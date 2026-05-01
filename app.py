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
from zoneinfo import ZoneInfo

import markdown as md
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, url_for
from markupsafe import Markup

load_dotenv()

from models import Article, FetchRun, Narrative, db

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
_is_regenerating = False
_last_fetch_error = None


def _save_articles(today_articles, past_weeks, fetch_date):
    """Transaction 1: persist articles with an empty narrative placeholder.
    Returns the new Narrative.id."""
    with app.app_context():
        existing = Narrative.query.filter_by(fetch_date=fetch_date).first()
        if existing:
            db.session.delete(existing)
            db.session.flush()

        narrative = Narrative(fetch_date=fetch_date, content="")
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
        LOGGER.info(
            "Articles saved for %s (today=%d, past_weeks=%d).",
            fetch_date,
            len(today_articles),
            sum(len(arts) for _, arts in past_weeks),
        )
        return narrative.id


def _save_narrative_content(narrative_id, content):
    """Transaction 2: update the narrative placeholder with generated text."""
    with app.app_context():
        narrative = db.session.get(Narrative, narrative_id)
        if not narrative:
            raise ValueError(f"Narrative {narrative_id} not found when saving content.")
        narrative.content = content
        db.session.commit()
        LOGGER.info("Narrative content saved (%d chars) for id=%d.", len(content), narrative_id)


def _start_fetch_run(force):
    with app.app_context():
        run = FetchRun(
            trigger_type="manual" if force else "scheduled",
            status="running",
            started_at=datetime.utcnow(),
        )
        db.session.add(run)
        db.session.commit()
        return run.id


def _finish_fetch_run(run_id, status, duration_seconds, error_message=None):
    if run_id is None:
        return
    with app.app_context():
        run = db.session.get(FetchRun, run_id)
        if not run:
            return
        run.status = status
        run.completed_at = datetime.utcnow()
        run.duration_seconds = duration_seconds
        run.error_message = (error_message or "")[:2000] or None
        db.session.commit()


def fetch_and_save(force=False):
    global _is_fetching, _last_fetch_error
    run_started = time.perf_counter()
    fetch_run_id = None

    with _fetch_lock:
        if _is_fetching:
            LOGGER.info("Fetch skipped — another fetch is already in progress.")
            return
        _is_fetching = True
        _last_fetch_error = None

    LOGGER.info("Fetch run started (force=%s).", force)

    try:
        from fetcher import fetch_news_only, generate_narrative

        fetch_run_id = _start_fetch_run(force)
        today = datetime.now().date()

        with app.app_context():
            if not force and Narrative.query.filter_by(fetch_date=today).first():
                LOGGER.info("Already fetched for %s; skipping scheduled fetch.", today)
                return

        # ── Step 1: Fetch articles (NewsAPI) ──────────────────────────────
        # Committed immediately so articles are visible even if narrative fails.
        LOGGER.info("Step 1: fetching articles for %s.", today)
        today_articles, past_weeks = fetch_news_only()
        narrative_id = _save_articles(today_articles, past_weeks, today)

        # ── Step 2: Generate narrative (OpenAI) ───────────────────────────
        # Failure here is non-fatal: articles are already saved.
        LOGGER.info("Step 2: generating narrative for %s.", today)
        try:
            narrative_text = generate_narrative(today_articles, past_weeks)
            _save_narrative_content(narrative_id, narrative_text)
            _last_fetch_error = None
            elapsed = time.perf_counter() - run_started
            _finish_fetch_run(fetch_run_id, "success", elapsed)
            LOGGER.info("Fetch complete for %s (%.2fs).", today, elapsed)
        except Exception as narrative_exc:
            elapsed = time.perf_counter() - run_started
            _finish_fetch_run(fetch_run_id, "partial", elapsed, str(narrative_exc))
            _last_fetch_error = (
                "Articles saved but narrative generation failed — "
                f"{narrative_exc}. Try clicking Fetch Now again."
            )
            LOGGER.exception("Narrative generation failed after %.2fs.", elapsed)

    except Exception as exc:
        elapsed = time.perf_counter() - run_started
        _finish_fetch_run(fetch_run_id, "failed", elapsed, str(exc))
        _last_fetch_error = (
            "News fetch failed. Check your NEWS_API_KEY and server logs."
        )
        LOGGER.exception("Fetch run failed after %.2fs: %s", elapsed, exc)
    finally:
        with _fetch_lock:
            _is_fetching = False
        LOGGER.info("Fetch lock released.")


