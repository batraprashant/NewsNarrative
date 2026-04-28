"""News fetching and narrative generation logic."""

import os
from datetime import datetime, timedelta

import requests
from openai import OpenAI


def _news_api_key():
    return os.environ["NEWS_API_KEY"]


def _openai_client():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def fetch_top_headlines_today():
    resp = requests.get(
        "https://newsapi.org/v2/top-headlines",
        params={"country": "us", "pageSize": 10, "apiKey": _news_api_key()},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("articles", [])[:10]


def fetch_top_articles_for_week(from_date, to_date):
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
        return []
    return data.get("articles", [])[:10]


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

    response = _openai_client().chat.completions.create(
        model="gpt-4o",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def fetch_all():
    """Fetch today + 4 weeks of articles and generate a narrative.

    Returns:
        (narrative_text, today_articles, past_weeks)
        where past_weeks = [(label, articles), ...]
    """
    today = datetime.now().date()

    today_articles = fetch_top_headlines_today()

    past_weeks = []
    for week_num in range(1, 5):
        to_date = today - timedelta(days=(week_num - 1) * 7)
        from_date = today - timedelta(days=week_num * 7)
        label = f"{from_date} to {to_date}"
        articles = fetch_top_articles_for_week(from_date, to_date)
        past_weeks.append((label, articles))

    narrative_text = generate_narrative(today_articles, past_weeks)
    return narrative_text, today_articles, past_weeks
