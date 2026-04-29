"""
NewsNarrative Flask web application.

Run:
    pip install -r requirements.txt
    cp .env.example .env   # fill in API keys
    python app.py
"""

import os
import threading
import logging
import time
from datetime import datetime

import markdown as md
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, url_for
from markupsafe import Markup

load_dotenv()

from models import Article, Narrative, db

# Basic startup/runtime logging for diagnostics.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)


def validate_startup_config():
    """Validate required configuration and log actionable diagnostics."""
    required_keys = ["NEWS_API_KEY", "OPENAI_API_KEY"]
    missing_keys = [key for key in required_keys if not os.environ.get(key)]
    if missing_keys:
        missing_list = ", ".join(missing_keys)
        raise RuntimeError(
            f"Missing required environment variables: {missing_list}. "
            "Create a .env file from .env.example and set these values."
        )

    if os.environ.get("SECRET_KEY", "change-me-in-production") == "change-me-in-production":
        LOGGER.warning(
            "SECRET_KEY is using the default value. Set SECRET_KEY in .env "
            "before deploying outside local development."
        )

    database_url = os.environ.get("DATABASE_URL", "sqlite:///newsnarrative.db")
    LOGGER.info("Startup configuration validated (DATABASE_URL=%s)", database_url)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

validate_startup_config()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///newsnarrative.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# Jinja2 filter: render Markdown to safe HTML
# ---------------------------------------------------------------------------

@app.template_filter("markdownify")
def markdownify(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return Markup(md.markdown(text.strip(), extensions=["nl2br"]))


# ---------------------------------------------------------------------------
# Background fetch state
# ---------------------------------------------------------------------------

_fetch_lock = threading.Lock()
_is_fetching = False


def _save_fetch_result(narrative_text, today_articles, past_weeks, fetch_date):
    start = time.perf_counter()
    with app.app_context():
        existing = Narrative.query.filter_by(fetch_date=fetch_date).first()
        if existing:
            db.session.delete(existing)
            db.session.flush()

        narrative = Narrative(fetch_date=fetch_date, content=narrative_text)
        db.session.add(narrative)
        db.session.flush()

        for a in today_articles:
            db.session.add(Article(
                narrative_id=narrative.id,
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
                    narrative_id=narrative.id,
                    title=a.get("title") or "No title",
                    source=(a.get("source") or {}).get("name") or "Unknown",
                    description=a.get("description") or "",
                    url=a.get("url") or "",
                    published_at=(a.get("publishedAt") or "")[:10],
                    article_type=f"week_{i}",
                    week_label=label,
                ))

        db.session.commit()
    weekly_count = sum(len(articles) for _, articles in past_weeks)
    elapsed = time.perf_counter() - start
    LOGGER.info(
        "Persist phase complete for %s (today=%d, past_weeks=%d, duration=%.2fs).",
        fetch_date.isoformat(),
        len(today_articles),
        weekly_count,
        elapsed,
    )


def fetch_and_save(force=False):
    global _is_fetching
    run_started = time.perf_counter()
    LOGGER.info("Fetch run requested (force=%s).", force)
    with _fetch_lock:
        if _is_fetching:
            LOGGER.info("Fetch run skipped because another fetch is already in progress.")
            return
        _is_fetching = True
    LOGGER.info("Fetch run started (force=%s).", force)

    try:
        from fetcher import fetch_all

        today = datetime.now().date()
        with app.app_context():
            if not force and Narrative.query.filter_by(fetch_date=today).first():
                LOGGER.info("Already fetched for %s; skipping scheduled fetch.", today)
                return

        LOGGER.info("Fetching news for %s...", today)
        narrative_text, today_articles, past_weeks = fetch_all()
        _save_fetch_result(narrative_text, today_articles, past_weeks, today)
        elapsed = time.perf_counter() - run_started
        LOGGER.info("Fetch run complete for %s (duration=%.2fs).", today, elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - run_started
        LOGGER.exception("Fetch run failed after %.2fs: %s", elapsed, exc)
    finally:
        with _fetch_lock:
            _is_fetching = False
        LOGGER.info("Fetch run released in-progress lock.")


# ---------------------------------------------------------------------------
# Scheduler: auto-fetch daily at 08:00
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(fetch_and_save, "cron", hour=8, minute=0)
if os.environ.get("TESTING", "").lower() not in {"1", "true", "yes"}:
    scheduler.start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    today = datetime.now().date()
    narrative = (
        Narrative.query.filter_by(fetch_date=today).first()
        or Narrative.query.order_by(Narrative.fetch_date.desc()).first()
    )
    return render_template("index.html", narrative=narrative, today=today, fetching=_is_fetching)


@app.route("/history")
def history():
    narratives = Narrative.query.order_by(Narrative.fetch_date.desc()).all()
    return render_template("history.html", narratives=narratives)


@app.route("/narrative/<date_str>")
def view_narrative(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return redirect(url_for("index"))
    narrative = Narrative.query.filter_by(fetch_date=d).first_or_404()
    today = datetime.now().date()
    return render_template("index.html", narrative=narrative, today=today, fetching=_is_fetching)


@app.route("/fetch", methods=["POST"])
def trigger_fetch():
    if _is_fetching:
        LOGGER.info("Manual fetch ignored: fetch already in progress.")
        flash("A fetch is already in progress. Please wait.", "warning")
    else:
        thread = threading.Thread(target=lambda: fetch_and_save(force=True), daemon=True)
        thread.start()
        LOGGER.info("Manual fetch accepted and background thread started.")
        flash("Fetching latest news — this takes about 30–60 seconds. Refresh shortly.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
