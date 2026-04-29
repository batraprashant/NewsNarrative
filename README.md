# NewsNarrative

A web app that fetches the daily top 10 news and the top 10 stories from each of the past 4 weeks, stores them in a database, and presents a GPT-5.5-generated narrative through a clean web front-end.

## What it does

1. Fetches today's top 10 headlines (via [NewsAPI](https://newsapi.org))
2. Fetches the top 10 most popular articles for each of the past 4 weeks
3. Stores everything in a local SQLite database
4. Generates a Markdown narrative with OpenAI GPT-4o
5. Presents the narrative + article cards in a responsive web UI
6. Auto-fetches daily at 08:00 via a background scheduler

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
- **OpenAI API key** – at https://platform.openai.com/api-keys
- **SECRET_KEY** – any random string for Flask session signing

### 3. Run

```bash
python3 app.py
```

Open http://localhost:5000 in your browser, then click **Fetch Now** to pull the first batch of news.

## Project structure

```
app.py          Flask app, routes, scheduler
models.py       SQLAlchemy models (Narrative, Article)
fetcher.py      NewsAPI fetching + OpenAI narrative generation
templates/      Jinja2 HTML templates (Bootstrap 5)
static/         CSS
```

## Narrative structure

- **Today's Top Stories** – analysis of today's headlines
- **Weekly Trends** – themes across each of the 4 prior weeks
- **The Big Picture** – synthesis and context

## Notes

- The SQLite database (`newsnarrative.db`) is git-ignored.
- NewsAPI free tier covers articles up to 1 month old, sufficient for the 4-week lookback.
- The scheduler runs in the background; fetches can also be triggered manually via the **Fetch Now** button.
