# market-intel

Competitive intelligence scraper for the gym management software market. Monitors Google News and competitor blogs, classifies items via Claude, stores structured data as flat files, and delivers daily/weekly email digests.

## What it does

Fetches the last 7 days of news from Google News RSS using configurable search queries, and probes competitor blog RSS feeds. Deduplicates against a local `seen_urls.json` store so nothing is processed twice. Sends each new item to the Claude API for classification and 1–5 relevance scoring. Items scoring ≥ 3 are written to markdown files in category subfolders and appended to `data/intel-log.csv`. After each run with new items, everything is committed and pushed to GitHub. Sends a daily email summary and compiles/emails a weekly digest on demand.

## Setup

### 1. Create the GitHub repo

```bash
# Create a new empty repo at github.com, then set the remote:
cd /path/to/chief-of-staff/market-intel
git remote add origin git@github.com:YOUR_USERNAME/market-intel.git
git push -u origin main
```

### 2. Install dependencies

```bash
cd chief-of-staff/market-intel
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
cp .env.example .env
# Edit .env and fill in all three values
```

- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `GMAIL_APP_PASSWORD` — see below
- `GITHUB_REMOTE_URL` — SSH URL of your GitHub repo

### 4. Generate a Gmail App Password

1. Go to myaccount.google.com → Security → 2-Step Verification
2. Scroll to **App passwords** and create one for "Mail"
3. Paste the 16-character password as `GMAIL_APP_PASSWORD` in your `.env`

## Running manually

```bash
# Daily run (fetch, classify, store, email, git push)
python market_intel.py

# Daily dry run — writes files locally, skips email and git push
python market_intel.py --dry-run

# Weekly digest (compile last 7 days, email, save to briefs/)
python market_intel.py --weekly

# Weekly digest dry run
python market_intel.py --weekly --dry-run
```

## Adding/removing competitors

Edit `config/competitors.json`. Each entry needs: `name`, `website`, `blog_url` (or null), `changelog_url` (or null), `description`.

## Adding/removing search queries

Edit `config/queries.json`. Each entry is a plain search string. Google News is queried for the last 7 days.

## Cron setup

```cron
# Daily run at 5:00 AM Central (CST = UTC-6)
0 11 * * * cd /path/to/chief-of-staff/market-intel && /usr/bin/python3 market_intel.py >> /tmp/market-intel.log 2>&1

# Weekly digest on Mondays at 6:00 AM Central (CST = UTC-6)
0 12 * * 1 cd /path/to/chief-of-staff/market-intel && /usr/bin/python3 market_intel.py --weekly >> /tmp/market-intel-weekly.log 2>&1
```

> **Note:** Adjust the UTC hour by ±1 in summer when Central switches to CDT (UTC-5).

## Data reference

| Path | Contents |
|------|----------|
| `data/intel-log.csv` | Every stored item, chronological |
| `data/features/` | Feature launch articles |
| `data/acquisitions/` | Acquisition news |
| `data/trends/` | Industry trends, new entrants, partnerships, funding, leadership |
| `data/pricing/` | Pricing change articles |
| `data/competitors/` | Per-competitor timelines (append-style, one file per competitor) |
| `briefs/` | Weekly digest archives |
| `config/seen_urls.json` | Dedup store — all processed URLs |
