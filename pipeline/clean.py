"""Clean the raw reviews corpus: dedupe, drop noise, refine language tags.

Design note: this does NOT delete rows from reviews.db. Deletion is
destructive and reviews.db is the committed dataset of record - instead,
dropped ids are written to data/exports/dropped_reviews.csv (with a reason)
so they're auditable, and Phase 4's tagger reads that file to skip them.
The `lang` column is updated in place (refining the scraper's best guess).

Usage:
    python pipeline/clean.py
"""
import hashlib
import re
import sqlite3
from pathlib import Path

import pandas as pd
from langdetect import LangDetectException, detect

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
DROPPED_CSV = Path(__file__).parent.parent / "data" / "exports" / "dropped_reviews.csv"
MIN_LENGTH = 20

RANT_FILTER_MAX_LENGTH = 200  # longer reviews almost always carry real substance

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")

RANT_PATTERNS = [
    "worst app", "worst service", "worst experience", "pathetic",
    "waste of time", "waste of money", "fake app", "scam app",
    "not working", "app crash", "app hangs", "app hang", "useless app",
    "delivery boy", "delivery late", "late delivery", "never delivered",
    "cancel my order", "cancelled my order", "refund not received",
    "customer care", "customer support", "rude delivery", "poor service",
    "bad service", "horrible app", "terrible app", "very bad app",
    "not good app", "worst delivery", "delivery partner rude",
]

CATEGORY_KEYWORDS = {
    "grocery_staples": ["grocery", "groceries", "rice", "atta", "flour", "dal", "oil", "sugar", "salt", "wheat"],
    "fresh_produce": ["vegetable", "vegetables", "fruit", "fruits", "sabzi", "onion", "tomato", "potato", "banana", "apple"],
    "snacks_beverages": ["snack", "snacks", "chips", "biscuit", "cold drink", "juice", "namkeen", "chocolate", "beverage"],
    "household_cleaning": ["detergent", "cleaning", "phenyl", "dishwash", "harpic", "surf", "cleaner"],
    "personal_care": ["shampoo", "toothpaste", "soap", "deodorant", "razor", "sanitary pad", "hygiene"],
    "beauty_cosmetics": ["makeup", "cosmetic", "lipstick", "moisturizer", "beauty", "skincare"],
    "baby_care": ["diaper", "diapers", "baby", "infant", "formula milk", "baby wipes"],
    "pet_supplies": ["pet food", "dog food", "cat food", "pet supplies", "dog treat", "cat litter"],
    "pharma_wellness": ["medicine", "tablet", "pharmacy", "vitamin", "syrup", "protein powder", "supplement"],
    "electronics_accessories": ["charger", "cable", "electronics", "earphone", "earbuds", "gadget", "batteries"],
    "home_kitchen": ["kitchen", "utensil", "cookware", "container", "bottle", "cutlery"],
    "festive_seasonal": ["diwali", "festive", "rakhi", "holi", "christmas", "gift pack", "festival"],
}
# Generic product/quality signal words - broader than the category taxonomy,
# but their presence means the review has *some* product substance, not just
# a delivery/app/payment rant. Erring permissive here is intentional: the
# AI tagger's `relevant` flag does the precise judgment call later, so this
# filter should only catch reviews with genuinely zero product signal.
PRODUCT_SIGNAL_WORDS = [
    "food", "item", "items", "product", "products", "packet", "packaging",
    "egg", "eggs", "milk", "bread", "meat", "chicken", "fish", "paneer",
    "curd", "cheese", "butter", "tea", "coffee", "ice", "quality", "fresh",
    "freshness", "expired", "expiry", "damaged", "spoiled", "rotten", "stale",
    "gift", "wrap", "wrapping", "size", "colour", "color", "brand", "piece",
    "pieces", "wrong item", "different item", "cigarette", "offer", "bogo",
    "discount", "coupon",
]

ALL_CATEGORY_WORDS = sorted({w for words in CATEGORY_KEYWORDS.values() for w in words} | set(PRODUCT_SIGNAL_WORDS))


def normalize_text(text: str) -> str:
    t = text.lower().strip()
    t = PUNCT_RE.sub(" ", t)
    t = WHITESPACE_RE.sub(" ", t).strip()
    return t


def detect_lang(text: str, fallback: str) -> str:
    has_deva = bool(DEVANAGARI_RE.search(text))
    has_latin = bool(LATIN_LETTER_RE.search(text))
    if has_deva and has_latin:
        return "hinglish"
    if has_deva:
        return "hi"
    try:
        return detect(text)
    except LangDetectException:
        return fallback or "en"


def is_delivery_rant_without_category(text_lower: str) -> bool:
    if not any(pattern in text_lower for pattern in RANT_PATTERNS):
        return False
    return not any(word in text_lower for word in ALL_CATEGORY_WORDS)


def clean():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT id, source, text, rating, date, lang FROM reviews ORDER BY date ASC", conn)
    before = len(df)

    reasons = {}  # id -> reason
    seen_hashes = set()

    for row in df.itertuples():
        text_lower = row.text.lower()

        if len(row.text.strip()) < MIN_LENGTH:
            reasons[row.id] = "too_short"
            continue

        norm_hash = hashlib.sha256(normalize_text(row.text).encode("utf-8")).hexdigest()
        if norm_hash in seen_hashes:
            reasons[row.id] = "duplicate"
            continue
        seen_hashes.add(norm_hash)

        if len(row.text) <= RANT_FILTER_MAX_LENGTH and is_delivery_rant_without_category(text_lower):
            reasons[row.id] = "delivery_rant_no_category"
            continue

    # Refine lang for every surviving + dropped row (cheap, harmless to run on all).
    updates = []
    for row in df.itertuples():
        new_lang = detect_lang(row.text, fallback=row.lang)
        if new_lang != row.lang:
            updates.append((new_lang, row.id))
    conn.executemany("UPDATE reviews SET lang = ? WHERE id = ?", updates)
    conn.commit()

    dropped_ids = set(reasons.keys())
    after = before - len(dropped_ids)

    DROPPED_CSV.parent.mkdir(parents=True, exist_ok=True)
    dropped_df = df[df["id"].isin(dropped_ids)].copy()
    dropped_df["reason"] = dropped_df["id"].map(reasons)
    dropped_df[["id", "source", "reason", "text"]].to_csv(DROPPED_CSV, index=False)

    reason_counts = dropped_df["reason"].value_counts().to_dict()
    conn.close()

    print(f"Before: {before} rows")
    print(f"After:  {after} rows ({len(dropped_ids)} dropped)")
    for reason, count in reason_counts.items():
        print(f"  {reason}: {count}")
    print(f"Lang updated on {len(updates)} rows")
    print(f"Dropped rows written to {DROPPED_CSV}")

    return before, after


if __name__ == "__main__":
    clean()
