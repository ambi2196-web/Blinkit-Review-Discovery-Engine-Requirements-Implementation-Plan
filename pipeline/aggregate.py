"""Build the barrier x category matrix and other aggregates from tagged reviews,
then synthesize a 10-bullet insight summary via one Groq call.

Works on whatever's tagged so far - tagger.py runs incrementally (quota-limited
on the free tier), and this script always reflects current progress, not a
fixed final dataset.

Usage:
    python pipeline/aggregate.py
"""
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
EXPORT_DIR = Path(__file__).parent.parent / "data" / "exports"
INSIGHTS_PATH = Path(__file__).parent.parent / "insights.md"

SYNTHESIS_MODEL = os.getenv("GROQ_SYNTHESIS_MODEL", "llama-3.1-8b-instant")


def load_relevant() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        """SELECT r.id, r.date, r.source, r.rating,
                  t.sentiment, t.categories_mentioned, t.barrier_type,
                  t.discovery_channel, t.segment_signals, t.verbatim_quote
           FROM tags t JOIN reviews r ON r.id = t.review_id
           WHERE t.relevant = 1""",
        conn,
    )
    conn.close()

    for col in ["categories_mentioned", "barrier_type", "segment_signals"]:
        df[col] = df[col].apply(lambda x: json.loads(x) if x else [])
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    return df


def barrier_category_matrix(df: pd.DataFrame) -> pd.DataFrame:
    counts = defaultdict(lambda: defaultdict(int))
    for _, row in df.iterrows():
        for b in set(row["barrier_type"]):
            for c in set(row["categories_mentioned"]):
                counts[b][c] += 1
    if not counts:
        return pd.DataFrame()
    return pd.DataFrame(counts).fillna(0).astype(int).T.sort_index()


def barrier_ranks(df: pd.DataFrame) -> pd.Series:
    counter = Counter()
    for barriers in df["barrier_type"]:
        counter.update(set(barriers))
    return pd.Series(counter, dtype=int).sort_values(ascending=False)


def discovery_channel_distribution(df: pd.DataFrame) -> pd.Series:
    return df["discovery_channel"].fillna("none_stated").value_counts()


MIN_SEGMENT_N = 5  # below this, lift ratios are small-sample noise, not signal


def segment_barrier_index(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    if total == 0:
        return pd.DataFrame()

    overall_counts = Counter()
    for barriers in df["barrier_type"]:
        overall_counts.update(set(barriers))
    overall_rates = {b: c / total for b, c in overall_counts.items()}

    all_segments = {s for segs in df["segment_signals"] for s in segs}
    rows = []
    for seg in all_segments:
        seg_df = df[df["segment_signals"].apply(lambda segs: seg in segs)]
        seg_n = len(seg_df)
        if seg_n < MIN_SEGMENT_N:
            continue
        seg_counts = Counter()
        for barriers in seg_df["barrier_type"]:
            seg_counts.update(set(barriers))
        for b, count in seg_counts.items():
            seg_rate = count / seg_n
            baseline = overall_rates.get(b, 0.0)
            lift = (seg_rate / baseline) if baseline else None
            rows.append({
                "segment": seg, "barrier": b, "segment_n": seg_n,
                "count": count, "segment_rate": round(seg_rate, 3),
                "baseline_rate": round(baseline, 3),
                "lift": round(lift, 2) if lift is not None else None,
            })
    if not rows:
        return pd.DataFrame(columns=["segment", "barrier", "segment_n", "count", "segment_rate", "baseline_rate", "lift"])
    return pd.DataFrame(rows).sort_values("lift", ascending=False, na_position="last")


def monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    counts = defaultdict(lambda: defaultdict(int))
    for _, row in df.iterrows():
        for b in set(row["barrier_type"]):
            counts[row["month"]][b] += 1
    if not counts:
        return pd.DataFrame()
    return pd.DataFrame(counts).fillna(0).astype(int).T.sort_index()


def export_all(df: pd.DataFrame) -> dict:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "barrier_category_matrix": barrier_category_matrix(df),
        "barrier_ranks": barrier_ranks(df).to_frame("count"),
        "discovery_channel_distribution": discovery_channel_distribution(df).to_frame("count"),
        "segment_barrier_index": segment_barrier_index(df),
        "monthly_trend": monthly_trend(df),
    }
    for name, table in outputs.items():
        table.to_csv(EXPORT_DIR / f"{name}.csv")
    return outputs


def synthesize_insights(df: pd.DataFrame, outputs: dict) -> str:
    if not os.getenv("GROQ_API_KEY"):
        return "GROQ_API_KEY not set - skipping synthesis."

    quotes = df[df["verbatim_quote"].notna()]["verbatim_quote"].drop_duplicates().head(40).tolist()

    context = {
        "total_relevant_reviews": len(df),
        "note": "This is a partial/in-progress tagging run, not the full corpus - treat percentages as directional, not final.",
        "barrier_ranks": outputs["barrier_ranks"]["count"].to_dict(),
        "discovery_channel_distribution": outputs["discovery_channel_distribution"]["count"].to_dict(),
        "top_segment_barrier_lifts": outputs["segment_barrier_index"].head(15).to_dict("records"),
        "sample_quotes": quotes,
    }

    system_prompt = (
        "You are a PM analyst. Given aggregated counts from a tagged review corpus "
        "about why Blinkit users don't explore new product categories, write exactly "
        "10 bullet points of insight. Every bullet MUST cite a specific count or "
        "number from the provided data - no vague claims. Output plain markdown "
        "bullets only, no preamble or headers."
    )

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=SYNTHESIS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        max_tokens=1500,
        temperature=0.2,
    )
    return resp.choices[0].message.content


def run():
    df = load_relevant()
    print(f"Loaded {len(df)} relevant tagged reviews")

    if len(df) == 0:
        print("No tagged reviews yet - run pipeline/tagger.py first.")
        return

    outputs = export_all(df)
    print(f"Barrier ranks:\n{outputs['barrier_ranks']}")
    print(f"\nDiscovery channel distribution:\n{outputs['discovery_channel_distribution']}")
    print(f"\nExported CSVs to {EXPORT_DIR}")

    insights = synthesize_insights(df, outputs)
    INSIGHTS_PATH.write_text(insights, encoding="utf-8")
    print(f"\nInsights written to {INSIGHTS_PATH}")


if __name__ == "__main__":
    run()
