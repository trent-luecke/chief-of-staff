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
