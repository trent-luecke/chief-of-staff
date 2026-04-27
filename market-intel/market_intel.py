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


# ── Competitor blog fetching ───────────────────────────────────────────────

_COMMON_RSS_PATHS = [
    "",
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


# ── Main pipelines ─────────────────────────────────────────────────────────

def run_daily(dry_run: bool = False):
    """Daily pipeline: fetch → dedup → classify → store → email → git."""
    log.info(f"=== Daily market intel run (dry_run={dry_run}) ===")
    today = datetime.now().strftime("%Y-%m-%d")

    queries = load_queries()
    competitors = load_competitors()
    seen = load_seen_urls()
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    log.info("Fetching Google News RSS...")
    rss_items = fetch_all_rss(queries)

    log.info("Fetching competitor blog feeds...")
    blog_items = fetch_competitor_feeds(competitors)

    all_items = rss_items + blog_items
    log.info(f"Total raw items: {len(all_items)}")

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
