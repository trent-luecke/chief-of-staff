# Market Intel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `chief-of-staff/market-intel/` — a daily/weekly competitive intelligence scraper that monitors gym management software market via Google News RSS and competitor blogs, classifies items with Claude, stores structured flat-file data, commits/pushes to git, and emails daily/weekly digests.

**Architecture:** Single script `market_intel.py` with clearly separated functions. Config in JSON files. Data in flat files (CSV + markdown). No database. Runs via cron or manual invocation with `--dry-run` and `--weekly` CLI flags. Nested under `chief-of-staff/` so all project data lives in one queryable directory.

**Tech Stack:** Python 3.10+, feedparser, requests, anthropic, beautifulsoup4, python-dotenv, smtplib/email (stdlib), subprocess (stdlib for git), argparse/csv/re/json (stdlib)

---

## File Map

```
chief-of-staff/market-intel/
├── config/
│   ├── competitors.json      # 20 competitors with URLs and descriptions
│   ├── queries.json          # 20 Google News RSS search queries
│   └── seen_urls.json        # dedup store, starts as {"seen": []}
├── data/
│   ├── intel-log.csv         # running log, all stored items
│   ├── competitors/          # per-competitor timeline .md files
│   ├── features/             # feature_launch items
│   ├── trends/               # industry_trend, new_entrant, partnership, funding, leadership_change
│   ├── acquisitions/         # acquisition items
│   └── pricing/              # pricing_change items
├── briefs/                   # weekly digest archives as YYYY-MM-DD.md
├── tests/
│   ├── __init__.py
│   └── test_market_intel.py
├── market_intel.py           # all pipeline logic
├── requirements.txt
├── .gitignore
├── .env.example
└── README.md
```

---

## Task 1: Project Scaffold

Creates the directory tree and static config files.

**Files:**
- Create: `chief-of-staff/market-intel/` (full tree)
- Create: `chief-of-staff/market-intel/requirements.txt`
- Create: `chief-of-staff/market-intel/.gitignore`
- Create: `chief-of-staff/market-intel/.env.example`
- Create: `chief-of-staff/market-intel/config/seen_urls.json`
- Create: `chief-of-staff/market-intel/data/intel-log.csv`

- [ ] **Step 1.1: Create directory tree**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
mkdir -p market-intel/{config,data/{competitors,features,trends,acquisitions,pricing},briefs,tests}
touch market-intel/data/competitors/.gitkeep
touch market-intel/data/features/.gitkeep
touch market-intel/data/trends/.gitkeep
touch market-intel/data/acquisitions/.gitkeep
touch market-intel/data/pricing/.gitkeep
touch market-intel/briefs/.gitkeep
touch market-intel/tests/__init__.py
```

- [ ] **Step 1.2: Write requirements.txt**

`chief-of-staff/market-intel/requirements.txt`:
```
feedparser==6.0.11
requests==2.32.3
anthropic==0.49.0
beautifulsoup4==4.12.3
python-dotenv==1.0.1
```

- [ ] **Step 1.3: Write .gitignore**

`chief-of-staff/market-intel/.gitignore`:
```
.env
__pycache__/
*.pyc
*.egg-info/
.venv/
venv/
```

- [ ] **Step 1.4: Write .env.example**

`chief-of-staff/market-intel/.env.example`:
```
ANTHROPIC_API_KEY=your-anthropic-api-key-here
GMAIL_APP_PASSWORD=your-gmail-app-password-here
GITHUB_REMOTE_URL=git@github.com:yourusername/market-intel.git
```

- [ ] **Step 1.5: Write config/seen_urls.json (empty store)**

`chief-of-staff/market-intel/config/seen_urls.json`:
```json
{"seen": []}
```

- [ ] **Step 1.6: Write data/intel-log.csv (header only)**

`chief-of-staff/market-intel/data/intel-log.csv`:
```
date_found,category,competitor,relevance_score,action_flag,summary,title,url,source
```

- [ ] **Step 1.7: Commit scaffold**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/
git commit -m "feat(market-intel): initial project scaffold"
```

---

## Task 2: Config Files

Pre-populate competitors and queries per spec.

**Files:**
- Create: `chief-of-staff/market-intel/config/competitors.json`
- Create: `chief-of-staff/market-intel/config/queries.json`

- [ ] **Step 2.1: Write config/competitors.json**

