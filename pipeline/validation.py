"""Validate AI tagging on a holdout sample.

Two independent things live here, don't confuse them:
  1. Human validation (`--sample` / `--score`): `--sample` picks 50 relevant
     reviews, exports to data/exports/holdout.csv with the AI's tags plus two
     empty columns (human_categories_mentioned, human_barrier_type) for a
     human to fill in by hand. `--score` then computes exact-match % and
     per-barrier/per-category precision & recall against those hand labels.
     No model may fill in the human_* columns - that defeats the point.
  2. AI self-consistency (`--self-consistency`): re-tags the same 50 holdout
     reviews in a fresh, independent call (single-review context instead of
     the original's batch-of-25 context, temperature 0.4 instead of 0) and
     measures how much the model agrees with itself. This is NOT a
     substitute for human validation - it only tells you whether the tagger
     is stable, not whether it's correct. Writes self_consistency_report.md,
     clearly labeled as such.

Usage:
    python pipeline/validation.py --sample
    ... hand-label data/exports/holdout.csv in Excel/Sheets ...
    python pipeline/validation.py --score
    python pipeline/validation.py --self-consistency
"""
import argparse
import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
HOLDOUT_CSV = Path(__file__).parent.parent / "data" / "exports" / "holdout.csv"
SELF_CONSISTENCY_CSV = Path(__file__).parent.parent / "data" / "exports" / "self_consistency.csv"
REPORT_PATH = Path(__file__).parent.parent / "validation_report.md"
SELF_CONSISTENCY_REPORT_PATH = Path(__file__).parent.parent / "self_consistency_report.md"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "tagging_prompt.md"
SAMPLE_SIZE = 50
SELF_CONSISTENCY_MODEL = os.getenv("GROQ_TAGGING_MODEL", "llama-3.3-70b-versatile")
SELF_CONSISTENCY_TEMPERATURE = 0.4

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


def self_consistency_check():
    if not HOLDOUT_CSV.exists():
        print("No holdout.csv - run --sample first.")
        return
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("GROQ_API_KEY not set. Add it to .env (see .env.example).")

    from groq import Groq, RateLimitError

    from tagger import normalize_tag

    df = pd.read_csv(HOLDOUT_CSV)
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    run2_cats, run2_barriers, quota_hit = [], [], False
    for i, row in df.iterrows():
        if quota_hit:
            run2_cats.append(None)
            run2_barriers.append(None)
            continue
        payload = [{"id": row["id"], "text": row["text"], "rating": row.get("rating"), "source": row.get("source")}]
        try:
            resp = client.chat.completions.create(
                model=SELF_CONSISTENCY_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_tokens=500,
                temperature=SELF_CONSISTENCY_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            tags = json.loads(resp.choices[0].message.content).get("tags", [])
            tag = normalize_tag(tags[0]) if tags else normalize_tag({"id": row["id"], "relevant": False})
            run2_cats.append(json.dumps(tag["categories_mentioned"]))
            run2_barriers.append(json.dumps(tag["barrier_type"]))
        except RateLimitError:
            print(f"\nQuota hit at row {i}/{len(df)} - stopping, partial results will be scored.")
            quota_hit = True
            run2_cats.append(None)
            run2_barriers.append(None)
        print(f"  {i + 1}/{len(df)}", end="\r")

    df["run2_categories_mentioned"] = run2_cats
    df["run2_barrier_type"] = run2_barriers
    df.to_csv(SELF_CONSISTENCY_CSV, index=False)

    scored = df[df["run2_categories_mentioned"].notna()].copy()
    if scored.empty:
        print("\nNo rows scored (quota exhausted immediately) - try again later.")
        return

    scored["run1_cats"] = scored["ai_categories_mentioned"].apply(parse_ai_list)
    scored["run1_barriers"] = scored["ai_barrier_type"].apply(parse_ai_list)
    scored["run2_cats"] = scored["run2_categories_mentioned"].apply(parse_ai_list)
    scored["run2_barriers"] = scored["run2_barrier_type"].apply(parse_ai_list)

    exact_match = ((scored["run1_cats"] == scored["run2_cats"]) & (scored["run1_barriers"] == scored["run2_barriers"])).mean()

    def agreement(valid_set, col1, col2):
        rows = []
        for label in sorted(valid_set):
            both = neither = only1 = only2 = 0
            for s1, s2 in zip(scored[col1], scored[col2]):
                h1, h2 = label in s1, label in s2
                if h1 and h2: both += 1
                elif not h1 and not h2: neither += 1
                elif h1: only1 += 1
                else: only2 += 1
            n = both + neither + only1 + only2
            if both + only1 + only2 == 0:
                continue
            rows.append({"label": label, "agree_rate": round((both + neither) / n, 2), "run1_only": only1, "run2_only": only2, "both": both})
        return pd.DataFrame(rows)

    barrier_agreement = agreement(VALID_BARRIERS, "run1_barriers", "run2_barriers")
    category_agreement = agreement(VALID_CATEGORIES, "run1_cats", "run2_cats")

    n = len(scored)
    lines = [
        f"# AI self-consistency check ({n}/{len(df)} holdout reviews re-tagged)",
        "",
        "**This is NOT human validation.** It measures whether the tagger gives the same "
        "answer to itself under a different context (single-review call vs. the original's "
        f"batch-of-25 context) and mild sampling variation (temperature {SELF_CONSISTENCY_TEMPERATURE} "
        "vs. the original's 0). It tells you the tagger is *stable*, not that it's *correct* - "
        "for correctness, human-labeled validation (`--score`) is still needed.",
        "",
        f"**Exact-match rate between the two runs: {exact_match:.0%}**",
        "",
        "## Per-barrier agreement",
        "",
        barrier_agreement.to_markdown(index=False) if not barrier_agreement.empty else "_no barriers tagged in either run_",
        "",
        "## Per-category agreement",
        "",
        category_agreement.to_markdown(index=False) if not category_agreement.empty else "_no categories tagged in either run_",
    ]
    report = "\n".join(lines)
    SELF_CONSISTENCY_REPORT_PATH.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\nWritten to {SELF_CONSISTENCY_REPORT_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Validate AI tags against hand labels")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample", action="store_true", help="Sample 50 relevant reviews to holdout.csv")
    group.add_argument("--score", action="store_true", help="Score a hand-labeled holdout.csv")
    group.add_argument("--self-consistency", action="store_true", help="Re-tag the holdout independently and measure agreement with itself")
    args = parser.parse_args()

    if args.sample:
        sample_holdout()
    elif args.score:
        score_holdout()
    else:
        self_consistency_check()


if __name__ == "__main__":
    main()
