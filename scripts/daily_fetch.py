#!/usr/bin/env python3
"""
Standalone daily fetch script.

Fetches today's news and generates a narrative, writing results directly
to the SQLite database. Intended to be called by a system cron job or
launchd agent — completely independent of the Flask process.

Usage:
    python3 scripts/daily_fetch.py
    python3 scripts/daily_fetch.py --force   # re-fetch even if today already has data
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure the project root is on the path so app/models/fetcher import correctly.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="NewsNarrative daily fetch")
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch even if today already has data")
    args = parser.parse_args()

    # Validate env before doing any work
    missing = [k for k in ("NEWS_API_KEY", "OPENAI_API_KEY") if not os.environ.get(k)]
    if missing:
        LOGGER.error("Missing environment variables: %s", ", ".join(missing))
        sys.exit(1)

    os.environ.setdefault("TESTING", "1")   # prevents APScheduler from starting
    from app import app, db
    from models import Narrative, Article
    from fetcher import fetch_news_only, generate_narrative

    today = datetime.now().date()

    with app.app_context():
        existing = Narrative.query.filter_by(fetch_date=today).first()
        if existing and (existing.content or "").strip() and not args.force:
            LOGGER.info("Today (%s) already has a complete narrative. Use --force to re-fetch.", today)
            sys.exit(0)

    # ── Step 1: fetch articles ────────────────────────────────────────────
    LOGGER.info("Fetching articles for %s ...", today)
    today_articles, past_weeks = fetch_news_only()
    LOGGER.info("  today: %d articles, weeks: %s",
                len(today_articles),
                [len(arts) for _, arts in past_weeks])

    # ── Step 2: save articles ─────────────────────────────────────────────
    with app.app_context():
        existing = Narrative.query.filter_by(fetch_date=today).first()
        if existing:
            db.session.delete(existing)
            db.session.flush()

        narrative_row = Narrative(fetch_date=today, content="")
        db.session.add(narrative_row)
        db.session.flush()

        for a in today_articles:
            db.session.add(Article(
                narrative_id=narrative_row.id,
                title=a.get("title") or "No title",
                source=(a.get("source") or {}).get("name") or "Unknown",
                description=a.get("description") or "",
                url=a.get("url") or "",
                published_at=(a.get("publishedAt") or "")[:10],
                article_type="today",
            ))
        for i, (label, articles) in enumerate(past_weeks, 1):
            for a in articles:
                db.session.add(Article(
                    narrative_id=narrative_row.id,
                    title=a.get("title") or "No title",
                    source=(a.get("source") or {}).get("name") or "Unknown",
                    description=a.get("description") or "",
                    url=a.get("url") or "",
                    published_at=(a.get("publishedAt") or "")[:10],
                    article_type=f"week_{i}",
                    week_label=label,
                ))
        db.session.commit()
        narrative_id = narrative_row.id
    LOGGER.info("Articles saved (narrative id=%d).", narrative_id)

    # ── Step 3: generate narrative ────────────────────────────────────────
    LOGGER.info("Generating narrative via OpenAI ...")
    narrative_text = generate_narrative(today_articles, past_weeks)
    LOGGER.info("  Generated %d chars.", len(narrative_text))

    with app.app_context():
        narrative_row = db.session.get(Narrative, narrative_id)
        narrative_row.content = narrative_text
        db.session.commit()
    LOGGER.info("Narrative saved. Done.")


if __name__ == "__main__":
    main()
