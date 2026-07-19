# Blinkit Review Discovery Engine

Scrapes public user feedback about Blinkit, tags it with an AI pipeline, and
surfaces quantified insights about why users don't explore new categories.

## Status

Phase 0 (scaffold) complete. Reddit scraping is skipped for now (no PRAW app
credentials available) — Play Store and App Store are the active sources.
AI tagging runs on **Groq** (not Anthropic) — set `GROQ_API_KEY` in `.env`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then fill in GROQ_API_KEY
```

## Run

```bash
python run_pipeline.py --init      # create data/reviews.db with empty schema
```

Later phases add scraping, cleaning, tagging, aggregation, and the Streamlit
app (`streamlit run app.py`).

## Repo structure

```
app.py                  # Streamlit UI (Phase 7)
scrapers/
    play_store.py       # Google Play scraper (Phase 1)
    app_store.py         # App Store RSS scraper (Phase 2)
pipeline/
    clean.py            # dedupe, lang detect, spam filter (Phase 3)
    tagger.py            # Groq batch tagging (Phase 4)
    aggregate.py         # builds matrices/counts (Phase 6)
    validation.py         # AI-vs-human holdout validation (Phase 5)
prompts/
    tagging_prompt.md    # tagging system prompt (Phase 4)
data/
    reviews.db           # SQLite store (reviews, tags)
    exports/             # CSV exports for the deck
run_pipeline.py          # CLI: scrape -> clean -> tag -> aggregate
```