`chief-of-staff/market-intel/config/competitors.json`:
```json
[
  {
    "name": "PushPress",
    "website": "https://pushpress.com",
    "blog_url": "https://pushpress.com/blog",
    "changelog_url": null,
    "description": "Gym management for class-based gyms, free tier, strong in CrossFit/group training"
  },
  {
    "name": "Mindbody",
    "website": "https://www.mindbodyonline.com",
    "blog_url": "https://www.mindbodyonline.com/business/education",
    "changelog_url": null,
    "description": "Largest platform, strong in boutique/wellness, marketplace model"
  },
  {
    "name": "ABC Glofox",
    "website": "https://www.abcglofox.com",
    "blog_url": "https://www.abcglofox.com/blog",
    "changelog_url": null,
    "description": "Acquired by ABC Fitness, good UX, branded apps, growing fast"
  },
  {
    "name": "ABC Fitness",
    "website": "https://www.abcfitness.com",
    "blog_url": "https://www.abcfitness.com/blog",
    "changelog_url": null,
    "description": "Enterprise/legacy, 40+ years, 9300+ locations"
  },
  {
    "name": "Gymdesk",
    "website": "https://gymdesk.com",
    "blog_url": "https://gymdesk.com/blog",
    "changelog_url": null,
    "description": "Popular with martial arts gyms, strong CRM"
  },
  {
    "name": "Wodify",
    "website": "https://www.wodify.com",
    "blog_url": "https://www.wodify.com/blog",
    "changelog_url": null,
    "description": "CrossFit and performance gym focused"
  },
  {
    "name": "Zen Planner",
    "website": "https://zenplanner.com",
    "blog_url": "https://zenplanner.com/blog",
    "changelog_url": null,
    "description": "Appointment-based gyms, martial arts, key fob access"
  },
  {
    "name": "ClubOS",
    "website": "https://www.club-os.com",
    "blog_url": "https://www.club-os.com/blog",
    "changelog_url": null,
    "description": "Sales CRM for gym chains, recently launched ClubOS ONE as all-in-one"
  },
  {
    "name": "Exercise.com",
    "website": "https://www.exercise.com",
    "blog_url": "https://www.exercise.com/learn",
    "changelog_url": null,
    "description": "Coaching + fitness + retail blend, API-heavy"
  },
  {
    "name": "GymMaster",
    "website": "https://www.gymmaster.com",
    "blog_url": "https://www.gymmaster.com/blog",
    "changelog_url": null,
    "description": "Strong access control, 24/7 gym focus"
  },
  {
    "name": "Wellyx",
    "website": "https://wellyx.com",
    "blog_url": "https://wellyx.com/blog",
    "changelog_url": null,
    "description": "Newer all-in-one, aggressive content marketing"
  },
  {
    "name": "Kilo",
    "website": "https://getkilo.com",
    "blog_url": "https://getkilo.com/blog",
    "changelog_url": null,
    "description": "Gym owners getting more members, retention focused"
  },
  {
    "name": "TeamUp",
    "website": "https://www.goteamup.com",
    "blog_url": "https://www.goteamup.com/resources",
    "changelog_url": null,
    "description": "Group training and fitness studios"
  },
  {
    "name": "Woven",
    "website": "https://startwoven.com",
    "blog_url": "https://startwoven.com/blog",
    "changelog_url": null,
    "description": "Enterprise maintenance/operations layer"
  },
  {
    "name": "Club Ready",
    "website": "https://www.clubready.com",
    "blog_url": "https://www.clubready.com/blog",
    "changelog_url": null,
    "description": "Large gyms, staff management, lead tracking"
  },
  {
    "name": "SHC",
    "website": "https://smarthealthclubs.com",
    "blog_url": "https://smarthealthclubs.com/blog",
    "changelog_url": null,
    "description": "Full-service clubs, family/aquatics/multi-department"
  },
  {
    "name": "1club",
    "website": "https://1club.ai",
    "blog_url": "https://1club.ai/blog",
    "changelog_url": null,
    "description": "AI-first gym management, newer entrant"
  },
  {
    "name": "Virtuagym",
    "website": "https://virtuagym.com",
    "blog_url": "https://virtuagym.com/blog",
    "changelog_url": null,
    "description": "Member engagement beyond workouts, coaching content"
  },
  {
    "name": "Upper Hand",
    "website": "https://www.upperhand.com",
    "blog_url": "https://www.upperhand.com/blog",
    "changelog_url": null,
    "description": "Sports facilities, equipment/event management"
  },
  {
    "name": "EZFacility",
    "website": "https://www.ezfacility.com",
    "blog_url": "https://www.ezfacility.com/blog",
    "changelog_url": null,
    "description": "Schools, sports centers, municipal gyms"
  }
]
```

- [ ] **Step 2.2: Write config/queries.json**

`chief-of-staff/market-intel/config/queries.json`:
```json
[
  "gym management software",
  "member management software fitness",
  "fitness technology software",
  "gym software acquisition",
  "fitness business technology",
  "PushPress gym",
  "Mindbody fitness",
  "ABC Glofox",
  "Wodify gym",
  "Gymdesk",
  "ClubOS fitness",
  "gym membership software",
  "fitness studio software new",
  "gym owner technology",
  "IHRSA fitness industry",
  "health fitness association technology",
  "gym retention software",
  "fitness AI software",
  "gym billing software",
  "boutique fitness technology"
]
```

- [ ] **Step 2.3: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/config/
git commit -m "feat(market-intel): competitor and query configs"
```

---

## Task 3: market_intel.py Skeleton + Pure Utilities + Tests

Creates the main script file with all imports and pure utility functions. These are the only functions that can be unit-tested without network or API calls.

**Files:**
- Create: `chief-of-staff/market-intel/market_intel.py`
- Create: `chief-of-staff/market-intel/tests/test_market_intel.py`

- [ ] **Step 3.1: Write the failing tests first**

`chief-of-staff/market-intel/tests/test_market_intel.py`:
```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from market_intel import slugify, build_rss_url, parse_classification


