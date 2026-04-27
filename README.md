# NewsNarrative

Build a narrative around the daily Top 10 news and recent events.

## What it does

1. Fetches today's top 10 headlines (via [NewsAPI](https://newsapi.org))
2. Fetches the top 10 most popular articles for each of the past 4 weeks
3. Sends everything to Claude (claude-opus-4-6) to generate a cohesive narrative with trend analysis

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

You need:
- **NewsAPI key** – free at https://newsapi.org/register (100 requests/day on free tier)
- **Anthropic API key** – at https://console.anthropic.com

### 3. Run

```bash
python3 app.py
```

The narrative is printed to stdout and saved as `narrative_YYYY-MM-DD.txt`.

## Output structure

- **Today's Top Stories** – analysis of the day's headlines
- **Weekly Trends** – themes across each of the 4 prior weeks
- **The Big Picture** – synthesis and context

## Notes

- NewsAPI free tier covers articles up to 1 month old, which is sufficient for the 4-week lookback.
- Output files (`narrative_*.txt`) are git-ignored.
