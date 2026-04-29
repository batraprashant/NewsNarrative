"""Pytest fixtures for NewsNarrative smoke tests."""

import importlib
import os

import pytest


@pytest.fixture(scope="session")
def app_module():
    """Import the Flask app module with test-safe environment variables."""
    os.environ["TESTING"] = "1"
    os.environ["NEWS_API_KEY"] = "test-news-key"
    os.environ["OPENAI_API_KEY"] = "test-openai-key"
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

    module = importlib.import_module("app")
    module.app.config.update(TESTING=True)
    return module


@pytest.fixture()
def client(app_module):
    """Provide an isolated Flask test client with a clean DB."""
    with app_module.app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
    return app_module.app.test_client()
