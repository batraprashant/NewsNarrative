"""
NewsNarrative - Fetch top 10 daily news and build a narrative using Claude.

Requires:
  NEWS_API_KEY  - from https://newsapi.org (free tier)
  ANTHROPIC_API_KEY - from https://console.anthropic.com
"""

import os
import sys
from datetime import datetime, timedelta

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


def check_env():
    missing = [k for k in ("NEWS_API_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your API keys.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# News fetching
# ---------------------------------------------------------------------------

def fetch_top_headlines_today():
    """Fetch today's top 10 headlines (US, English)."""
    resp = requests.get(
        "https://newsapi.org/v2/top-headlines",
        params={
            "country": "us",
            "pageSize": 10,
            "apiKey": NEWS_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("articles", [])[:10]


def fetch_top_articles_for_week(from_date, to_date):
    """Fetch top 10 most-popular articles for a given date range."""
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": "news",
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "sortBy": "popularity",
            "language": "en",
            "pageSize": 10,
            "apiKey": NEWS_API_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        print(f"  WARNING: NewsAPI error for {from_date} – {to_date}: {data.get('message', 'unknown')}")
        return []
    return data.get("articles", [])[:10]


def fetch_past_4_weeks():
    """Return a list of (label, articles) for each of the past 4 weeks."""
    today = datetime.now().date()
    weeks = []
    for week_num in range(1, 5):
        to_date = today - timedelta(days=(week_num - 1) * 7)
        from_date = today - timedelta(days=week_num * 7)
        label = f"{from_date} to {to_date}"
        print(f"  Fetching week {week_num} ({label}) ...")
        articles = fetch_top_articles_for_week(from_date, to_date)
        print(f"    {len(articles)} articles retrieved")
        weeks.append((label, articles))
    return weeks


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_article_list(articles):
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


# ---------------------------------------------------------------------------
# Narrative generation
# ---------------------------------------------------------------------------

def build_narrative(today_articles, past_weeks):
    """Call Claude to generate a cohesive news narrative."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    today_block = format_article_list(today_articles)

    weekly_blocks = []
    for i, (label, articles) in enumerate(past_weeks, 1):
        block = f"Week {i} ({label}):\n{format_article_list(articles) if articles else '  (no articles retrieved)'}"
        weekly_blocks.append(block)
    weekly_block = "\n\n".join(weekly_blocks)

    prompt = f"""You are an experienced journalist and narrative writer. \
Using only the news headlines and descriptions provided below, craft a compelling, \
well-structured narrative (800–1 200 words) that:

1. Opens with the most significant stories from TODAY
2. Identifies recurring themes and trends across the PAST 4 WEEKS
3. Draws connections between stories where relevant
4. Closes with a "Big Picture" section that contextualises what these stories mean together

Structure your response with these clear headings:
- Today's Top Stories
- Weekly Trends (Week 1 through Week 4)
- The Big Picture

Be analytical, not sensational. Cite source names where helpful.

---

TODAY'S TOP 10 NEWS:
{today_block}

---

PAST 4 WEEKS – TOP 10 PER WEEK:
{weekly_block}
"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    check_env()

    today = datetime.now().date()
    print(f"NewsNarrative – {today}")
    print("=" * 60)

    print("\n[1/3] Fetching today's top 10 headlines ...")
    today_articles = fetch_top_headlines_today()
    print(f"  {len(today_articles)} headlines retrieved")

    print("\n[2/3] Fetching top 10 articles for each of the past 4 weeks ...")
    past_weeks = fetch_past_4_weeks()

    print("\n[3/3] Building narrative with Claude ...")
    narrative = build_narrative(today_articles, past_weeks)

    output_path = f"narrative_{today}.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"NewsNarrative – {today}\n")
        f.write("=" * 60 + "\n\n")
        f.write(narrative)
        f.write("\n")

    print(f"\nNarrative saved to: {output_path}")
    print("\n" + "=" * 60)
    print(narrative)


if __name__ == "__main__":
    main()