def test_slugify_basic():
    assert slugify("PushPress Launches AI Feature") == "pushpress-launches-ai-feature"


def test_slugify_special_chars():
    assert slugify("ABC/Glofox: New Update!") == "abcglofox-new-update"


def test_slugify_truncates_long_title():
    long_title = "a" * 200
    result = slugify(long_title)
    assert len(result) <= 80


def test_build_rss_url_contains_domain():
    url = build_rss_url("gym management software")
    assert "news.google.com" in url


def test_build_rss_url_contains_query():
    url = build_rss_url("PushPress gym")
    assert "PushPress" in url or "pushpress" in url.lower()


def test_build_rss_url_contains_recency():
    url = build_rss_url("gym software")
    assert "7d" in url


def test_parse_classification_valid():
    raw = '{"category": "feature_launch", "relevance_score": 4, "competitor": "PushPress", "summary": "Test.", "action_flag": true}'
    result = parse_classification(raw)
    assert result["category"] == "feature_launch"
    assert result["relevance_score"] == 4
    assert result["competitor"] == "PushPress"
    assert result["action_flag"] is True


def test_parse_classification_strips_markdown_fences():
    raw = '```json\n{"category": "noise", "relevance_score": 1, "competitor": null, "summary": "nothing", "action_flag": false}\n```'
    result = parse_classification(raw)
    assert result["category"] == "noise"
    assert result["competitor"] is None


def test_parse_classification_invalid_returns_none():
    result = parse_classification("not json at all")
    assert result is None
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
pip install -r requirements.txt
python -m pytest tests/test_market_intel.py -v
```
Expected: ImportError — `market_intel` module does not exist yet.

- [ ] **Step 3.3: Create market_intel.py with skeleton + utilities**

`chief-of-staff/market-intel/market_intel.py`:
```python
"""
market_intel.py — Competitive intelligence scraper for gym management software market.

Usage:
    python market_intel.py              # daily run
    python market_intel.py --dry-run    # fetch/classify/store; skip email and git push
    python market_intel.py --weekly     # compile and send weekly digest
    python market_intel.py --weekly --dry-run
"""

import argparse
import csv
import json
import logging
import os
import re
import smtplib
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote_plus

import anthropic
import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
BRIEFS_DIR = BASE_DIR / "briefs"

SEEN_URLS_FILE = CONFIG_DIR / "seen_urls.json"
COMPETITORS_FILE = CONFIG_DIR / "competitors.json"
QUERIES_FILE = CONFIG_DIR / "queries.json"
CSV_LOG = DATA_DIR / "intel-log.csv"

CATEGORY_DIRS = {
    "feature_launch": DATA_DIR / "features",
    "acquisition": DATA_DIR / "acquisitions",
    "new_entrant": DATA_DIR / "trends",
    "industry_trend": DATA_DIR / "trends",
    "pricing_change": DATA_DIR / "pricing",
    "partnership": DATA_DIR / "trends",
    "funding": DATA_DIR / "trends",
    "leadership_change": DATA_DIR / "trends",
}

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
GMAIL_USER = "trent@teambuildr.com"
MIN_RELEVANCE_SCORE = 3


# ── Pure utility functions ─────────────────────────────────────────────────

def slugify(title: str) -> str:
    """Convert title to a URL-safe filename slug, max 80 chars."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug[:80]


def build_rss_url(query: str) -> str:
    """Build Google News RSS URL scoped to the last 7 days."""
    q = quote_plus(f"{query} when:7d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def parse_classification(raw: str) -> dict | None:
    """
    Parse Claude's JSON classification response.
    Strips markdown code fences if present. Returns None on failure.
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
```

- [ ] **Step 3.4: Run tests — should pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python -m pytest tests/test_market_intel.py -v
```
Expected: 9 PASSED.

- [ ] **Step 3.5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py chief-of-staff/market-intel/tests/
git commit -m "feat(market-intel): skeleton + utility functions + passing tests"
```

---

## Task 4: Config Loading + Seen-URL Management

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`
- Modify: `chief-of-staff/market-intel/tests/test_market_intel.py`

- [ ] **Step 4.1: Add failing tests**

Append to `tests/test_market_intel.py`:
```python
import json
from pathlib import Path

# Update the import at top of test file to add:
# from market_intel import (
#     slugify, build_rss_url, parse_classification,
#     load_seen_urls, save_seen_urls, load_competitors, load_queries,
# )


def test_load_seen_urls_empty(tmp_path):
    f = tmp_path / "seen_urls.json"
    f.write_text('{"seen": []}')
    result = load_seen_urls(f)
    assert result == set()


def test_load_seen_urls_with_entries(tmp_path):
    f = tmp_path / "seen_urls.json"
    f.write_text('{"seen": ["http://a.com", "http://b.com"]}')
    result = load_seen_urls(f)
    assert "http://a.com" in result
    assert len(result) == 2


def test_save_and_reload_seen_urls(tmp_path):
    f = tmp_path / "seen_urls.json"
    urls = {"http://x.com", "http://y.com"}
    save_seen_urls(urls, f)
    data = json.loads(f.read_text())
    assert set(data["seen"]) == urls


def test_load_competitors_count():
    competitors = load_competitors()
    assert len(competitors) == 20


def test_load_competitors_has_required_fields():
    competitors = load_competitors()
    for c in competitors:
        assert "name" in c
        assert "website" in c
        assert "blog_url" in c
    assert any(c["name"] == "PushPress" for c in competitors)


def test_load_queries_count():
    queries = load_queries()
    assert len(queries) == 20


def test_load_queries_has_key_terms():
    queries = load_queries()
    assert "gym management software" in queries
    assert "fitness AI software" in queries
```

