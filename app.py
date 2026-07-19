"""Blinkit Review Discovery Engine - Streamlit dashboard.

Reads read-only from data/reviews.db (committed to the repo). The only
runtime API call is the "Try it live" tab, capped at 10 calls/session.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from pipeline.aggregate import (
    barrier_category_matrix,
    barrier_ranks,
    discovery_channel_distribution,
    load_relevant,
    monthly_trend,
    segment_barrier_index,
)

DB_PATH = Path(__file__).parent / "data" / "reviews.db"
PROMPT_PATH = Path(__file__).parent / "prompts" / "tagging_prompt.md"
VALIDATION_REPORT_PATH = Path(__file__).parent / "validation_report.md"

LIVE_DEMO_MODEL = os.getenv("GROQ_TAGGING_MODEL", "llama-3.3-70b-versatile")
LIVE_DEMO_LIMIT = 10

st.set_page_config(page_title="Blinkit Review Discovery Engine", layout="wide")


def get_api_key():
    try:
        return st.secrets["GROQ_API_KEY"]
    except (KeyError, FileNotFoundError):
        return os.getenv("GROQ_API_KEY")


DROPPED_CSV = Path(__file__).parent / "data" / "exports" / "dropped_reviews.csv"


@st.cache_data
def load_overview(_mtime: float) -> dict:
    conn = sqlite3.connect(DB_PATH)
    total = pd.read_sql("SELECT COUNT(*) c FROM reviews", conn)["c"][0]
    by_source = pd.read_sql("SELECT source, COUNT(*) c FROM reviews GROUP BY source", conn)
    date_range = pd.read_sql("SELECT MIN(date) lo, MAX(date) hi FROM reviews", conn).iloc[0]
    tagged = pd.read_sql("SELECT COUNT(*) c FROM tags", conn)["c"][0]
    relevant = pd.read_sql("SELECT COUNT(*) c FROM tags WHERE relevant=1", conn)["c"][0]
    conn.close()
    dropped = len(pd.read_csv(DROPPED_CSV)) if DROPPED_CSV.exists() else 0
    eligible = total - dropped
    return {
        "total": total, "by_source": by_source, "date_range": date_range,
        "tagged": tagged, "relevant": relevant, "eligible": eligible,
    }


@st.cache_data
def load_tagged_df(_mtime: float) -> pd.DataFrame:
    return load_relevant()


def db_mtime() -> float:
    return DB_PATH.stat().st_mtime if DB_PATH.exists() else 0.0


st.title("Blinkit Review Discovery Engine")
st.caption("Why don't users explore new categories on Blinkit? Evidence from scraped reviews.")

mtime = db_mtime()
overview = load_overview(mtime)
df = load_tagged_df(mtime)

tab_overview, tab_matrix, tab_deepdive, tab_segments, tab_live, tab_method = st.tabs(
    ["Overview", "Barrier Matrix", "Barrier Deep-Dive", "Segments", "Try It Live", "Methodology"]
)

with tab_overview:
    st.subheader("Corpus overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total reviews scraped", overview["total"])
    c2.metric("Reviews tagged", overview["tagged"])
    pct_relevant = (overview["relevant"] / overview["tagged"] * 100) if overview["tagged"] else 0
    c3.metric("% relevant (of tagged)", f"{pct_relevant:.0f}%")
    c4.metric("Date range", f"{overview['date_range']['lo'][:10]} to {overview['date_range']['hi'][:10]}")

    st.write("**Reviews by source**")
    st.bar_chart(overview["by_source"].set_index("source"))

    if overview["tagged"] < overview["eligible"]:
        st.info(
            f"Tagging in progress: {overview['tagged']}/{overview['eligible']} cleaned, eligible "
            f"reviews tagged so far ({overview['total'] - overview['eligible']} of the {overview['total']} "
            "scraped reviews were filtered out in cleaning - too short, duplicate, or pure delivery/app "
            "rants with no product signal - and are never tagged). Free-tier API rate limits mean "
            "tagging fills in over several days; charts below update automatically as more gets tagged."
        )

with tab_matrix:
    st.subheader("Barrier x Category matrix")
    st.caption("Cell = number of reviews mentioning that barrier for that category.")
    if df.empty:
        st.warning("No tagged reviews yet.")
    else:
        matrix = barrier_category_matrix(df)
        if matrix.empty:
            st.warning("No barrier/category co-occurrences tagged yet.")
        else:
            fig = px.imshow(
                matrix, text_auto=True, aspect="auto",
                labels=dict(x="Category", y="Barrier", color="Mentions"),
                color_continuous_scale="Reds",
            )
            fig.update_layout(height=500)
            st.plotly_chart(fig, width="stretch")

with tab_deepdive:
    st.subheader("Barrier deep-dive")
    if df.empty:
        st.warning("No tagged reviews yet.")
    else:
        ranks = barrier_ranks(df)
        if ranks.empty:
            st.warning("No barriers tagged yet.")
        else:
            chosen = st.selectbox("Pick a barrier", ranks.index.tolist())
            sub = df[df["barrier_type"].apply(lambda bs: chosen in bs)]

            st.write(f"**{len(sub)} reviews** mention `{chosen}`")

            cat_counts = pd.Series(
                [c for cats in sub["categories_mentioned"] for c in cats]
            ).value_counts()
            if not cat_counts.empty:
                st.write("**Categories involved**")
                st.bar_chart(cat_counts)

            trend = monthly_trend(df)
            if not trend.empty and chosen in trend.columns:
                st.write("**Trend over time**")
                st.line_chart(trend[chosen])

            st.write("**Top quotes**")
            quoted = sub[sub["verbatim_quote"].notna()].head(10)
            for _, row in quoted.iterrows():
                st.markdown(f"> {row['verbatim_quote']}  \n*{row['source']}, {row['date'][:10]}*")

with tab_segments:
    st.subheader("Segments")
    if df.empty:
        st.warning("No tagged reviews yet.")
    else:
        seg_counts = pd.Series(
            [s for segs in df["segment_signals"] for s in segs]
        ).value_counts()
        if seg_counts.empty:
            st.warning("No segment signals tagged yet.")
        else:
            st.write("**Segment frequency**")
            st.bar_chart(seg_counts)

            st.write("**Barrier over-indexing by segment** (min. 5 reviews per segment)")
            seg_index = segment_barrier_index(df)
            if seg_index.empty:
                st.info("Not enough tagged reviews yet for statistically meaningful segment breakdowns.")
            else:
                st.dataframe(seg_index, width="stretch")

with tab_live:
    st.subheader("Try it live")
    st.caption(f"Paste any Blinkit-style review and see the tagging pipeline run in real time (model: {LIVE_DEMO_MODEL}).")

    if "live_calls" not in st.session_state:
        st.session_state.live_calls = 0

    remaining = LIVE_DEMO_LIMIT - st.session_state.live_calls
    st.caption(f"{remaining} demo calls remaining this session")

    demo_text = st.text_area("Review text", placeholder="e.g. I always reorder the same groceries, never tried the pet supplies section...")

    if st.button("Tag this review", disabled=remaining <= 0):
        api_key = get_api_key()
        if not api_key:
            st.error("GROQ_API_KEY not configured for this app.")
        elif not demo_text.strip():
            st.warning("Enter some review text first.")
        else:
            from groq import Groq, RateLimitError

            st.session_state.live_calls += 1
            system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
            payload = [{"id": "live_demo", "text": demo_text, "rating": None, "source": "live_demo"}]
            try:
                client = Groq(api_key=api_key)
                resp = client.chat.completions.create(
                    model=LIVE_DEMO_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload)},
                    ],
                    max_tokens=500,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                st.json(json.loads(resp.choices[0].message.content))
            except RateLimitError:
                st.error("The tagging model's free-tier quota is exhausted right now - try again later.")
            except Exception as e:
                st.error(f"Tagging failed: {e}")

with tab_method:
    st.subheader("Methodology")
    st.markdown(
        """
**Pipeline:** scrape (Play Store + App Store) -> clean (dedupe, short-review filter,
delivery-rant-with-no-category-signal filter) -> tag (Groq `llama-3.3-70b-versatile`,
batched 25 reviews/call, JSON-only output against a fixed taxonomy) -> aggregate
(barrier x category matrix, segment lift, discovery-channel distribution) -> this app.

**Taxonomies:** 8 barrier types (habit_autopilot, trust_quality, price_perception,
awareness, occasion_mismatch, assortment_doubt, ux_findability, past_bad_experience)
x 12 product categories. See `prompts/tagging_prompt.md` for the full spec and few-shot examples.

**Non-destructive cleaning:** dropped reviews (too-short, near-duplicate, or pure
delivery/app rants with zero product signal) are never deleted from `reviews.db` -
they're logged with a reason in `data/exports/dropped_reviews.csv` for audit.
        """
    )
    with st.expander("Validation: AI tags vs. hand labels"):
        if VALIDATION_REPORT_PATH.exists():
            st.markdown(VALIDATION_REPORT_PATH.read_text(encoding="utf-8"))
        else:
            st.info("Validation not yet run (Phase 5). See `pipeline/validation.py`.")
