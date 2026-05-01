"""Unit tests for fetcher helpers and narrative retry logic."""

import fetcher


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Message(content)
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [_Choice(content, finish_reason)]


class _Completions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):  # noqa: ARG002 - signature mirrors SDK call site
        return self._responses.pop(0)


class _Chat:
    def __init__(self, responses):
        self.completions = _Completions(responses)


class _Client:
    def __init__(self, responses):
        self.chat = _Chat(responses)


def test_extract_message_text_from_string():
    assert fetcher._extract_message_text(_Message("hello world")) == "hello world"


def test_extract_message_text_from_content_parts():
    parts = [
        {"type": "output_text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
    assert fetcher._extract_message_text(_Message(parts)) == "first\nsecond"


def test_generate_narrative_retries_then_succeeds(monkeypatch):
    responses = [
        _Response("", finish_reason="length"),
        _Response("## Today's Top Stories\nNarrative content", finish_reason="stop"),
    ]
    client = _Client(responses)
    monkeypatch.setattr(fetcher, "_openai_client", lambda: client)

    result = fetcher.generate_narrative(
        today_articles=[{"title": "A", "source": {"name": "S"}, "description": "D"}],
        past_weeks=[("2026-01-01 to 2026-01-08", [])],
    )
    assert "Narrative content" in result


def test_generate_narrative_raises_after_empty_attempts(monkeypatch):
    responses = [
        _Response("", finish_reason="length"),
        _Response("", finish_reason="length"),
    ]
    client = _Client(responses)
    monkeypatch.setattr(fetcher, "_openai_client", lambda: client)

    try:
        fetcher.generate_narrative(
            today_articles=[{"title": "A", "source": {"name": "S"}, "description": "D"}],
            past_weeks=[("2026-01-01 to 2026-01-08", [])],
        )
        assert False, "Expected RuntimeError for empty narrative content."
    except RuntimeError as exc:
        assert "empty content" in str(exc)