Also update the import block at the top of `tests/test_market_intel.py` to:
```python
from market_intel import (
    slugify, build_rss_url, parse_classification,
    load_seen_urls, save_seen_urls, load_competitors, load_queries,
)
```

- [ ] **Step 4.2: Run tests to confirm failure**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python -m pytest tests/test_market_intel.py -v
```
Expected: ImportError on `load_seen_urls` etc.

- [ ] **Step 4.3: Add config/seen_url functions to market_intel.py**

Append after the pure utility functions:
```python
# ── Config loading ─────────────────────────────────────────────────────────

def load_seen_urls(path: Path = SEEN_URLS_FILE) -> set:
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    return set(data.get("seen", []))


def save_seen_urls(seen: set, path: Path = SEEN_URLS_FILE):
    path.write_text(json.dumps({"seen": sorted(seen)}, indent=2))


def load_competitors() -> list:
    return json.loads(COMPETITORS_FILE.read_text())


def load_queries() -> list:
    return json.loads(QUERIES_FILE.read_text())
```

- [ ] **Step 4.4: Run tests — should pass**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python -m pytest tests/test_market_intel.py -v
```
Expected: 16 PASSED.

- [ ] **Step 4.5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/
git commit -m "feat(market-intel): config loading and seen_url management"
```

---

## Task 5: Google News RSS Fetching + Deduplication

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 5.1: Append RSS fetch functions to market_intel.py**

```python
# ── RSS fetching ───────────────────────────────────────────────────────────

def fetch_rss_items(query: str) -> list[dict]:
    """
    Fetch items from Google News RSS for a single query.
    Returns list of dicts: {title, url, source, description}.
    Returns empty list on any error.
    """
    url = build_rss_url(query)
    try:
        feed = feedparser.parse(url)
        if feed.bozo and feed.bozo_exception:
            log.warning(f"RSS parse warning for '{query}': {feed.bozo_exception}")
        items = []
        for entry in feed.entries:
            source_name = "Google News"
            if hasattr(entry, "source") and isinstance(entry.source, dict):
                source_name = entry.source.get("title", "Google News")
            items.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": source_name,
                "description": entry.get("summary", ""),
            })
        log.info(f"  RSS '{query}': {len(items)} items")
        return items
    except Exception as e:
        log.error(f"RSS fetch failed for '{query}': {e}")
        return []


def fetch_all_rss(queries: list[str], delay: float = 2.0) -> list[dict]:
    """Fetch RSS for all queries with a delay between requests."""
    all_items = []
    for query in queries:
        items = fetch_rss_items(query)
        all_items.extend(items)
        time.sleep(delay)
    return all_items


def deduplicate_items(items: list[dict], seen: set) -> tuple[list[dict], set]:
    """
    Filter items to only those with unseen URLs.
    Returns (new_items, updated_seen_set) — updated_seen includes all new URLs
    regardless of whether they pass the relevance filter later.
    """
    new_items = []
    updated_seen = set(seen)
    for item in items:
        url = item.get("url", "")
        if url and url not in updated_seen:
            new_items.append(item)
            updated_seen.add(url)
    return new_items, updated_seen
```

- [ ] **Step 5.2: Smoke test fetch**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python -c "
from market_intel import fetch_rss_items
items = fetch_rss_items('gym management software')
print(f'Got {len(items)} items')
if items:
    print(f'  Sample: {items[0][\"title\"][:80]}')
"
```
Expected: prints item count. `0` is acceptable if Google News is rate-limiting; non-zero means the RSS pipeline works.

- [ ] **Step 5.3: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): Google News RSS fetching and deduplication"
```

---

## Task 6: Competitor Blog Fetching

The spec calls for competitor blog/changelog pages as a source type in addition to Google News RSS. This task adds a function that tries common RSS paths on each competitor's blog URL before falling back silently.

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 6.1: Append competitor blog fetch function**

```python
# ── Competitor blog fetching ───────────────────────────────────────────────

_COMMON_RSS_PATHS = [
    "",          # try blog_url directly — some are already RSS
    "/feed",
    "/feed.xml",
    "/rss.xml",
    "/rss",
    "/blog/feed",
    "/blog/feed.xml",
    "/blog/rss.xml",
    "/changelog/feed",
    "/atom.xml",
]


