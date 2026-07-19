"""Apple App Store review scraper for Blinkit (IN storefront), via RSS.

The customer-reviews RSS feed caps out around 500 recent reviews (10 pages
x 50/page) - there's no way to page further back, so this is a best-effort
recent-reviews pull, not a full history.

Usage:
    python scrapers/app_store.py
"""
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

APP_ID = "960335206"  # Blinkit: Groceries & more, IN storefront
COUNTRY = "in"
DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
MAX_PAGES = 10
SLEEP_SECONDS = 1.5
RSS_URL = "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/page={page}/json"


def fetch_page(page: int) -> list:
    url = RSS_URL.format(country=COUNTRY, app_id=APP_ID, page=page)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    entries = data.get("feed", {}).get("entry", [])
    return [e for e in entries if "im:rating" in e]  # drop the app-summary entry if present


def to_row(entry: dict):
    review_id = f"as_{entry['id']['label']}"
    text = entry["content"]["label"]
    rating = int(entry["im:rating"]["label"])
    date = entry["updated"]["label"]
    upvotes = int(entry.get("im:voteSum", {}).get("label", 0))
    url = entry.get("link", {}).get("attributes", {}).get("href", "")
    return (
        review_id,
        "app_store",
        text,
        rating,
        date,
        None,  # lang unknown until Phase 3 langdetect
        upvotes,
        url,
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


def scrape() -> int:
    conn = sqlite3.connect(DB_PATH)
    total_fetched = 0
    total_inserted = 0

    for page in range(1, MAX_PAGES + 1):
        entries = fetch_page(page)
        if not entries:
            print(f"  page {page}: empty, stopping")
            break

        rows = [to_row(e) for e in entries]
        inserted = upsert(conn, rows)
        print(f"  page {page}: fetched {len(entries)}, inserted {inserted} new rows")
        total_fetched += len(entries)
        total_inserted += inserted

        if page < MAX_PAGES:
            time.sleep(SLEEP_SECONDS)

    conn.close()
    return total_fetched, total_inserted


def main():
    fetched, inserted = scrape()
    print(f"Done. fetched {fetched}, inserted {inserted} new rows into {DB_PATH}")


if __name__ == "__main__":
    main()
