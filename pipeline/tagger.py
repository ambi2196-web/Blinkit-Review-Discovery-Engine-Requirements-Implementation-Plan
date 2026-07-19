"""Batch-tag reviews via Groq using prompts/tagging_prompt.md.

Idempotent: only tags reviews with no row in `tags` yet, and skips ids in
data/exports/dropped_reviews.csv (Phase 3's cleaning output).

Usage:
    python pipeline/tagger.py                 # tag everything untagged
    python pipeline/tagger.py --limit 100      # tag only the next 100 (test run)
"""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from groq import APIStatusError, Groq, RateLimitError
from tqdm import tqdm

load_dotenv()

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
DROPPED_CSV = Path(__file__).parent.parent / "data" / "exports" / "dropped_reviews.csv"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "tagging_prompt.md"

MODEL = os.getenv("GROQ_TAGGING_MODEL", "llama-3.3-70b-versatile")
BATCH_SIZE = 25
MAX_TOKENS = 3200  # 25-item batches with llama-3.3-70b need more room than the
                    # 2000 figure in the original Claude-Haiku-sized spec (see
                    # README note on the Groq swap)
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

class DailyQuotaExceeded(Exception):
    pass


REQUIRED_FIELDS = [
    "relevant", "sentiment", "categories_mentioned", "barrier_type",
    "discovery_channel", "segment_signals", "verbatim_quote",
]

# Models occasionally invent categories/barriers outside the fixed taxonomy
# (e.g. "dairy" instead of "grocery_staples") despite explicit instructions.
# Filter to the canonical sets so the barrier x category matrix stays clean.
VALID_CATEGORIES = {
    "grocery_staples", "fresh_produce", "snacks_beverages", "household_cleaning",
    "personal_care", "beauty_cosmetics", "baby_care", "pet_supplies",
    "pharma_wellness", "electronics_accessories", "home_kitchen", "festive_seasonal",
}
VALID_BARRIERS = {
    "habit_autopilot", "trust_quality", "price_perception", "awareness",
    "occasion_mismatch", "assortment_doubt", "ux_findability", "past_bad_experience",
}
VALID_CHANNELS = {"search", "browse", "reorder", "offer", "word_of_mouth", "none_stated"}

# Groq free-tier list pricing is $0; kept configurable in case that changes.
INPUT_PRICE_PER_1M = float(os.getenv("GROQ_INPUT_PRICE_PER_1M", "0"))
OUTPUT_PRICE_PER_1M = float(os.getenv("GROQ_OUTPUT_PRICE_PER_1M", "0"))


def get_untagged_reviews(limit: int = None) -> list:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        """SELECT r.id, r.text, r.rating, r.source
           FROM reviews r LEFT JOIN tags t ON r.id = t.review_id
           WHERE t.review_id IS NULL
           ORDER BY r.id""",
        conn,
    )
    conn.close()

    if DROPPED_CSV.exists():
        dropped_ids = set(pd.read_csv(DROPPED_CSV)["id"])
        df = df[~df["id"].isin(dropped_ids)]

    if limit:
        df = df.head(limit)

    return df.to_dict("records")


def build_user_message(batch: list) -> str:
    payload = [{"id": r["id"], "text": r["text"], "rating": r["rating"], "source": r["source"]} for r in batch]
    return json.dumps(payload, ensure_ascii=False)


def normalize_tag(tag: dict) -> dict:
    if not tag.get("relevant"):
        return {
            "id": tag.get("id"),
            "relevant": False,
            "sentiment": None,
            "categories_mentioned": [],
            "barrier_type": [],
            "discovery_channel": None,
            "segment_signals": [],
            "verbatim_quote": None,
        }
    for field in REQUIRED_FIELDS:
        tag.setdefault(field, None)
    tag["categories_mentioned"] = [c for c in (tag["categories_mentioned"] or []) if c in VALID_CATEGORIES]
    tag["barrier_type"] = [b for b in (tag["barrier_type"] or []) if b in VALID_BARRIERS]
    if tag["discovery_channel"] not in VALID_CHANNELS:
        tag["discovery_channel"] = "none_stated"
    return tag