def fetch_competitor_feeds(competitors: list[dict], delay: float = 2.0) -> list[dict]:
    """
    Try to fetch RSS from each competitor's blog_url by probing common RSS paths.
    Only takes the 10 most recent entries per competitor.
    Returns list of items in same format as fetch_rss_items.
    """
    all_items = []
    for competitor in competitors:
        blog_url = competitor.get("blog_url")
        if not blog_url:
            continue

        base = blog_url.rstrip("/")
        found = False

        for path in _COMMON_RSS_PATHS:
            probe_url = base + path
            try:
                feed = feedparser.parse(probe_url)
                if feed.entries:
                    for entry in feed.entries[:10]:
                        all_items.append({
                            "title": entry.get("title", ""),
                            "url": entry.get("link", ""),
                            "source": competitor["name"],
                            "description": entry.get("summary", ""),
                        })
                    log.info(f"  Blog feed {competitor['name']}: {min(len(feed.entries), 10)} items")
                    found = True
                    break
            except Exception:
                pass
            time.sleep(0.3)

        if not found:
            log.debug(f"  No RSS found for {competitor['name']} at {blog_url}")

        time.sleep(delay)

    return all_items
```

- [ ] **Step 6.2: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): competitor blog RSS fetching"
```

---

## Task 7: Claude Classification

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 7.1: Append classification function and system prompt**

```python
# ── Claude classification ──────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a competitive intelligence analyst for a gym management and coaching software company called TeamBuildr OS. Your job is to classify news items and score their relevance.

TeamBuildr OS is a gym management and sales/coaching platform for independent, owner-operated, single-location, membership-based gyms (personal training studios, small/large group training, sports performance, adult fitness).

For each item, return a JSON object with these fields:
- "category": one of "feature_launch", "acquisition", "new_entrant", "industry_trend", "pricing_change", "partnership", "funding", "leadership_change", "noise"
- "relevance_score": 1-5 (1 = barely relevant, 5 = directly impacts TeamBuildr's competitive position)
- "competitor": name of the competitor involved, or null if it's an industry-wide item
- "summary": 2-3 sentence summary of what happened and why it matters to TeamBuildr OS
- "action_flag": true if this is something TeamBuildr should respond to or be aware of within the week, false otherwise

Scoring guidance:
- 5 = A direct competitor launched a feature that competes with something TeamBuildr does or plans to do, or a competitor got acquired
- 4 = A competitor made a move that changes the market (new pricing, big partnership, funding round), or a strong industry trend that directly affects TeamBuildr's ICP
- 3 = Relevant competitive activity or industry news worth tracking but no immediate action needed
- 2 = Tangentially related to the gym software market
- 1 = Only loosely connected, mostly noise

Return ONLY valid JSON. No markdown, no explanation, no preamble."""


def classify_article(client: anthropic.Anthropic, item: dict) -> dict | None:
    """
    Classify a single article via Claude.
    Returns parsed classification dict or None on API or parse failure.
    Always sleeps 1 second after the call.
    """
    user_message = (
        f"Title: {item['title']}\n"
        f"Source: {item.get('source', '')}\n"
        f"URL: {item['url']}\n"
        f"Description: {item.get('description', 'No description available')}"
    )
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text
        result = parse_classification(raw)
        if result is None:
            log.warning(f"  Parse failure for: {item['title'][:60]}")
        return result
    except Exception as e:
        log.error(f"  Claude API error for '{item['title'][:60]}': {e}")
        return None
    finally:
        time.sleep(1.0)
```

- [ ] **Step 7.2: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): Claude classification function"
```

---

## Task 8: Data Storage

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 8.1: Append storage functions**

```python
# ── Data storage ───────────────────────────────────────────────────────────

def append_to_csv(record: dict):
    """Append a classified item to intel-log.csv."""
    fieldnames = [
        "date_found", "category", "competitor", "relevance_score",
        "action_flag", "summary", "title", "url", "source",
    ]
    write_header = not CSV_LOG.exists() or CSV_LOG.stat().st_size == 0
    with CSV_LOG.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in fieldnames})


def write_markdown_file(record: dict):
    """
    Write a markdown file to the appropriate category subfolder.
    Skips silently for categories with no mapped directory (e.g. 'noise').
    """
    category = record.get("category", "noise")
    category_dir = CATEGORY_DIRS.get(category)
    if category_dir is None:
        return

    date_str = record["date_found"]
    slug = slugify(record.get("title", "untitled"))
    filepath = category_dir / f"{date_str}-{slug}.md"

    competitor = record.get("competitor") or "N/A"
    action_flag = str(record.get("action_flag", False)).lower()

    content = (
        f"---\n"
        f"date: {date_str}\n"
        f"category: {category}\n"
        f"competitor: {competitor}\n"
        f"relevance_score: {record.get('relevance_score', '')}\n"
        f"action_flag: {action_flag}\n"
        f"source: {record.get('source', '')}\n"
        f"url: {record.get('url', '')}\n"
        f"---\n\n"
        f"{record.get('summary', '')}\n"
    )
    filepath.write_text(content, encoding="utf-8")
    log.info(f"  Wrote {filepath.name}")


