"""News fetching and narrative generation logic."""

import os
import logging
import time
from datetime import datetime, timedelta

import requests
from openai import OpenAI

LOGGER = logging.getLogger(__name__)


def _news_api_key():
    return os.environ["NEWS_API_KEY"]


def _openai_client():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def _extract_message_text(message):
    """Extract plain text from OpenAI message content across SDK shapes."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(item["text"])
                elif item.get("type") == "output_text" and item.get("text"):
                    parts.append(item["text"])
            else:
                item_type = getattr(item, "type", None)
                item_text = getattr(item, "text", None)
                if item_type in {"text", "output_text"} and item_text:
                    parts.append(item_text)
        return "\n".join(parts)
    return ""


def fetch_top_headlines_today():
    start = time.perf_counter()
    LOGGER.info("Fetch phase: requesting today's top headlines from NewsAPI.")
    resp = requests.get(
        "https://newsapi.org/v2/top-headlines",
        params={"country": "us", "pageSize": 10, "apiKey": _news_api_key()},
        timeout=15,
    )
    resp.raise_for_status()
    articles = resp.json().get("articles", [])[:10]
    elapsed = time.perf_counter() - start
    LOGGER.info(
        "Fetch phase complete: today's headlines retrieved (%d articles in %.2fs).",
        len(articles),
        elapsed,
    )
    return articles


def fetch_top_articles_for_week(from_date, to_date):
    start = time.perf_counter()
    LOGGER.info(
        "Fetch phase: requesting weekly articles from %s to %s.",
        from_date.isoformat(),
        to_date.isoformat(),
    )
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": "news",
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "sortBy": "popularity",
            "language": "en",
            "pageSize": 10,
            "apiKey": _news_api_key(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        LOGGER.warning(
            "Fetch phase warning: weekly article request returned non-ok status for %s to %s.",
            from_date.isoformat(),
            to_date.isoformat(),
        )
        return []
    articles = data.get("articles", [])[:10]
    elapsed = time.perf_counter() - start
    LOGGER.info(
        "Fetch phase complete: weekly articles retrieved (%s to %s, %d articles in %.2fs).",
        from_date.isoformat(),
        to_date.isoformat(),
        len(articles),
        elapsed,
    )
    return articles


def _format_article_list(articles):
    lines = []
    for i, a in enumerate(articles, 1):
        title = a.get("title") or "No title"
        source = (a.get("source") or {}).get("name") or "Unknown"
        desc = a.get("description") or ""
        pub = (a.get("publishedAt") or "")[:10]
        lines.append(f"{i}. [{source}] {title} ({pub})")
        if desc:
            lines.append(f"   {desc.strip()}")
    return "\n".join(lines)


def generate_narrative(today_articles, past_weeks):
    """Call OpenAI GPT-4o and return a Markdown-formatted narrative string."""
    start = time.perf_counter()
    LOGGER.info(
        "Generation phase: creating narrative from %d today articles and %d week groups.",
        len(today_articles),
        len(past_weeks),
    )
    today_block = _format_article_list(today_articles)
    weekly_blocks = []
    for i, (label, articles) in enumerate(past_weeks, 1):
        content = _format_article_list(articles) if articles else "  (no articles retrieved)"
        weekly_blocks.append(f"**Week {i}** ({label}):\n{content}")
    weekly_block = "\n\n".join(weekly_blocks)

    prompt = f"""You are an experienced journalist and narrative writer.
Using only the news headlines and descriptions provided below, craft a compelling,
well-structured narrative (800–1200 words) in **Markdown** format.

Your narrative must:
1. Open with the most significant stories from TODAY
2. Identify recurring themes and trends across the PAST 4 WEEKS
3. Draw connections between stories where relevant
4. Close with a "Big Picture" section contextualising what these stories mean together

Use these exact Markdown headings:
## Today's Top Stories
## Weekly Trends
### Week 1
### Week 2
### Week 3
### Week 4
## The Big Picture

Be analytical, not sensational. Cite source names where helpful.

---

TODAY'S TOP 10 NEWS:
{today_block}

---

PAST 4 WEEKS – TOP 10 PER WEEK:
{weekly_block}
"""
    attempt_limits = [4096, 8192]
    last_finish_reason = None

    for attempt_num, token_limit in enumerate(attempt_limits, start=1):
        LOGGER.info(
            "Generation attempt %d/%d with max_completion_tokens=%d.",
            attempt_num,
            len(attempt_limits),
            token_limit,
        )
        response = _openai_client().chat.completions.create(
            model="gpt-5.5",
            max_completion_tokens=token_limit,
            messages=[{"role": "user", "content": prompt}],
        )

        choice = response.choices[0]
        content = _extract_message_text(choice.message).strip()
        last_finish_reason = choice.finish_reason

        # Strip wrapping ```markdown ... ``` code fences some models add
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]  # drop the opening fence line
            if content.endswith("```"):
                content = content.rsplit("```", 1)[0]
        narrative = content.strip()
        if narrative:
            elapsed = time.perf_counter() - start
            LOGGER.info(
                "Generation phase complete: narrative generated (%d chars in %.2fs).",
                len(narrative),
                elapsed,
            )
            return narrative

        LOGGER.warning(
            "Generation attempt %d returned empty content (finish_reason=%s).",
            attempt_num,
            choice.finish_reason,
        )

    raise RuntimeError(
        "Narrative generation returned empty content "
        f"(finish_reason={last_finish_reason})."
    )


def fetch_all():
    """Fetch today + 4 weeks of articles and generate a narrative.

    Returns:
        (narrative_text, today_articles, past_weeks)
        where past_weeks = [(label, articles), ...]
    """
    start = time.perf_counter()
    today = datetime.now().date()
    LOGGER.info("Fetch lifecycle started for %s.", today.isoformat())

    today_articles = fetch_top_headlines_today()

    past_weeks = []
    for week_num in range(1, 5):
        to_date = today - timedelta(days=(week_num - 1) * 7)
        from_date = today - timedelta(days=week_num * 7)
        label = f"{from_date} to {to_date}"
        articles = fetch_top_articles_for_week(from_date, to_date)
        past_weeks.append((label, articles))

    narrative_text = generate_narrative(today_articles, past_weeks)
    elapsed = time.perf_counter() - start
    weekly_count = sum(len(articles) for _, articles in past_weeks)
    LOGGER.info(
        "Fetch lifecycle complete for %s (today=%d, past_weeks=%d, duration=%.2fs).",
        today.isoformat(),
        len(today_articles),
        weekly_count,
        elapsed,
    )
    return narrative_text, today_articles, past_weeks
