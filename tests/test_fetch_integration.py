"""Integration tests for fetch lifecycle and UI fallback behavior."""

from datetime import datetime, timedelta


def test_fetch_and_save_success_records_fetch_run(app_module, monkeypatch):
    def fake_fetch_all():
        return (
            "## Today's Top Stories\nGenerated text",
            [{"title": "T1", "source": {"name": "S1"}, "description": "D1"}],
            [("2026-01-01 to 2026-01-08", [])],
        )

    monkeypatch.setattr("fetcher.fetch_all", fake_fetch_all)
    app_module.fetch_and_save(force=True)

    with app_module.app.app_context():
        run = app_module.FetchRun.query.order_by(app_module.FetchRun.started_at.desc()).first()
        assert run is not None
        assert run.status == "success"
        assert run.duration_seconds is not None


def test_fetch_and_save_failure_records_error(app_module, monkeypatch):
    def fake_fetch_all():
        raise RuntimeError("boom")

    monkeypatch.setattr("fetcher.fetch_all", fake_fetch_all)
    app_module.fetch_and_save(force=True)

    with app_module.app.app_context():
        run = app_module.FetchRun.query.order_by(app_module.FetchRun.started_at.desc()).first()
        assert run is not None
        assert run.status == "failed"
        assert "boom" in (run.error_message or "")


def test_index_falls_back_to_latest_non_empty_narrative(client, app_module):
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)

    with app_module.app.app_context():
        blank_today = app_module.Narrative(fetch_date=today, content="   ")
        older_good = app_module.Narrative(fetch_date=yesterday, content="### Older narrative")
        app_module.db.session.add(blank_today)
        app_module.db.session.add(older_good)
        app_module.db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert b"Older narrative" in response.data
