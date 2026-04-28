"""
NewsNarrative Flask web application.

Run:
    pip install -r requirements.txt
    cp .env.example .env   # fill in API keys
    python app.py
"""

import os
import threading
from datetime import datetime

import markdown as md
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, url_for
from markupsafe import Markup

load_dotenv()

from models import Article, Narrative, db

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

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
    return Markup(md.markdown(text or "", extensions=["nl2br"]))


# ---------------------------------------------------------------------------
# Background fetch state
# ---------------------------------------------------------------------------

_fetch_lock = threading.Lock()
_is_fetching = False


def _save_fetch_result(narrative_text, today_articles, past_weeks, fetch_date):
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


def fetch_and_save(force=False):
    global _is_fetching
    with _fetch_lock:
        if _is_fetching:
            return
        _is_fetching = True

    try:
        from fetcher import fetch_all

        today = datetime.now().date()
        with app.app_context():
            if not force and Narrative.query.filter_by(fetch_date=today).first():
                print(f"Already fetched for {today}, skipping.")
                return

        print(f"Fetching news for {today} ...")
        narrative_text, today_articles, past_weeks = fetch_all()
        _save_fetch_result(narrative_text, today_articles, past_weeks, today)
        print("Fetch complete.")
    except Exception as exc:
        print(f"Fetch error: {exc}")
    finally:
        with _fetch_lock:
            _is_fetching = False


# ---------------------------------------------------------------------------
# Scheduler: auto-fetch daily at 08:00
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(fetch_and_save, "cron", hour=8, minute=0)
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
        flash("A fetch is already in progress. Please wait.", "warning")
    else:
        thread = threading.Thread(target=lambda: fetch_and_save(force=True), daemon=True)
        thread.start()
        flash("Fetching latest news — this takes about 30–60 seconds. Refresh shortly.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
