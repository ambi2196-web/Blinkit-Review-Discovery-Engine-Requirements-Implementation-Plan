"""Validate AI tagging against hand labels on a holdout sample.

Two steps, run separately:
  1. `--sample`: pick 50 relevant reviews, export to data/exports/holdout.csv
     with the AI's tags plus two empty columns (human_categories_mentioned,
     human_barrier_type) for a human to fill in by hand. Do NOT let a model
     fill these in - that defeats the point of validation.
  2. `--score`: after the human columns are filled (comma-separated taxonomy
     slugs, e.g. "trust_quality, price_perception"), compute exact-match %
     and per-barrier/per-category precision & recall, write
     validation_report.md.

Usage:
    python pipeline/validation.py --sample
    ... hand-label data/exports/holdout.csv in Excel/Sheets ...
    python pipeline/validation.py --score
"""
import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
HOLDOUT_CSV = Path(__file__).parent.parent / "data" / "exports" / "holdout.csv"
REPORT_PATH = Path(__file__).parent.parent / "validation_report.md"
SAMPLE_SIZE = 50

VALID_CATEGORIES = {
    "grocery_staples", "fresh_produce", "snacks_beverages", "household_cleaning",
    "personal_care", "beauty_cosmetics", "baby_care", "pet_supplies",
    "pharma_wellness", "electronics_accessories", "home_kitchen", "festive_seasonal",
}
VALID_BARRIERS = {
    "habit_autopilot", "trust_quality", "price_perception", "awareness",
    "occasion_mismatch", "assortment_doubt", "ux_findability", "past_bad_experience",
}


def sample_holdout():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        """SELECT r.id, r.text, r.source, r.rating, r.date, r.lang,
                  t.categories_mentioned AS ai_categories_mentioned,
                  t.barrier_type AS ai_barrier_type,
                  t.discovery_channel AS ai_discovery_channel,
                  t.sentiment AS ai_sentiment
           FROM tags t JOIN reviews r ON r.id = t.review_id
           WHERE t.relevant = 1""",
        conn,
    )
    conn.close()

    if len(df) == 0:
        print("No relevant tagged reviews yet - run pipeline/tagger.py first.")
        return

    # Prioritize non-English rows for language diversity, fill the rest randomly.
    non_en = df[df["lang"] != "en"]
    en = df[df["lang"] == "en"]
    n_non_en = min(len(non_en), SAMPLE_SIZE // 2)
    picked_non_en = non_en.sample(n_non_en, random_state=42) if n_non_en else non_en.iloc[0:0]
    remaining = SAMPLE_SIZE - len(picked_non_en)
    picked_en = en.sample(min(remaining, len(en)), random_state=42)
    holdout = pd.concat([picked_non_en, picked_en]).sample(frac=1, random_state=42).reset_index(drop=True)

    holdout["human_categories_mentioned"] = ""
    holdout["human_barrier_type"] = ""

    HOLDOUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    holdout.to_csv(HOLDOUT_CSV, index=False)
    print(f"Sampled {len(holdout)} relevant reviews ({len(picked_non_en)} non-English) to {HOLDOUT_CSV}")
    print("Fill in human_categories_mentioned and human_barrier_type (comma-separated slugs), then run --score.")
    print(f"Valid categories: {sorted(VALID_CATEGORIES)}")
    print(f"Valid barriers: {sorted(VALID_BARRIERS)}")


def parse_slugs(value, valid_set) -> set:
    if pd.isna(value) or not str(value).strip():
        return set()
    return {s.strip().lower() for s in str(value).split(",") if s.strip().lower() in valid_set}


def parse_ai_list(value) -> set:
    if pd.isna(value) or not str(value).strip():
        return set()
    return set(json.loads(value))


def score_holdout():
    if not HOLDOUT_CSV.exists():
        print("No holdout.csv - run --sample first.")
        return

    df = pd.read_csv(HOLDOUT_CSV)
    unlabeled = df["human_barrier_type"].isna() & df["human_categories_mentioned"].isna()
    if unlabeled.all():
        print("holdout.csv hasn't been hand-labeled yet - fill in human_categories_mentioned and human_barrier_type first.")
        return

    df["ai_cats"] = df["ai_categories_mentioned"].apply(parse_ai_list)
    df["ai_barriers"] = df["ai_barrier_type"].apply(parse_ai_list)
    df["human_cats"] = df["human_categories_mentioned"].apply(lambda v: parse_slugs(v, VALID_CATEGORIES))
    df["human_barriers"] = df["human_barrier_type"].apply(lambda v: parse_slugs(v, VALID_BARRIERS))

    exact_match = ((df["ai_cats"] == df["human_cats"]) & (df["ai_barriers"] == df["human_barriers"])).mean()

    def prf(label_set_name, valid_set, ai_col, human_col):
        rows = []
        for label in sorted(valid_set):
            tp = fp = fn = 0
            for ai_set, human_set in zip(df[ai_col], df[human_col]):
                ai_has, human_has = label in ai_set, label in human_set
                if ai_has and human_has:
                    tp += 1
                elif ai_has and not human_has:
                    fp += 1
                elif human_has and not ai_has:
                    fn += 1
            support = tp + fn
            if support == 0 and tp + fp == 0:
                continue
            precision = tp / (tp + fp) if (tp + fp) else None
            recall = tp / (tp + fn) if (tp + fn) else None
            rows.append({"label": label, "support": support, "precision": precision, "recall": recall})
        return pd.DataFrame(rows)

    barrier_prf = prf("barrier", VALID_BARRIERS, "ai_barriers", "human_barriers")
    category_prf = prf("category", VALID_CATEGORIES, "ai_cats", "human_cats")

    n = len(df)
    lines = [
        f"# Validation report ({n}-review holdout)",
        "",
        f"**Exact-match rate (categories AND barriers both match exactly): {exact_match:.0%}**",
        "",
        "## Per-barrier precision/recall",
        "",
        barrier_prf.to_markdown(index=False, floatfmt=".2f") if not barrier_prf.empty else "_no barriers labeled in holdout_",
        "",
        "## Per-category precision/recall",
        "",
        category_prf.to_markdown(index=False, floatfmt=".2f") if not category_prf.empty else "_no categories labeled in holdout_",
    ]
    report = "\n".join(lines)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWritten to {REPORT_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Validate AI tags against hand labels")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample", action="store_true", help="Sample 50 relevant reviews to holdout.csv")
    group.add_argument("--score", action="store_true", help="Score a hand-labeled holdout.csv")
    args = parser.parse_args()

    if args.sample:
        sample_holdout()
    else:
        score_holdout()


if __name__ == "__main__":
    main()
