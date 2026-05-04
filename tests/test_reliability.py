"""Tests for reliability paths: two-step save, regenerate, and index UI fallback."""

from datetime import datetime, timedelta

import pytest


SAMPLE_ARTICLES = [
    {"title": "T1", "source": {"name": "S1"}, "description": "D1",
     "publishedAt": "2026-05-01", "url": "https://example.com/1"},
]
SAMPLE_WEEKS = [("2026-01-01 to 2026-01-08", [])]
SAMPLE_NARRATIVE = "## Today's Top Stories\nGenerated text"


# ---------------------------------------------------------------------------
# Two-step save: articles must survive narrative failure
# ---------------------------------------------------------------------------

def test_articles_saved_when_narrative_fails(app_module, client, monkeypatch):
    """Articles must be persisted even when OpenAI narrative generation raises."""
    monkeypatch.setattr("fetcher.fetch_news_only", lambda: (SAMPLE_ARTICLES, SAMPLE_WEEKS))

    def _raise(*_):
        raise RuntimeError("openai down")

    monkeypatch.setattr("fetcher.generate_narrative", _raise)

    app_module.fetch_and_save(force=True)

    # fetch_and_save uses datetime.now() (local time); match that here
    today = datetime.now().date()
    with app_module.app.app_context():
        narrative = app_module.Narrative.query.filter_by(fetch_date=today).first()
        assert narrative is not None, "Narrative row should be created even on failure"
        assert len(narrative.articles) == len(SAMPLE_ARTICLES)


def test_two_step_save_narrative_content_on_success(app_module, client, monkeypatch):
    """On full success both articles and narrative content must be persisted."""
    monkeypatch.setattr("fetcher.fetch_news_only", lambda: (SAMPLE_ARTICLES, SAMPLE_WEEKS))
    monkeypatch.setattr("fetcher.generate_narrative", lambda *_: SAMPLE_NARRATIVE)

    app_module.fetch_and_save(force=True)

    today = datetime.now().date()
    with app_module.app.app_context():
        narrative = app_module.Narrative.query.filter_by(fetch_date=today).first()
        assert narrative is not None
        assert narrative.content.strip() != ""
        assert len(narrative.articles) == len(SAMPLE_ARTICLES)


# ---------------------------------------------------------------------------
# regenerate_narrative_for_date
# ---------------------------------------------------------------------------

def test_regenerate_fills_empty_narrative(app_module, client, monkeypatch):
    """regenerate_narrative_for_date should write narrative text when content is empty."""
    today = datetime.utcnow().date()
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=today, content="")
        app_module.db.session.add(n)
        app_module.db.session.flush()
        app_module.db.session.add(app_module.Article(
            narrative_id=n.id,
            title="T1", source="S1", description="D1",
            url="https://example.com/1", published_at="2026-05-01",
            article_type="today",
        ))
        app_module.db.session.commit()

    monkeypatch.setattr("fetcher.generate_narrative", lambda *_: SAMPLE_NARRATIVE)
    app_module.regenerate_narrative_for_date(today)

    with app_module.app.app_context():
        n = app_module.Narrative.query.filter_by(fetch_date=today).first()
        assert (n.content or "").strip() != ""


def test_regenerate_skips_when_content_already_exists(app_module, client, monkeypatch):
    """regenerate_narrative_for_date should not overwrite a narrative that already has content."""
    today = datetime.utcnow().date()
    original = "## Original content"
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=today, content=original)
        app_module.db.session.add(n)
        app_module.db.session.commit()

    called = []
    monkeypatch.setattr("fetcher.generate_narrative", lambda *_: called.append(1) or SAMPLE_NARRATIVE)
    app_module.regenerate_narrative_for_date(today)

    assert called == [], "generate_narrative should not be called when content exists"
    with app_module.app.app_context():
        n = app_module.Narrative.query.filter_by(fetch_date=today).first()
        assert n.content == original


def test_regenerate_skips_for_unknown_date(app_module, client, monkeypatch):
    """regenerate_narrative_for_date should be a no-op for a date with no DB record."""
    future_date = datetime.utcnow().date() + timedelta(days=365)
    called = []
    monkeypatch.setattr("fetcher.generate_narrative", lambda *_: called.append(1) or SAMPLE_NARRATIVE)

    # Should not raise
    app_module.regenerate_narrative_for_date(future_date)
    assert called == []


def test_regenerate_skips_when_no_articles(app_module, client, monkeypatch):
    """regenerate_narrative_for_date should not call OpenAI when there are no articles."""
    today = datetime.utcnow().date()
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=today, content="")
        app_module.db.session.add(n)
        app_module.db.session.commit()

    called = []
    monkeypatch.setattr("fetcher.generate_narrative", lambda *_: called.append(1) or SAMPLE_NARRATIVE)
    app_module.regenerate_narrative_for_date(today)

    assert called == [], "generate_narrative should not be called when there are no articles"


# ---------------------------------------------------------------------------
# /regenerate/<date> route
# ---------------------------------------------------------------------------

def test_regenerate_route_redirects_on_valid_date(app_module, client, monkeypatch):
    """POST /regenerate/<date> should redirect (302) for a valid date string."""
    today = datetime.utcnow().date()
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=today, content="")
        app_module.db.session.add(n)
        app_module.db.session.commit()

    monkeypatch.setattr("fetcher.generate_narrative", lambda *_: SAMPLE_NARRATIVE)
    response = client.post(f"/regenerate/{today.isoformat()}")
    assert response.status_code == 302


def test_regenerate_route_rejects_invalid_date(app_module, client):
    """POST /regenerate/bad-date should redirect without crashing."""
    response = client.post("/regenerate/not-a-date")
    assert response.status_code == 302


def test_regenerate_route_rejects_when_fetch_in_progress(app_module, client, monkeypatch):
    """POST /regenerate while _is_fetching=True should flash a warning and redirect."""
    today = datetime.utcnow().date()

    original = app_module._is_fetching
    app_module._is_fetching = True
    try:
        response = client.post(f"/regenerate/{today.isoformat()}")
        assert response.status_code == 302
    finally:
        app_module._is_fetching = original


# ---------------------------------------------------------------------------
# Index UI: empty narrative shows Regenerate button
# ---------------------------------------------------------------------------

def test_index_shows_regenerate_button_when_narrative_empty(client, app_module):
    """When today's narrative exists but content is empty, the Regenerate button should appear."""
    today = datetime.utcnow().date()
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=today, content="")
        app_module.db.session.add(n)
        app_module.db.session.flush()
        app_module.db.session.add(app_module.Article(
            narrative_id=n.id,
            title="T1", source="S1", description="D1",
            url="https://example.com/1", published_at="2026-05-01",
            article_type="today",
        ))
        app_module.db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert b"Regenerate" in response.data


def test_index_shows_narrative_content_when_present(client, app_module):
    """When narrative content exists, it should appear in the rendered page."""
    today = datetime.utcnow().date()
    with app_module.app.app_context():
        n = app_module.Narrative(fetch_date=today, content="## Today's Top Stories\nSome text")
        app_module.db.session.add(n)
        app_module.db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert b"Today" in response.data
