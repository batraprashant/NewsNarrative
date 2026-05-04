"""Integration tests for fetch lifecycle and UI fallback behavior."""

from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_ARTICLES = [
    {"title": "T1", "source": {"name": "S1"}, "description": "D1",
     "publishedAt": "2026-05-01", "url": "https://example.com/1"},
]
SAMPLE_WEEKS = [("2026-01-01 to 2026-01-08", [])]
SAMPLE_NARRATIVE = "## Today's Top Stories\nGenerated text"


def _patch_fetch(monkeypatch, narrative=SAMPLE_NARRATIVE, news_error=None, narrative_error=None):
    """Patch fetcher.fetch_news_only and fetcher.generate_narrative."""
    def fake_fetch_news_only():
        if news_error:
            raise news_error
        return SAMPLE_ARTICLES, SAMPLE_WEEKS

    def fake_generate_narrative(today_articles, past_weeks):
        if narrative_error:
            raise narrative_error
        return narrative

    monkeypatch.setattr("fetcher.fetch_news_only", fake_fetch_news_only)
    monkeypatch.setattr("fetcher.generate_narrative", fake_generate_narrative)


# ---------------------------------------------------------------------------
# fetch_and_save — FetchRun recording
# ---------------------------------------------------------------------------

def test_fetch_and_save_success_records_fetch_run(app_module, client, monkeypatch):
    _patch_fetch(monkeypatch)
    app_module.fetch_and_save(force=True)

    with app_module.app.app_context():
        run = app_module.FetchRun.query.order_by(app_module.FetchRun.started_at.desc()).first()
        assert run is not None
        assert run.status == "success"
        assert run.duration_seconds is not None


def test_fetch_and_save_news_failure_records_failed_run(app_module, client, monkeypatch):
    """If NewsAPI call raises, FetchRun should be marked 'failed'."""
    _patch_fetch(monkeypatch, news_error=RuntimeError("newsapi down"))
    app_module.fetch_and_save(force=True)

    with app_module.app.app_context():
        run = app_module.FetchRun.query.order_by(app_module.FetchRun.started_at.desc()).first()
        assert run is not None
        assert run.status == "failed"
        assert "newsapi down" in (run.error_message or "")


def test_fetch_and_save_narrative_failure_records_partial_run(app_module, client, monkeypatch):
    """If only narrative generation fails, FetchRun should be 'partial' (not 'failed')."""
    _patch_fetch(monkeypatch, narrative_error=RuntimeError("openai down"))
    app_module.fetch_and_save(force=True)

    with app_module.app.app_context():
        run = app_module.FetchRun.query.order_by(app_module.FetchRun.started_at.desc()).first()
        assert run is not None
        assert run.status == "partial"
        assert "openai down" in (run.error_message or "")


# ---------------------------------------------------------------------------
# Index route fallback behaviour
# ---------------------------------------------------------------------------

def test_index_shows_today_record_when_it_exists(client, app_module):
    """Index should show today's narrative record even if content is empty."""
    today = datetime.utcnow().date()
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=today, content="## Today's content")
        app_module.db.session.add(n)
        app_module.db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert b"Today" in response.data


def test_index_falls_back_to_most_recent_when_no_today_record(client, app_module):
    """If there is no record for today, index falls back to the most recent date."""
    yesterday = datetime.utcnow().date() - timedelta(days=1)
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=yesterday, content="### Older narrative")
        app_module.db.session.add(n)
        app_module.db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert b"Older narrative" in response.data


def test_index_shows_empty_state_when_no_narratives(client):
    """Index should show the empty-state UI when the database has no narratives."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"No news yet" in response.data
