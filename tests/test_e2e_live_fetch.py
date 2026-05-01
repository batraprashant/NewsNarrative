"""Optional live end-to-end test against external APIs."""

import os

import pytest


@pytest.mark.e2e
def test_live_fetch_all_generates_non_empty_narrative():
    if os.environ.get("RUN_E2E", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set RUN_E2E=1 to execute live E2E fetch test.")
    if not os.environ.get("NEWS_API_KEY") or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("NEWS_API_KEY and OPENAI_API_KEY are required for live E2E tests.")

    from fetcher import fetch_all

    narrative_text, today_articles, past_weeks = fetch_all()
    assert (narrative_text or "").strip()
    assert isinstance(today_articles, list)
    assert isinstance(past_weeks, list)