def append_competitor_file(record: dict):
    """
    Append item to the per-competitor timeline in data/competitors/.
    No-op if no competitor is named.
    """
    competitor = record.get("competitor")
    if not competitor:
        return

    filepath = DATA_DIR / "competitors" / f"{slugify(competitor)}.md"
    date_str = record["date_found"]
    category = record.get("category", "")
    score = record.get("relevance_score", "")
    url = record.get("url", "")
    summary = record.get("summary", "")

    entry = (
        f"## {date_str} — {category} (score: {score})\n\n"
        f"{summary}\n\n"
        f"Source: {url}\n\n"
        f"---\n"
    )

    if not filepath.exists():
        filepath.write_text(f"# {competitor} — Intelligence Timeline\n\n{entry}", encoding="utf-8")
    else:
        with filepath.open("a", encoding="utf-8") as f:
            f.write(entry)
```

- [ ] **Step 8.2: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): CSV and markdown storage functions"
```

---

## Task 9: Git Integration

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 9.1: Append git functions**

```python
# ── Git integration ────────────────────────────────────────────────────────

def git_run(*args) -> tuple[int, str, str]:
    """Run a git command in BASE_DIR. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", "-C", str(BASE_DIR)] + list(args),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def ensure_git_repo():
    """Initialize repo and set remote if BASE_DIR is not already a git repo."""
    code, _, _ = git_run("rev-parse", "--is-inside-work-tree")
    if code != 0:
        log.info("Initializing git repo in market-intel/")
        git_run("init")
        remote_url = os.getenv("GITHUB_REMOTE_URL", "")
        if remote_url:
            git_run("remote", "add", "origin", remote_url)
            log.info(f"Remote set to: {remote_url}")
        else:
            log.warning("GITHUB_REMOTE_URL not set — git push will be skipped")


def git_commit_push(n_items: int, breakdown: dict):
    """
    Stage all changes, commit with a run-summary message, and push.
    Does nothing if n_items == 0.
    """
    if n_items == 0:
        log.info("No stored items — skipping git commit")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    breakdown_str = ", ".join(
        f"{k}: {v}" for k, v in sorted(breakdown.items()) if v > 0
    )
    message = f"intel run {today}: {n_items} new items ({breakdown_str})"

    git_run("add", ".")
    code, _, stderr = git_run("commit", "-m", message)
    if code != 0:
        log.error(f"git commit failed: {stderr}")
        return
    log.info(f"git commit: {message}")

    remote_url = os.getenv("GITHUB_REMOTE_URL", "")
    if not remote_url:
        log.warning("GITHUB_REMOTE_URL not set — skipping push")
        return

    code, _, stderr = git_run("push", "origin", "main")
    if code != 0:
        log.error(f"git push failed: {stderr}")
    else:
        log.info("git push successful")
```

- [ ] **Step 9.2: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): git init, commit, push integration"
```

---

## Task 10: Email — Daily Summary

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 10.1: Append email functions**

```python
# ── Email ──────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str):
    """Send plain-text email via Gmail SMTP using App Password."""
    app_password = os.getenv("GMAIL_APP_PASSWORD", "")
    if not app_password:
        log.warning("GMAIL_APP_PASSWORD not set — skipping email")
        return
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, app_password)
            server.sendmail(GMAIL_USER, [GMAIL_USER], msg.as_string())
        log.info(f"Email sent: {subject}")
    except Exception as e:
        log.error(f"Email send failed: {e}")


def format_daily_email(records: list[dict], date_str: str) -> tuple[str, str]:
    """
    Format daily summary email.
    Action-flagged items appear first under ACTION NEEDED.
    Remaining items are grouped by category.
    Returns (subject, body).
    """
    n = len(records)
    subject = f"Market Intel — {date_str} ({n} new items)"

    action_items = [r for r in records if r.get("action_flag") in (True, "true", "True")]
    other_items = [r for r in records if r not in action_items]

    lines = []

    if action_items:
        lines.append("ACTION NEEDED")
        lines.append("=" * 40)
        for r in action_items:
            competitor = r.get("competitor") or "Industry"
            lines.append(f"\n[{r.get('category', '').upper().replace('_', ' ')}] {competitor} (score: {r.get('relevance_score')})")
            lines.append(r.get("summary", ""))
            lines.append(r.get("url", ""))
        lines.append("")

    by_category = defaultdict(list)
    for r in other_items:
        by_category[r.get("category", "other")].append(r)

    for category, items in sorted(by_category.items()):
        lines.append(category.upper().replace("_", " "))
        lines.append("-" * 30)
        for r in items:
            competitor = r.get("competitor") or "Industry"
            lines.append(f"\n{competitor} (score: {r.get('relevance_score')})")
            lines.append(r.get("summary", ""))
            lines.append(r.get("url", ""))
        lines.append("")

    return subject, "\n".join(lines)
```

- [ ] **Step 10.2: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): daily email formatting and send"
```

---

## Task 11: Weekly Digest

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 11.1: Append weekly digest functions**