def regenerate_narrative_for_date(fetch_date):
    """Re-run only the OpenAI narrative step for a date that already has articles.
    Safe to call when articles exist but content is empty (e.g. after a daemon-thread kill)."""
    global _is_regenerating, _last_fetch_error
    with _fetch_lock:
        if _is_regenerating or _is_fetching:
            LOGGER.info("Regeneration skipped — fetch/regeneration already in progress.")
            return
        _is_regenerating = True

    LOGGER.info("Narrative regeneration started for %s.", fetch_date)
    try:
        from fetcher import generate_narrative

        with app.app_context():
            narrative = Narrative.query.filter_by(fetch_date=fetch_date).first()
            if not narrative:
                LOGGER.warning("Regeneration: no narrative record found for %s.", fetch_date)
                return
            if (narrative.content or "").strip():
                LOGGER.info("Regeneration: %s already has content, skipping.", fetch_date)
                return

            def art_to_dict(a):
                return {"title": a.title, "source": {"name": a.source},
                        "description": a.description, "publishedAt": a.published_at}

            today_dicts = [art_to_dict(a) for a in narrative.today_articles]
            weeks_dicts = [(lbl, [art_to_dict(a) for a in arts])
                           for lbl, arts in narrative.weekly_groups]

        if not today_dicts:
            LOGGER.warning("Regeneration: no articles found for %s, cannot generate.", fetch_date)
            return

        LOGGER.info("Regeneration: calling OpenAI for %s (%d articles).", fetch_date, len(today_dicts))
        narrative_text = generate_narrative(today_dicts, weeks_dicts)
        _save_narrative_content(narrative.id, narrative_text)
        _last_fetch_error = None
        LOGGER.info("Regeneration complete for %s (%d chars).", fetch_date, len(narrative_text))
    except Exception as exc:
        _last_fetch_error = f"Narrative regeneration failed: {exc}"
        LOGGER.exception("Regeneration failed for %s: %s", fetch_date, exc)
    finally:
        with _fetch_lock:
            _is_regenerating = False


# ---------------------------------------------------------------------------
# Scheduler: auto-fetch daily at 06:00 America/Los_Angeles
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    fetch_and_save,
    "cron",
    hour=6,
    minute=0,
    timezone=ZoneInfo("America/Los_Angeles"),
    id="daily_fetch",
    replace_existing=True,
    misfire_grace_time=3600,
)
if os.environ.get("TESTING", "").lower() not in {"1", "true", "yes"}:
    scheduler.start()
    job = scheduler.get_job("daily_fetch")
    if job:
        LOGGER.info("Auto-fetch scheduled for %s", job.next_run_time)

    # Startup recovery: if today has articles but no narrative (e.g. daemon thread
    # was killed mid-run last time), kick off a background regeneration immediately.
    def _startup_recovery():
        from datetime import date as _date
        today = _date.today()
        with app.app_context():
            n = Narrative.query.filter_by(fetch_date=today).first()
            if n and not (n.content or "").strip() and n.articles:
                LOGGER.info("Startup recovery: today has articles but no narrative — regenerating.")
                regenerate_narrative_for_date(today)

    threading.Thread(target=_startup_recovery, daemon=True).start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    today = datetime.now().date()
    # Show today's record if it exists (even with empty narrative — template handles that).
    # Only fall back to a previous date if there is no record at all for today.
    narrative = Narrative.query.filter_by(fetch_date=today).first()
    if not narrative:
        narrative = Narrative.query.order_by(Narrative.fetch_date.desc()).first()
    latest_fetch_run = FetchRun.query.order_by(FetchRun.started_at.desc()).first()
    return render_template(
        "index.html",
        narrative=narrative,
        today=today,
        fetching=_is_fetching or _is_regenerating,
        fetch_error=_last_fetch_error,
        latest_fetch_run=latest_fetch_run,
    )


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
    if not (narrative.content or "").strip():
        flash("This saved narrative is empty due to an earlier generation failure.", "warning")
        return redirect(url_for("index"))
    today = datetime.now().date()
    return render_template(
        "index.html",
        narrative=narrative,
        today=today,
        fetching=_is_fetching,
        fetch_error=_last_fetch_error,
        latest_fetch_run=FetchRun.query.order_by(FetchRun.started_at.desc()).first(),
    )


@app.route("/regenerate/<date_str>", methods=["POST"])
def trigger_regenerate(date_str):
    try:
        fetch_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return redirect(url_for("index"))
    if _is_fetching or _is_regenerating:
        flash("A fetch or regeneration is already in progress. Please wait.", "warning")
    else:
        thread = threading.Thread(
            target=lambda: regenerate_narrative_for_date(fetch_date), daemon=True
        )
        thread.start()
        flash("Regenerating narrative — this takes about 60 seconds. Page will refresh automatically.", "info")
    return redirect(url_for("index"))


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
