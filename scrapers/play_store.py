"""Google Play review scraper for com.grofers.customerapp (Blinkit).

Usage:
    python scrapers/play_store.py                 # full run: ~5000 en (12mo) + ~500 hi
    python scrapers/play_store.py --limit 200      # quick test: 200 en reviews, no cutoff
"""
import argparse
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from google_play_scraper import Sort, reviews
from tqdm import tqdm

APP_ID = "com.grofers.customerapp"
COUNTRY = "in"
DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
PAGE_SIZE = 200
SLEEP_SECONDS = 1.5

# (lang, target_count, respect_12mo_cutoff)
DEFAULT_TARGETS = [("en", 5000, True), ("hi", 500, True)]


def _cutoff_date(months: int = 12) -> datetime:
    return datetime.now() - timedelta(days=30 * months)


def fetch_lang(lang: str, target: int, cutoff) -> list:
    """Paginate Play Store reviews for one language, newest first."""
    collected = []
    token = None
    with tqdm(total=target, desc=f"play_store[{lang}]", unit="review") as pbar:
        while len(collected) < target:
            batch, token = reviews(
                APP_ID,
                lang=lang,
                country=COUNTRY,
                sort=Sort.NEWEST,
                count=min(PAGE_SIZE, target - len(collected)),
                continuation_token=token,
            )
            if not batch:
                break

            stop = False
            for entry in batch:
                if cutoff and entry["at"] < cutoff:
                    stop = True
                    break
                collected.append(entry)
                pbar.update(1)
                if len(collected) >= target:
                    break

            if stop or token is None:
                break
            time.sleep(SLEEP_SECONDS)

    return collected


def to_row(entry: dict, lang: str) -> tuple:
    return (
        entry["reviewId"],
        "play_store",
        entry["content"],
        entry["score"],
        entry["at"].isoformat(),
        lang,
        entry.get("thumbsUpCount"),
        f"https://play.google.com/store/apps/details?id={APP_ID}&reviewId={entry['reviewId']}",
        datetime.now().isoformat(),
    )


def upsert(conn: sqlite3.Connection, rows: list) -> int:
    cur = conn.executemany(
        """INSERT OR IGNORE INTO reviews
           (id, source, text, rating, date, lang, upvotes, url, scraped_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return cur.rowcount


def scrape(limit: int = None) -> int:
    conn = sqlite3.connect(DB_PATH)
    total_inserted = 0

    if limit:
        # Quick test run: single language, no date cutoff.
        targets = [("en", limit, False)]
    else:
        targets = DEFAULT_TARGETS

    for lang, target, use_cutoff in targets:
        cutoff = _cutoff_date(12) if use_cutoff else None
        entries = fetch_lang(lang, target, cutoff)
        rows = [to_row(e, lang) for e in entries]
        inserted = upsert(conn, rows)
        print(f"  {lang}: fetched {len(entries)}, inserted {inserted} new rows")
        total_inserted += inserted

    conn.close()
    return total_inserted


def main():
    parser = argparse.ArgumentParser(description="Scrape Blinkit Play Store reviews")
    parser.add_argument("--limit", type=int, default=None, help="Quick test: cap en reviews, skip cutoff")
    args = parser.parse_args()

    inserted = scrape(limit=args.limit)
    print(f"Done. {inserted} new rows inserted into {DB_PATH}")


if __name__ == "__main__":
    main()