```python
# ── Weekly digest ──────────────────────────────────────────────────────────

def load_recent_csv_records(days: int = 7) -> list[dict]:
    """Read intel-log.csv and return records from the last N days."""
    if not CSV_LOG.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = []
    with CSV_LOG.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date_found", "") >= cutoff:
                records.append(row)
    return records


def format_weekly_digest(records: list[dict], week_start: str) -> tuple[str, str]:
    """
    Format weekly digest email and markdown body.
    Returns (subject, body).
    """
    subject = f"Weekly Market Intel Digest — Week of {week_start}"

    high_signal = [r for r in records if int(r.get("relevance_score") or 0) >= 4]

    by_competitor = defaultdict(list)
    for r in records:
        c = r.get("competitor")
        if c:
            by_competitor[c].append(r)

    trend_items = [
        r for r in records
        if r.get("category") in ("industry_trend", "new_entrant", "partnership")
        and not r.get("competitor")
    ]

    category_counts = Counter(r.get("category") for r in records)
    competitor_counts = Counter(r.get("competitor") for r in records if r.get("competitor"))
    most_active = competitor_counts.most_common(3)

    lines = [
        f"Weekly Market Intel Digest — Week of {week_start}",
        "=" * 50,
        "",
        f"Total items tracked this week: {len(records)}",
        "",
        "TOP SIGNALS (score 4-5)",
        "-" * 30,
    ]

    if high_signal:
        for r in sorted(high_signal, key=lambda x: int(x.get("relevance_score") or 0), reverse=True):
            competitor = r.get("competitor") or "Industry"
            lines.append(f"\n[{r.get('category', '').upper().replace('_', ' ')}] {competitor} (score: {r.get('relevance_score')})")
            lines.append(r.get("summary", ""))
            lines.append(r.get("url", ""))
    else:
        lines.append("No high-signal items this week.")
    lines.append("")

    lines += ["COMPETITOR ACTIVITY", "-" * 30]
    for competitor, items in sorted(by_competitor.items()):
        lines.append(f"\n{competitor} ({len(items)} items)")
        for r in items:
            cat = r.get("category", "").replace("_", " ")
            lines.append(f"  • [{cat}] {r.get('summary', '')[:120]}")
    if not by_competitor:
        lines.append("No competitor-specific activity this week.")
    lines.append("")

    lines += ["INDUSTRY TRENDS", "-" * 30]
    for r in trend_items:
        lines.append(f"\n[{r.get('category', '').upper().replace('_', ' ')}] {r.get('title', '')}")
        lines.append(r.get("summary", ""))
    if not trend_items:
        lines.append("No pure industry trends this week.")
    lines.append("")

    lines += ["STATS", "-" * 30]
    lines.append(f"Total items: {len(records)}")
    for cat, count in sorted(category_counts.items()):
        if cat:
            lines.append(f"  {cat}: {count}")
    if most_active:
        lines.append("Most active competitors:")
        for name, count in most_active:
            if name:
                lines.append(f"  {name}: {count} items")
    lines.append("")

    return subject, "\n".join(lines)


def save_weekly_brief(body: str, date_str: str):
    """Save weekly digest body to briefs/YYYY-MM-DD.md."""
    BRIEFS_DIR.mkdir(exist_ok=True)
    filepath = BRIEFS_DIR / f"{date_str}.md"
    filepath.write_text(body, encoding="utf-8")
    log.info(f"Saved weekly brief: briefs/{date_str}.md")
```

- [ ] **Step 11.2: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): weekly digest compile, format, save"
```

---

## Task 12: Main Pipeline + CLI Entry Point

Wires everything together. Daily pipeline: fetch (Google News + competitor blogs) → dedup → classify → store → email → git. Weekly pipeline reads CSV and compiles digest.

**Files:**
- Modify: `chief-of-staff/market-intel/market_intel.py`

- [ ] **Step 12.1: Append main pipelines and CLI**

```python
# ── Main pipelines ─────────────────────────────────────────────────────────

def run_daily(dry_run: bool = False):
    """Daily pipeline: fetch → dedup → classify → store → email → git."""
    log.info(f"=== Daily market intel run (dry_run={dry_run}) ===")
    today = datetime.now().strftime("%Y-%m-%d")

    queries = load_queries()
    competitors = load_competitors()
    seen = load_seen_urls()
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Fetch from all sources
    log.info("Fetching Google News RSS...")
    rss_items = fetch_all_rss(queries)

    log.info("Fetching competitor blog feeds...")
    blog_items = fetch_competitor_feeds(competitors)

    all_items = rss_items + blog_items
    log.info(f"Total raw items: {len(all_items)}")

    # Deduplicate
    new_items, updated_seen = deduplicate_items(all_items, seen)
    log.info(f"New items after dedup: {len(new_items)}")

    stored_records = []
    breakdown: dict = {}

    log.info("Classifying with Claude...")
    for item in new_items:
        classification = classify_article(client, item)
        if classification is None:
            continue

        score = int(classification.get("relevance_score") or 0)
        category = classification.get("category", "noise")

        if score < MIN_RELEVANCE_SCORE or category == "noise":
            log.info(f"  Skip (score={score}, cat={category}): {item['title'][:50]}")
            continue

        record = {
            "date_found": today,
            "category": category,
            "competitor": classification.get("competitor"),
            "relevance_score": score,
            "action_flag": classification.get("action_flag", False),
            "summary": classification.get("summary", ""),
            "title": item["title"],
            "url": item["url"],
            "source": item.get("source", ""),
        }

        append_to_csv(record)
        write_markdown_file(record)
        append_competitor_file(record)

        stored_records.append(record)
        breakdown[category] = breakdown.get(category, 0) + 1

    # Always persist seen URLs so we don't reprocess next run
    save_seen_urls(updated_seen)
    log.info(f"Stored {len(stored_records)} records. Breakdown: {breakdown}")

    if stored_records and not dry_run:
        subject, body = format_daily_email(stored_records, today)
        send_email(subject, body)

    if not dry_run:
        git_commit_push(len(stored_records), breakdown)
    else:
        log.info("[dry-run] Skipping email and git push")

    log.info("=== Daily run complete ===")
    return stored_records


