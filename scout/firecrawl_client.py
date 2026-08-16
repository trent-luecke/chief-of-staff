"""Thin Firecrawl v1 REST wrapper (search + scrape). Actions-safe, requests-only."""
import logging
import time

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.firecrawl.dev/v1"
TIMEOUT = 60
MAX_ATTEMPTS = 3


class FirecrawlClient:
    def __init__(self, api_key: str):
        self.api_key = api_key or ""
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def search(self, query: str, limit: int = 8) -> list:
        """Web search returning [{'url','title','markdown'}]; [] on failure."""
        if not self.api_key:
            log.warning("FIRECRAWL_API_KEY not set — search skipped")
            return []
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                resp = requests.post(
                    f"{BASE_URL}/search",
                    headers=self.headers,
                    json={"query": query, "limit": limit,
                          "scrapeOptions": {"formats": ["markdown"]}},
                    timeout=TIMEOUT,
                )
                if resp.status_code == 429 and attempt < MAX_ATTEMPTS:
                    log.warning(f"Firecrawl search 429 for '{query}', retrying (attempt {attempt})")
                    time.sleep(5 * attempt)
                    continue
                break
            resp.raise_for_status()
            data = resp.json().get("data", []) or []
            return [
                {"url": r.get("url", ""),
                 "title": r.get("title", ""),
                 "markdown": r.get("markdown", "")}
                for r in data if r.get("url")
            ]
        except Exception as e:
            log.error(f"Firecrawl search failed for '{query}': {e}")
            return []

    def scrape(self, url: str) -> str | None:
        """Scrape a URL to markdown; None on failure."""
        if not self.api_key:
            log.warning("FIRECRAWL_API_KEY not set — scrape skipped")
            return None
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                resp = requests.post(
                    f"{BASE_URL}/scrape",
                    headers=self.headers,
                    json={"url": url, "formats": ["markdown"]},
                    timeout=TIMEOUT,
                )
                if resp.status_code == 429 and attempt < MAX_ATTEMPTS:
                    log.warning(f"Firecrawl scrape 429 for '{url}', retrying (attempt {attempt})")
                    time.sleep(5 * attempt)
                    continue
                break
            resp.raise_for_status()
            return (resp.json().get("data", {}) or {}).get("markdown")
        except Exception as e:
            log.error(f"Firecrawl scrape failed for '{url}': {e}")
            return None

    def scrape_with_links(self, url: str) -> tuple[str | None, list]:
        """Scrape a URL, returning (markdown, on-page links). One credit — the
        `links` format piggybacks on the same scrape. (None, []) on failure."""
        if not self.api_key:
            log.warning("FIRECRAWL_API_KEY not set — scrape skipped")
            return None, []
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                resp = requests.post(
                    f"{BASE_URL}/scrape",
                    headers=self.headers,
                    json={"url": url, "formats": ["markdown", "links"]},
                    timeout=TIMEOUT,
                )
                if resp.status_code == 429 and attempt < MAX_ATTEMPTS:
                    log.warning(f"Firecrawl scrape 429 for '{url}', retrying (attempt {attempt})")
                    time.sleep(5 * attempt)
                    continue
                break
            resp.raise_for_status()
            data = resp.json().get("data", {}) or {}
            return data.get("markdown"), (data.get("links") or [])
        except Exception as e:
            log.error(f"Firecrawl scrape failed for '{url}': {e}")
            return None, []