def call_groq(client: Groq, system_prompt: str, batch: list, cost_log: dict):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_user_message(batch)},
    ]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except RateLimitError as e:
            msg = str(e)
            if "per day" in msg.lower() or "TPD" in msg:
                raise DailyQuotaExceeded(msg) from None
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(f"  Rate limited, retrying in {wait:.0f}s...")
            time.sleep(wait)
            continue
        except APIStatusError as e:
            if attempt == MAX_RETRIES:
                raise
            wait = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(f"  API error ({e.status_code}), retrying in {wait:.0f}s...")
            time.sleep(wait)
            continue

        if resp.usage:
            cost_log["prompt_tokens"] += resp.usage.prompt_tokens
            cost_log["completion_tokens"] += resp.usage.completion_tokens

        content = resp.choices[0].message.content
        try:
            parsed = json.loads(content)
            return parsed.get("tags", [])
        except json.JSONDecodeError:
            if attempt == MAX_RETRIES:
                print("  JSON parse failed after retries, skipping batch")
                return []
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "That was not valid JSON. Return only valid JSON matching the schema, no other text."})

    return []


def upsert_tags(conn: sqlite3.Connection, tags: list, batch_ids: set):
    rows = []
    tagged_ids = set()
    for tag in tags:
        tag = normalize_tag(tag)
        review_id = tag.get("id")
        if review_id not in batch_ids:
            continue
        tagged_ids.add(review_id)
        rows.append((
            review_id,
            tag["relevant"],
            tag["sentiment"],
            json.dumps(tag["categories_mentioned"], ensure_ascii=False),
            json.dumps(tag["barrier_type"], ensure_ascii=False),
            tag["discovery_channel"],
            json.dumps(tag["segment_signals"], ensure_ascii=False),
            tag["verbatim_quote"],
            MODEL,
            datetime.now().isoformat(),
        ))

    conn.executemany(
        """INSERT OR REPLACE INTO tags
           (review_id, relevant, sentiment, categories_mentioned, barrier_type,
            discovery_channel, segment_signals, verbatim_quote, model, tagged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return tagged_ids


def run(limit: int = None):
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY not set. Add it to .env (see .env.example).")

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    reviews = get_untagged_reviews(limit=limit)
    if not reviews:
        print("Nothing to tag.")
        return

    conn = sqlite3.connect(DB_PATH)
    cost_log = {"prompt_tokens": 0, "completion_tokens": 0}
    missing_ids = []
    tagged_this_run = 0
    batches_attempted = 0

    batches = [reviews[i:i + BATCH_SIZE] for i in range(0, len(reviews), BATCH_SIZE)]
    quota_hit = False
    for batch in tqdm(batches, desc="tagging", unit="batch"):
        batch_ids = {r["id"] for r in batch}
        try:
            tags = call_groq(client, system_prompt, batch, cost_log)
        except DailyQuotaExceeded:
            print(f"\nGroq daily token quota reached for {MODEL}.")
            print("Progress so far is saved. Re-run this script once the quota resets (Groq's 429 message includes the wait time) to continue - it picks up where it left off.")
            quota_hit = True
            break
        batches_attempted += 1
        tagged_ids = upsert_tags(conn, tags, batch_ids)
        tagged_this_run += len(tagged_ids)
        missing_ids.extend(batch_ids - tagged_ids)

    conn.close()

    total_tokens = cost_log["prompt_tokens"] + cost_log["completion_tokens"]
    cost = (cost_log["prompt_tokens"] / 1_000_000 * INPUT_PRICE_PER_1M
            + cost_log["completion_tokens"] / 1_000_000 * OUTPUT_PRICE_PER_1M)

    print(f"Tagged {tagged_this_run} reviews this run")
    if missing_ids:
        print(f"  {len(missing_ids)} reviews not tagged (parse/API failures) - re-run to retry")
    if quota_hit:
        remaining = len(reviews) - (batches_attempted * BATCH_SIZE)
        print(f"  ~{remaining} reviews still untagged (quota-limited) - re-run later")
    print(f"Tokens: {cost_log['prompt_tokens']} in / {cost_log['completion_tokens']} out ({total_tokens} total)")
    print(f"Estimated cost: ${cost:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Tag Blinkit reviews via Groq")
    parser.add_argument("--limit", type=int, default=None, help="Only tag the next N untagged reviews")
    args = parser.parse_args()
    run(limit=args.limit)


if __name__ == "__main__":
    main()