def run_weekly(dry_run: bool = False):
    """Weekly pipeline: read last 7 days of CSV → format digest → email → save → git."""
    log.info(f"=== Weekly digest run (dry_run={dry_run}) ===")
    today = datetime.now().strftime("%Y-%m-%d")
    week_start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")

    records = load_recent_csv_records(days=7)
    log.info(f"Found {len(records)} records from last 7 days")

    subject, body = format_weekly_digest(records, week_start)
    save_weekly_brief(body, today)

    if not dry_run:
        send_email(subject, body)
        git_commit_push(1, {"weekly_digest": 1})
    else:
        log.info("[dry-run] Skipping email and git push")

    log.info("=== Weekly digest complete ===")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Market Intel — gym software competitive intelligence scraper"
    )
    parser.add_argument("--weekly", action="store_true", help="Run weekly digest instead of daily run")
    parser.add_argument("--dry-run", action="store_true", help="Skip email and git push; write files locally")
    args = parser.parse_args()

    ensure_git_repo()

    if args.weekly:
        run_weekly(dry_run=args.dry_run)
    else:
        run_daily(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 12.2: Run full test suite**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python -m pytest tests/ -v
```
Expected: All 16 tests PASS.

- [ ] **Step 12.3: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/market_intel.py
git commit -m "feat(market-intel): main pipeline and CLI entry point"
```

---

## Task 13: README

**Files:**
- Create: `chief-of-staff/market-intel/README.md`

- [ ] **Step 13.1: Write README.md**

`chief-of-staff/market-intel/README.md`:
```markdown
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

- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com)
- `GMAIL_APP_PASSWORD` — see below
- `GITHUB_REMOTE_URL` — SSH URL of your GitHub repo

### 4. Generate a Gmail App Password

1. Go to [myaccount.google.com](https://myaccount.google.com) → Security → 2-Step Verification
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
```

- [ ] **Step 13.2: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/README.md
git commit -m "docs(market-intel): README with setup, cron, and data reference"
```

---

## Task 14: Dry Run Validation

Execute an end-to-end dry run with real API calls to validate the full pipeline.

**Files:** No changes — validation only.

- [ ] **Step 14.1: Install dependencies**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
pip install -r requirements.txt
```
Expected: All packages install cleanly.

- [ ] **Step 14.2: Set up .env**

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and GMAIL_APP_PASSWORD
# Leave GITHUB_REMOTE_URL blank for now
```

- [ ] **Step 14.3: Smoke test RSS fetching with 3 queries**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python -c "
from market_intel import fetch_rss_items
for q in ['gym management software', 'PushPress gym', 'ABC Glofox']:
    items = fetch_rss_items(q)
    print(f'{q}: {len(items)} items')
    if items:
        print(f'  Sample: {items[0][\"title\"][:70]}')
"
```
Expected: 3 lines with item counts. Non-zero means the RSS path works end-to-end.

- [ ] **Step 14.4: Run full dry run**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python market_intel.py --dry-run
```
Expected log output (in order):
1. `=== Daily market intel run (dry_run=True) ===`
2. `Fetching Google News RSS...` lines with per-query item counts
3. `Fetching competitor blog feeds...` lines
4. `Total raw items: N`
5. `New items after dedup: N`
6. `Classifying with Claude...`
7. Per-item skip/store log lines
8. `Stored N records.`
9. `[dry-run] Skipping email and git push`
10. `=== Daily run complete ===`

No exceptions or tracebacks.

- [ ] **Step 14.5: Inspect outputs**

```bash
# Check CSV has at least one data row
head -5 /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel/data/intel-log.csv

# Check markdown files were written
ls /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel/data/features/
ls /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel/data/trends/

# Check competitor files
ls /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel/data/competitors/

# Spot-check a markdown file
cat $(ls /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel/data/features/*.md 2>/dev/null | head -1)
```
Expected: CSV has header + ≥ 1 data row. At least some markdown files exist with valid frontmatter.

- [ ] **Step 14.6: Run final test suite**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff/market-intel
python -m pytest tests/ -v
```
Expected: All 16 tests PASS.

- [ ] **Step 14.7: Commit dry run outputs**

```bash
cd /Users/trentluecke/dev/Claude-Projects
git add chief-of-staff/market-intel/
git commit -m "feat(market-intel): complete — passing tests and dry run validated"
```
