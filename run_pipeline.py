"""CLI entrypoint: scrape -> clean -> tag -> aggregate.

Usage:
    python run_pipeline.py --init      # create data/reviews.db with empty schema
"""
import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "reviews.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    rating INTEGER,
    date TEXT,
    lang TEXT,
    upvotes INTEGER,
    url TEXT,
    scraped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    review_id TEXT PRIMARY KEY REFERENCES reviews(id),
    relevant BOOLEAN,
    sentiment TEXT,
    categories_mentioned TEXT,
    barrier_type TEXT,
    discovery_channel TEXT,
    segment_signals TEXT,
    verbatim_quote TEXT,
    model TEXT,
    tagged_at TEXT
);
"""


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Initialized {DB_PATH} with reviews + tags tables.")


def main():
    parser = argparse.ArgumentParser(description="Blinkit discovery engine pipeline")
    parser.add_argument("--init", action="store_true", help="Create reviews.db with empty schema")
    args = parser.parse_args()

    if args.init:
        init_db()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
