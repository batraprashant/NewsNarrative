"""Basic route smoke tests for NewsNarrative."""


def test_index_route_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"NewsNarrative" in response.data


def test_history_route_renders(client):
    response = client.get("/history")
    assert response.status_code == 200


def test_invalid_narrative_date_redirects_to_index(client):
    response = client.get("/narrative/not-a-date", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_manual_fetch_starts_background_thread(client, app_module, monkeypatch):
    started = {"value": False}

    class DummyThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            started["value"] = True

    monkeypatch.setattr(app_module.threading, "Thread", DummyThread)

    response = client.post("/fetch", follow_redirects=False)

    assert response.status_code == 302
    assert started["value"] is True
