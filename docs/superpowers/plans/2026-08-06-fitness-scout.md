# Fitness Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `chief-of-staff/scout/` — a fully autonomous module that emails Trent two deep, OS-grounded teardowns of emerging gym-management / online-coaching platforms every Friday 7am CDT.

**Architecture:** A self-contained Python module modeled on `market-intel/` (own `data/`, `config/`, `requirements.txt`, GitHub Actions cron; no `lib/` imports, no touching `main.py`). A hybrid discovery layer (Firecrawl web search + best-effort Meta Ad Library scrape) stocks a `candidates.jsonl` backlog decoupled from delivery; each Friday the orchestrator selects the 2 best uncovered candidates, scrapes and analyzes them with Claude against a hand-curated OS grounding profile, and emails the result. State persists via git commit-back.

**Tech Stack:** Python 3.11, `anthropic` SDK, Firecrawl REST API (via `requests`), `beautifulsoup4`, `smtplib`, pytest.

## Global Constraints

- **Python 3.11** (matches `market-intel` workflow `setup-python`).
- **Self-contained module.** No imports from repo-root `lib/`. Mirror `market-intel/market_intel.py` patterns (standalone `smtplib` email, direct `anthropic` SDK, local git helpers). Never import or modify `main.py`, the brief, or the Telegram bot.
- **Model strings:** cheap/high-volume scoring → `claude-haiku-4-5-20251001`; grounded teardown analysis → `claude-opus-4-8`. Anthropic call shape mirrors `market_intel.classify_article`: `client.messages.create(model=..., max_tokens=..., system=..., messages=[{"role":"user","content":...}])`, read `response.content[0].text`.
- **Grounding-lookup rule (non-negotiable):** the OS grounding profile (`scout/os_grounding.md`) is injected verbatim into the teardown prompt. The model assigns feature-taxonomy tags (✅/🎯/🚫/➖/✨/❓) and JTBD verdicts (📣/🎯/➖) ONLY by looking up against that text; unmapped → ❓/flag, never invent OS strategy.
- **Recipient / sender:** `trent@teambuildr.com` (both From and To), via Gmail SMTP SSL on port 465 using `GMAIL_APP_PASSWORD`. Missing password → log warning and skip send (never crash).
- **Resilience:** every network/Claude call is wrapped so a single failure (a bad scrape, a Meta block, one candidate erroring) never kills the weekly email. Discovery failures never block delivery — the email draws from the existing backlog.
- **Never a silent skip:** if fewer than 2 uncovered candidates exist, send what's available (1, or a short "no new platforms this week" note); never send nothing on a Friday.
- **Env vars / secrets:** `ANTHROPIC_API_KEY`, `GMAIL_APP_PASSWORD`, `FIRECRAWL_API_KEY`.
- **Spec:** `docs/superpowers/specs/2026-08-06-fitness-scout-design.md`.

---

## File Structure

```
scout/
  __init__.py
  config.py             # load config json, grounding md, resolve data paths
  backlog.py            # candidates.jsonl / covered.jsonl data layer (load/save/dedup/select)
  firecrawl_client.py   # thin requests wrapper: search() + scrape()
  discovery.py          # search seeds -> score -> backlog; meta ad library booster
  teardown.py           # scrape + content-hash + grounded Claude analysis -> teardown dict
  emailer.py            # format_email (HTML) + send_email (smtplib)
  scout.py              # orchestrator + CLI (default run / --dry-run / --discover-only / --seed / --covered)
  os_grounding.md       # hand-curated OS profile (TRACKED source of truth)
  requirements.txt
  config/
    scout_config.json   # search seeds, exclude list, thresholds, recipient
  data/                 # machine-written state, git-committed each run
    .gitkeep
    candidates.jsonl    # (created at runtime)
    covered.jsonl       # (created at runtime)
    briefs/             # (created at runtime) rendered-email archive
  tests/
    __init__.py
    test_config.py
    test_backlog.py
    test_firecrawl_client.py
    test_discovery.py
    test_teardown.py
    test_emailer.py
    test_scout.py
.github/workflows/scout.yml
```

**Candidate record** (one JSON object per line in `candidates.jsonl`; `covered.jsonl` mirrors covered records):
```json
{
  "domain": "coachway.io", "name": "Coachway", "url": "https://coachway.io/",
  "bucket": "B", "source": "websearch", "discovered_at": "2026-08-06",
  "novelty_score": 0.7, "icp_relevance": 0.6,
  "covered": false, "covered_at": null, "content_hash": null, "seed": false
}
```

---

## Task 1: Scaffold — module, config, grounding doc, config loader

**Files:**
- Create: `scout/__init__.py`, `scout/requirements.txt`, `scout/config/scout_config.json`, `scout/os_grounding.md`, `scout/data/.gitkeep`, `scout/config.py`, `scout/tests/__init__.py`
- Test: `scout/tests/test_config.py`
- Modify: `.gitignore` (add `scout/*.log`)

**Interfaces:**
- Produces: `config.load_config() -> dict`, `config.load_grounding() -> str`, module-level path constants `BASE_DIR, DATA_DIR, CONFIG_DIR, CANDIDATES_FILE, COVERED_FILE, BRIEFS_DIR, GROUNDING_FILE`.

- [ ] **Step 1: Create the directory skeleton and empty package files**

```bash
mkdir -p scout/config scout/data/briefs scout/tests
touch scout/__init__.py scout/tests/__init__.py scout/data/.gitkeep
```

- [ ] **Step 2: Write `scout/requirements.txt`**

```
anthropic==0.49.0
requests==2.32.3
beautifulsoup4==4.12.3
python-dotenv==1.0.1
```

- [ ] **Step 3: Write `scout/config/scout_config.json`**

```json
{
  "recipient": "trent@teambuildr.com",
  "teardowns_per_week": 2,
  "search_limit": 8,
  "search_queries": [
    "new gym management software 2025 2026",
    "best alternative to Trainerize for online coaches 2025",
    "AI personal trainer coaching platform startup",
    "indie gym management software built by a gym owner",
    "boutique studio management software new",
    "site:producthunt.com gym OR coaching OR fitness software",
    "site:reddit.com gym management software recommendation"
  ],
  "meta_ad_library_queries": [
    "gym management software",
    "online coaching platform for personal trainers"
  ],
  "exclude_domains": [
    "mindbody", "pushpress", "zenplanner", "trainerize", "truecoach",
    "teambuildr", "glofox", "wodify", "marianatek", "abcfitness",
    "everfit", "ptdistinction", "mypthub", "exercise.com", "kilo",
    "gymlaunch", "virtuagym", "hevy", "zenoti"
  ]
}
```

Note: `zenoti` is excluded from discovery (it's the $1.5B incumbent used only as an idea-source example), so autonomous discovery skews to true upstarts. It can still be added manually via `--seed`.

- [ ] **Step 4: Write `scout/os_grounding.md`**

Copy the grounding profile verbatim from the spec's "The OS Grounding Profile" section (strengths, gaps, market fit, OS JTBD, feature taxonomy, JTBD verdicts, and the category fingerprint). This file is the hand-curated source of truth; use the exact content committed in `docs/superpowers/specs/2026-08-06-fitness-scout-design.md`.

- [ ] **Step 5: Write the failing test `scout/tests/test_config.py`**

```python
from scout import config


def test_load_config_has_required_keys():
    cfg = config.load_config()
    for key in ("recipient", "teardowns_per_week", "search_queries", "exclude_domains"):
        assert key in cfg
    assert cfg["recipient"] == "trent@teambuildr.com"
    assert cfg["teardowns_per_week"] == 2


def test_load_grounding_is_nonempty_and_mentions_taxonomy():
    text = config.load_grounding()
    assert len(text) > 500
    # grounding must carry the taxonomy the teardown prompt depends on
    assert "Real gap" in text
    assert "JTBD" in text
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python -m pytest scout/tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scout.config'` (or ImportError).

- [ ] **Step 7: Write `scout/config.py`**

```python
"""Config + path resolution for the Fitness Scout module."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
BRIEFS_DIR = DATA_DIR / "briefs"
CANDIDATES_FILE = DATA_DIR / "candidates.jsonl"
COVERED_FILE = DATA_DIR / "covered.jsonl"
GROUNDING_FILE = BASE_DIR / "os_grounding.md"
CONFIG_FILE = CONFIG_DIR / "scout_config.json"


def load_config() -> dict:
    """Load scout_config.json."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_grounding() -> str:
    """Load the hand-curated OS grounding profile as raw text."""
    return GROUNDING_FILE.read_text(encoding="utf-8")
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `python -m pytest scout/tests/test_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 9: Add `scout/*.log` to `.gitignore`**

Append to `.gitignore` (after the market-intel block):
```
# Fitness Scout — logs are noise; scout/data/ IS tracked for state persistence
scout/*.log
```

- [ ] **Step 10: Commit**

```bash
git add scout/ .gitignore
git commit -m "feat(scout): scaffold module, config, grounding profile, config loader"
```

---

## Task 2: Backlog data layer (`backlog.py`)

**Files:**
- Create: `scout/backlog.py`
- Test: `scout/tests/test_backlog.py`

**Interfaces:**
- Consumes: path constants from `scout.config`.
- Produces:
  - `new_candidate(domain, name, url, bucket, source, discovered_at, seed=False) -> dict`
  - `load(path) -> list[dict]` / `save(records, path) -> None` (JSONL)
  - `has_domain(records, domain) -> bool`
  - `add(records, cand) -> bool` (dedup by domain; returns True if added)
  - `mark_covered(records, domain, content_hash, covered_at) -> None`
  - `select_uncovered(records, n) -> list[dict]` (seeds first oldest-first, then by `novelty_score + icp_relevance` desc)

- [ ] **Step 1: Write the failing test `scout/tests/test_backlog.py`**

```python
from scout import backlog


def _cand(domain, seed=False, nov=0.5, icp=0.5, covered=False):
    c = backlog.new_candidate(domain, domain.split(".")[0], f"https://{domain}/",
                              "A", "websearch", "2026-08-06", seed=seed)
    c["novelty_score"] = nov
    c["icp_relevance"] = icp
    c["covered"] = covered
    return c


def test_new_candidate_shape():
    c = backlog.new_candidate("xoda.com", "Xoda", "https://xoda.com/", "A", "seed", "2026-08-06", seed=True)
    assert c["domain"] == "xoda.com"
    assert c["seed"] is True
    assert c["covered"] is False
    assert c["content_hash"] is None


def test_add_dedups_by_domain():
    records = []
    assert backlog.add(records, _cand("a.com")) is True
    assert backlog.add(records, _cand("a.com")) is False
    assert len(records) == 1


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "candidates.jsonl"
    records = [_cand("a.com"), _cand("b.com")]
    backlog.save(records, p)
    loaded = backlog.load(p)
    assert [r["domain"] for r in loaded] == ["a.com", "b.com"]


def test_load_missing_file_returns_empty(tmp_path):
    assert backlog.load(tmp_path / "nope.jsonl") == []


def test_mark_covered_sets_fields():
    records = [_cand("a.com")]
    backlog.mark_covered(records, "a.com", "hash123", "2026-08-07")
    assert records[0]["covered"] is True
    assert records[0]["content_hash"] == "hash123"
    assert records[0]["covered_at"] == "2026-08-07"


def test_select_prioritizes_seeds_then_score():
    records = [
        _cand("low.com", nov=0.1, icp=0.1),
        _cand("high.com", nov=0.9, icp=0.9),
        _cand("seed.com", seed=True, nov=0.0, icp=0.0),
    ]
    picked = backlog.select_uncovered(records, 2)
    assert picked[0]["domain"] == "seed.com"      # seed first despite low score
    assert picked[1]["domain"] == "high.com"      # then best score


def test_select_skips_covered():
    records = [_cand("done.com", covered=True), _cand("open.com")]
    picked = backlog.select_uncovered(records, 2)
    assert [r["domain"] for r in picked] == ["open.com"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scout/tests/test_backlog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scout.backlog'`.

- [ ] **Step 3: Write `scout/backlog.py`**

```python
"""Candidate backlog data layer: JSONL load/save, dedup, selection."""
import json
from pathlib import Path


def new_candidate(domain, name, url, bucket, source, discovered_at, seed=False) -> dict:
    return {
        "domain": domain,
        "name": name,
        "url": url,
        "bucket": bucket,
        "source": source,
        "discovered_at": discovered_at,
        "novelty_score": 0.0,
        "icp_relevance": 0.0,
        "covered": False,
        "covered_at": None,
        "content_hash": None,
        "seed": seed,
    }


def load(path: Path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save(records: list, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def has_domain(records: list, domain: str) -> bool:
    return any(r["domain"] == domain for r in records)


def add(records: list, cand: dict) -> bool:
    if has_domain(records, cand["domain"]):
        return False
    records.append(cand)
    return True


def mark_covered(records: list, domain: str, content_hash: str, covered_at: str) -> None:
    for r in records:
        if r["domain"] == domain:
            r["covered"] = True
            r["content_hash"] = content_hash
            r["covered_at"] = covered_at


def select_uncovered(records: list, n: int) -> list:
    uncovered = [r for r in records if not r.get("covered")]
    seeds = [r for r in uncovered if r.get("seed")]
    seeds.sort(key=lambda r: r.get("discovered_at", ""))          # oldest seed first
    rest = [r for r in uncovered if not r.get("seed")]
    rest.sort(key=lambda r: r.get("novelty_score", 0) + r.get("icp_relevance", 0), reverse=True)
    return (seeds + rest)[:n]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest scout/tests/test_backlog.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add scout/backlog.py scout/tests/test_backlog.py
git commit -m "feat(scout): candidate backlog data layer with seed-first selection"
```

---

## Task 3: Firecrawl client (`firecrawl_client.py`)

**Files:**
- Create: `scout/firecrawl_client.py`
- Test: `scout/tests/test_firecrawl_client.py`

**Interfaces:**
- Produces: `class FirecrawlClient(api_key: str)` with:
  - `search(query: str, limit: int = 8) -> list[dict]` — each result `{"url": str, "title": str, "markdown": str}`; `[]` on any failure.
  - `scrape(url: str) -> str | None` — page markdown, or `None` on failure.
- Both methods POST to Firecrawl v1 REST (`https://api.firecrawl.dev/v1/search`, `/v1/scrape`) with `Authorization: Bearer <key>`, wrapped in try/except with a timeout.

- [ ] **Step 1: Write the failing test `scout/tests/test_firecrawl_client.py`**

```python
from scout.firecrawl_client import FirecrawlClient


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_search_parses_results(monkeypatch):
    payload = {"data": [
        {"url": "https://a.com", "title": "A", "markdown": "# A"},
        {"url": "https://b.com", "title": "B", "markdown": "# B"},
    ]}
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(200, payload))
    fc = FirecrawlClient("key")
    results = fc.search("gym software", limit=2)
    assert [r["url"] for r in results] == ["https://a.com", "https://b.com"]


def test_search_returns_empty_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr("scout.firecrawl_client.requests.post", boom)
    fc = FirecrawlClient("key")
    assert fc.search("x") == []


def test_scrape_returns_markdown(monkeypatch):
    payload = {"data": {"markdown": "# Hello", "metadata": {}}}
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(200, payload))
    fc = FirecrawlClient("key")
    assert fc.scrape("https://a.com") == "# Hello"


def test_scrape_returns_none_on_error(monkeypatch):
    monkeypatch.setattr("scout.firecrawl_client.requests.post",
                        lambda *a, **k: _FakeResp(500, {}))
    fc = FirecrawlClient("key")
    assert fc.scrape("https://a.com") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scout/tests/test_firecrawl_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scout.firecrawl_client'`.

- [ ] **Step 3: Write `scout/firecrawl_client.py`**

```python
"""Thin Firecrawl v1 REST wrapper (search + scrape). Actions-safe, requests-only."""
import logging

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.firecrawl.dev/v1"
TIMEOUT = 60


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
            resp = requests.post(
                f"{BASE_URL}/search",
                headers=self.headers,
                json={"query": query, "limit": limit,
                      "scrapeOptions": {"formats": ["markdown"]}},
                timeout=TIMEOUT,
            )
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
            resp = requests.post(
                f"{BASE_URL}/scrape",
                headers=self.headers,
                json={"url": url, "formats": ["markdown"]},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return (resp.json().get("data", {}) or {}).get("markdown")
        except Exception as e:
            log.error(f"Firecrawl scrape failed for '{url}': {e}")
            return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest scout/tests/test_firecrawl_client.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add scout/firecrawl_client.py scout/tests/test_firecrawl_client.py
git commit -m "feat(scout): Firecrawl REST client for search + scrape (graceful failure)"
```

---

## Task 4: Discovery (`discovery.py`)

**Files:**
- Create: `scout/discovery.py`
- Test: `scout/tests/test_discovery.py`

**Interfaces:**
- Consumes: `backlog.new_candidate/add`, `FirecrawlClient.search/scrape`, an `anthropic.Anthropic` client, grounding text.
- Produces:
  - `extract_domain(url: str) -> str` (lowercased registrable host, `www.` stripped)
  - `is_excluded(domain: str, exclude: list[str]) -> bool` (substring match)
  - `score_candidate(client, name, url, snippet, grounding_text) -> tuple[float, float]` (novelty, icp in 0..1; `(0.0, 0.0)` on failure)
  - `run_discovery(cfg, records, fc, client, grounding_text, today: str) -> int` (candidates added)
  - `meta_ad_library_boost(cfg, records, fc, today: str) -> int` (best-effort; 0 on any failure)

- [ ] **Step 1: Write the failing test `scout/tests/test_discovery.py`**

```python
from scout import discovery, backlog


def test_extract_domain_strips_www_and_path():
    assert discovery.extract_domain("https://www.Coachway.io/pricing?x=1") == "coachway.io"
    assert discovery.extract_domain("http://xoda.com") == "xoda.com"


def test_is_excluded_substring():
    ex = ["mindbody", "trainerize"]
    assert discovery.is_excluded("app.mindbody.com", ex) is True
    assert discovery.is_excluded("coachway.io", ex) is False


class _FakeFC:
    def __init__(self, results):
        self._results = results
    def search(self, query, limit=8):
        return self._results
    def scrape(self, url):
        return None


def _fake_client_scoring(novelty, icp):
    class _Resp:
        content = [type("C", (), {"text": f'{{"novelty": {novelty}, "icp": {icp}}}'})()]
    class _Msgs:
        def create(self, **k): return _Resp()
    class _Client:
        messages = _Msgs()
    return _Client()


def test_run_discovery_adds_new_scored_filtered(monkeypatch):
    fc = _FakeFC([
        {"url": "https://coachway.io/", "title": "Coachway", "markdown": "online coaching"},
        {"url": "https://mindbody.com/", "title": "Mindbody", "markdown": "big incumbent"},
        {"url": "https://coachway.io/pricing", "title": "dup", "markdown": "dup"},
    ])
    client = _fake_client_scoring(0.8, 0.7)
    cfg = {"search_queries": ["q"], "search_limit": 8, "exclude_domains": ["mindbody"]}
    records = []
    added = discovery.run_discovery(cfg, records, fc, client, "GROUNDING", "2026-08-06")
    assert added == 1                                  # mindbody excluded, dup collapsed
    assert records[0]["domain"] == "coachway.io"
    assert records[0]["novelty_score"] == 0.8
    assert records[0]["icp_relevance"] == 0.7


def test_run_discovery_skips_already_known(monkeypatch):
    fc = _FakeFC([{"url": "https://coachway.io/", "title": "C", "markdown": "x"}])
    client = _fake_client_scoring(0.5, 0.5)
    cfg = {"search_queries": ["q"], "search_limit": 8, "exclude_domains": []}
    records = [backlog.new_candidate("coachway.io", "C", "https://coachway.io/", "B", "seed", "2026-08-01")]
    added = discovery.run_discovery(cfg, records, fc, client, "G", "2026-08-06")
    assert added == 0


def test_score_candidate_handles_bad_json():
    class _Resp:
        content = [type("C", (), {"text": "not json"})()]
    class _Msgs:
        def create(self, **k): return _Resp()
    class _Client:
        messages = _Msgs()
    assert discovery.score_candidate(_Client(), "n", "u", "s", "G") == (0.0, 0.0)


def test_meta_boost_never_raises(monkeypatch):
    class _BoomFC:
        def scrape(self, url): raise RuntimeError("blocked")
        def search(self, *a, **k): raise RuntimeError("blocked")
    cfg = {"meta_ad_library_queries": ["gym software"]}
    # must swallow and return 0, never propagate
    assert discovery.meta_ad_library_boost(cfg, [], _BoomFC(), "2026-08-06") == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scout/tests/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scout.discovery'`.

- [ ] **Step 3: Write `scout/discovery.py`**

```python
"""Discovery: web-search seeds + best-effort Meta Ad Library -> scored backlog."""
import json
import logging
import re
from urllib.parse import urlparse

from . import backlog

log = logging.getLogger(__name__)

SCORE_MODEL = "claude-haiku-4-5-20251001"

SCORE_SYSTEM = (
    "You score a fitness-business software platform as a candidate for a weekly "
    "competitor teardown aimed at an S&C / gym-management product (TeamBuildr OS). "
    "Return ONLY a JSON object: {\"novelty\": <0-1>, \"icp\": <0-1>}. "
    "novelty = how unusual/distinctive its approach is vs. the boilerplate CRM category. "
    "icp = relevance to gym/studio management or online fitness coaching (1=core, 0=unrelated)."
)


def extract_domain(url: str) -> str:
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_excluded(domain: str, exclude: list) -> bool:
    return any(term in domain for term in exclude)


def _guess_bucket(text: str) -> str:
    t = (text or "").lower()
    online = any(w in t for w in ("online coach", "coaching platform", "client app", "programming for coaches"))
    return "B" if online else "A"


def score_candidate(client, name, url, snippet, grounding_text) -> tuple:
    user = (
        f"Platform: {name}\nURL: {url}\n"
        f"Snippet: {(snippet or '')[:1500]}\n\n"
        f"Grounding (our product context):\n{grounding_text[:2000]}"
    )
    try:
        resp = client.messages.create(
            model=SCORE_MODEL,
            max_tokens=128,
            system=SCORE_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
        return float(data.get("novelty", 0.0)), float(data.get("icp", 0.0))
    except Exception as e:
        log.warning(f"score_candidate failed for {name}: {e}")
        return (0.0, 0.0)


def run_discovery(cfg, records, fc, client, grounding_text, today) -> int:
    exclude = cfg.get("exclude_domains", [])
    limit = cfg.get("search_limit", 8)
    added = 0
    for query in cfg.get("search_queries", []):
        for r in fc.search(query, limit=limit):
            domain = extract_domain(r["url"])
            if not domain or is_excluded(domain, exclude) or backlog.has_domain(records, domain):
                continue
            name = (r.get("title") or domain).split("|")[0].split("-")[0].strip()
            nov, icp = score_candidate(client, name, r["url"], r.get("markdown", ""), grounding_text)
            cand = backlog.new_candidate(
                domain, name, r["url"], _guess_bucket(r.get("markdown", "")),
                "websearch", today,
            )
            cand["novelty_score"], cand["icp_relevance"] = nov, icp
            if backlog.add(records, cand):
                added += 1
                log.info(f"discovered: {domain} (nov={nov}, icp={icp})")
    return added


def meta_ad_library_boost(cfg, records, fc, today) -> int:
    """Best-effort: scrape the public Ad Library search UI for advertiser domains.
    Any failure returns 0 and never propagates — this must not block delivery."""
    added = 0
    try:
        for query in cfg.get("meta_ad_library_queries", []):
            url = ("https://www.facebook.com/ads/library/?active_status=active"
                   f"&ad_type=all&country=US&q={query.replace(' ', '%20')}&media_type=all")
            md = fc.scrape(url)
            if not md:
                continue
            for m in re.findall(r"https?://[^\s)\]]+", md):
                domain = extract_domain(m)
                if (domain and "facebook" not in domain and "fbcdn" not in domain
                        and not is_excluded(domain, cfg.get("exclude_domains", []))
                        and not backlog.has_domain(records, domain)):
                    cand = backlog.new_candidate(domain, domain.split(".")[0], m, "A",
                                                 "meta_ad_library", today)
                    if backlog.add(records, cand):
                        added += 1
    except Exception as e:
        log.warning(f"meta_ad_library_boost skipped: {e}")
        return added
    return added
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest scout/tests/test_discovery.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add scout/discovery.py scout/tests/test_discovery.py
git commit -m "feat(scout): hybrid discovery — search-seed scoring + best-effort Meta booster"
```

---

## Task 5: Teardown analysis (`teardown.py`)

**Files:**
- Create: `scout/teardown.py`
- Test: `scout/tests/test_teardown.py`

**Interfaces:**
- Consumes: `FirecrawlClient.scrape`, an `anthropic.Anthropic` client, grounding text, a candidate dict.
- Produces:
  - `content_hash(text: str) -> str` (sha256 hex of normalized text)
  - `scrape_platform(fc, url) -> str | None` (homepage + pricing + features markdown concatenated; None if homepage scrape fails)
  - `analyze(candidate, fc, client, grounding_text) -> dict | None` — returns a teardown dict, or `None` if scrape fails. Teardown dict keys: `name, url, bucket, description, segment, standout, features (list[str]), pricing, traction, maturity, os_takeaways (list[{feature, tag, note}]), jtbd ({platform_jtbd, verdict, note, quoted_line}), content_hash`.

- [ ] **Step 1: Write the failing test `scout/tests/test_teardown.py`**

```python
import json

from scout import teardown, backlog


def test_content_hash_stable_and_normalized():
    assert teardown.content_hash("  Hello  World ") == teardown.content_hash("hello world")
    assert teardown.content_hash("a") != teardown.content_hash("b")


class _FakeFC:
    def __init__(self, pages):  # pages: dict[url_substr] -> markdown
        self.pages = pages
    def scrape(self, url):
        for key, md in self.pages.items():
            if key in url:
                return md
        return None


_TEARDOWN_JSON = {
    "description": "Online coaching platform",
    "segment": "online coaches",
    "standout": "native-language localization",
    "features": ["workout builder", "meal planner"],
    "pricing": "EUR 69/mo",
    "traction": "self-reported 100+ coaches",
    "maturity": "polished early startup",
    "os_takeaways": [{"feature": "meal planner", "tag": "🚫 Out of scope", "note": "OS focuses on programming"}],
    "jtbd": {"platform_jtbd": "run whole coaching biz from one screen",
             "verdict": "📣 Positioning gap",
             "note": "OS also consolidates but doesn't say so",
             "quoted_line": "a client's whole week from one screen"},
}


def _fake_client(captured):
    class _Resp:
        content = [type("C", (), {"text": json.dumps(_TEARDOWN_JSON)})()]
    class _Msgs:
        def create(self, **k):
            captured.append(k)
            return _Resp()
    class _Client:
        messages = _Msgs()
    return _Client()


def test_analyze_returns_teardown_and_injects_grounding():
    cand = backlog.new_candidate("coachway.io", "Coachway", "https://coachway.io/", "B", "seed", "2026-08-06")
    fc = _FakeFC({"coachway.io": "# Coachway\nonline coaching for everyone"})
    captured = []
    client = _fake_client(captured)
    result = teardown.analyze(cand, fc, client, "OS_GROUNDING_MARKER")
    assert result["name"] == "Coachway"
    assert result["standout"] == "native-language localization"
    assert result["jtbd"]["verdict"] == "📣 Positioning gap"
    assert result["content_hash"]
    # grounding text MUST be present in the prompt sent to Claude
    sent = json.dumps(captured[0])
    assert "OS_GROUNDING_MARKER" in sent


def test_analyze_returns_none_when_scrape_fails():
    cand = backlog.new_candidate("dead.com", "Dead", "https://dead.com/", "A", "seed", "2026-08-06")
    fc = _FakeFC({})  # scrape returns None for everything
    result = teardown.analyze(cand, fc, _fake_client([]), "G")
    assert result is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scout/tests/test_teardown.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scout.teardown'`.

- [ ] **Step 3: Write `scout/teardown.py`**

```python
"""Per-platform teardown: scrape + grounded Claude analysis."""
import hashlib
import json
import logging
import re

log = logging.getLogger(__name__)

ANALYSIS_MODEL = "claude-opus-4-8"

ANALYSIS_SYSTEM = """You are a competitive-intelligence analyst producing a teardown of an \
emerging fitness-business / gym-management / online-coaching software platform for the VP of \
Sales at TeamBuildr OS. Your job is feature idea-mining.

You are given (a) the platform's scraped marketing pages and (b) a GROUNDING PROFILE of \
TeamBuildr OS (its strengths, gaps, market fit, JTBD, and two tagging schemes).

Rules — read carefully:
- Assign every OS-relevance tag and JTBD verdict ONLY by looking up against the GROUNDING \
PROFILE text. NEVER invent OS strategy, roadmap, or positioning. If something does not map \
cleanly, tag it "❓ Your call".
- Lean by default: a missing feature is "🎯 Real gap" ONLY if it hits real ICP pain named in \
the grounding. Bells-and-whistles OS deliberately skipped → "🚫 Out of scope".
- Competitor AI features → "🎯 Real gap" tagged "in progress" (never a blind-spot alarm).
- For JTBD: read the platform's own JTBD from its copy, then pick exactly one verdict \
(📣 Positioning gap / 🎯 Real job gap / ➖ Different job). If 📣, quote the platform's exact \
positioning line.

Return ONLY a JSON object with keys: description, segment, standout, features (array of \
strings), pricing, traction, maturity, os_takeaways (array of {feature, tag, note}), \
jtbd ({platform_jtbd, verdict, note, quoted_line}). No prose outside the JSON."""

_PAGE_PATHS = ["", "pricing", "features", "product", "about"]


def content_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def scrape_platform(fc, url: str) -> str | None:
    base = url.rstrip("/")
    home = fc.scrape(base + "/")
    if not home:
        return None
    parts = [home]
    for path in _PAGE_PATHS[1:]:
        md = fc.scrape(f"{base}/{path}")
        if md:
            parts.append(f"\n\n--- /{path} ---\n{md}")
    return "\n".join(parts)


def analyze(candidate: dict, fc, client, grounding_text: str) -> dict | None:
    content = scrape_platform(fc, candidate["url"])
    if not content:
        log.warning(f"scrape failed, skipping: {candidate['domain']}")
        return None

    user = (
        f"PLATFORM: {candidate['name']} ({candidate['url']})\n\n"
        f"=== SCRAPED PAGES ===\n{content[:18000]}\n\n"
        f"=== GROUNDING PROFILE (TeamBuildr OS) ===\n{grounding_text}"
    )
    try:
        resp = client.messages.create(
            model=ANALYSIS_MODEL,
            max_tokens=2000,
            system=ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
    except Exception as e:
        log.error(f"analysis failed for {candidate['domain']}: {e}")
        return None

    data["name"] = candidate["name"]
    data["url"] = candidate["url"]
    data["bucket"] = candidate.get("bucket", "A")
    data["content_hash"] = content_hash(content)
    return data
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest scout/tests/test_teardown.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add scout/teardown.py scout/tests/test_teardown.py
git commit -m "feat(scout): grounded per-platform teardown analysis"
```

---

## Task 6: Emailer (`emailer.py`)

**Files:**
- Create: `scout/emailer.py`
- Test: `scout/tests/test_emailer.py`

**Interfaces:**
- Consumes: teardown dicts from `teardown.analyze`.
- Produces:
  - `format_email(teardowns: list[dict], date_str: str) -> tuple[str, str]` — `(subject, html_body)`. Handles the empty list (0 teardowns) with a "no new platforms this week" body.
  - `send_email(subject: str, html_body: str, recipient: str) -> bool` — via Gmail SMTP SSL 465 + `GMAIL_APP_PASSWORD`; returns True on send, False if skipped/failed (never raises).

- [ ] **Step 1: Write the failing test `scout/tests/test_emailer.py`**

```python
from scout import emailer

_TD = {
    "name": "Coachway", "url": "https://coachway.io/", "bucket": "B",
    "description": "Online coaching platform", "segment": "online coaches",
    "standout": "native-language localization",
    "features": ["workout builder", "meal planner"],
    "pricing": "EUR 69/mo", "traction": "100+ coaches (self-reported)",
    "maturity": "polished early startup",
    "os_takeaways": [{"feature": "meal planner", "tag": "🚫 Out of scope", "note": "OS focuses on programming"}],
    "jtbd": {"platform_jtbd": "run whole biz from one screen", "verdict": "📣 Positioning gap",
             "note": "OS consolidates but doesn't market it", "quoted_line": "whole week from one screen"},
}


def test_format_email_includes_standout_tags_and_jtbd():
    subject, body = emailer.format_email([_TD], "2026-08-07")
    assert "Coachway" in subject
    assert "native-language localization" in body     # standout headline
    assert "🚫 Out of scope" in body                   # taxonomy tag rendered
    assert "📣 Positioning gap" in body                # jtbd verdict rendered
    assert "whole week from one screen" in body        # quoted positioning line
    assert "<" in body and ">" in body                 # HTML


def test_format_email_empty_is_honest_not_blank():
    subject, body = emailer.format_email([], "2026-08-07")
    assert "no new" in body.lower() or "no fresh" in body.lower()
    assert len(body) > 0


def test_send_email_skips_without_password(monkeypatch):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert emailer.send_email("s", "<p>b</p>", "trent@teambuildr.com") is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scout/tests/test_emailer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scout.emailer'`.

- [ ] **Step 3: Write `scout/emailer.py`**

```python
"""Format + send the weekly Fitness Scout email (HTML via Gmail SMTP)."""
import logging
import os
import smtplib
from email.mime.text import MIMEText
from html import escape

log = logging.getLogger(__name__)

GMAIL_USER = "trent@teambuildr.com"


def _teardown_html(td: dict) -> str:
    feats = "".join(f"<li>{escape(str(f))}</li>" for f in td.get("features", []))
    takeaways = "".join(
        f"<li><strong>{escape(t.get('tag',''))}</strong> — "
        f"{escape(t.get('feature',''))}: {escape(t.get('note',''))}</li>"
        for t in td.get("os_takeaways", [])
    )
    jt = td.get("jtbd", {}) or {}
    quoted = jt.get("quoted_line")
    quoted_html = f'<p style="margin:4px 0"><em>&ldquo;{escape(quoted)}&rdquo;</em></p>' if quoted else ""
    bucket = "Online coaching" if td.get("bucket") == "B" else "Brick-and-mortar"
    return f"""
    <div style="margin:0 0 32px 0;padding:0 0 24px 0;border-bottom:1px solid #ddd">
      <h2 style="margin:0 0 2px 0">{escape(td.get('name',''))}
        <span style="font-weight:normal;font-size:13px;color:#888"> · {bucket} ·
        <a href="{escape(td.get('url',''))}">{escape(td.get('url',''))}</a></span></h2>
      <p style="color:#555;margin:2px 0 12px 0">{escape(td.get('description',''))}</p>
      <p style="background:#fff8e1;padding:10px 12px;border-left:3px solid #f0b400;margin:0 0 14px 0">
        <strong>⚡ Standout wedge:</strong> {escape(td.get('standout',''))}</p>
      <p style="margin:2px 0"><strong>Segment:</strong> {escape(td.get('segment',''))}</p>
      <p style="margin:2px 0"><strong>Pricing:</strong> {escape(td.get('pricing',''))}</p>
      <p style="margin:2px 0"><strong>Traction:</strong> {escape(td.get('traction',''))}</p>
      <p style="margin:2px 0"><strong>Maturity:</strong> {escape(td.get('maturity',''))}</p>
      <p style="margin:12px 0 2px 0"><strong>Feature set:</strong></p>
      <ul style="margin:2px 0">{feats}</ul>
      <p style="margin:12px 0 2px 0"><strong>OS-tagged takeaways:</strong></p>
      <ul style="margin:2px 0">{takeaways}</ul>
      <div style="background:#f0f4ff;padding:10px 12px;border-left:3px solid #4361ee;margin:12px 0 0 0">
        <p style="margin:0 0 4px 0"><strong>JTBD:</strong> {escape(jt.get('platform_jtbd',''))}</p>
        {quoted_html}
        <p style="margin:4px 0 0 0"><strong>Verdict:</strong> {escape(jt.get('verdict',''))} —
          {escape(jt.get('note',''))}</p>
      </div>
    </div>"""


def format_email(teardowns: list, date_str: str) -> tuple:
    if not teardowns:
        body = (f'<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:680px">'
                f"<h1>Fitness Scout — {escape(date_str)}</h1>"
                f"<p>No new platforms surfaced this week. The discovery backlog is empty of "
                f"uncovered candidates — seed one with <code>python scout.py --seed &lt;url&gt;</code>.</p></div>")
        return (f"Fitness Scout — {date_str} (no new platforms)", body)

    names = " & ".join(td.get("name", "?") for td in teardowns)
    subject = f"Fitness Scout — {date_str}: {names}"
    inner = "".join(_teardown_html(td) for td in teardowns)
    body = (f'<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:680px">'
            f"<h1 style='margin:0 0 4px 0'>Fitness Scout</h1>"
            f"<p style='color:#888;margin:0 0 24px 0'>{escape(date_str)} · "
            f"{len(teardowns)} emerging platform teardown(s)</p>{inner}</div>")
    return subject, body


def send_email(subject: str, html_body: str, recipient: str = GMAIL_USER) -> bool:
    app_password = os.getenv("GMAIL_APP_PASSWORD", "")
    if not app_password:
        log.warning("GMAIL_APP_PASSWORD not set — skipping email")
        return False
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = recipient
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, app_password)
            server.sendmail(GMAIL_USER, [recipient], msg.as_string())
        log.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest scout/tests/test_emailer.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add scout/emailer.py scout/tests/test_emailer.py
git commit -m "feat(scout): HTML email formatting + Gmail SMTP send"
```

---

## Task 7: Orchestrator + CLI (`scout.py`)

**Files:**
- Create: `scout/scout.py`
- Test: `scout/tests/test_scout.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `run_weekly(dry_run=False, discover_only=False, today=None) -> dict` — returns `{"discovered": int, "teardowns": int, "sent": bool}`. Loads backlog, runs discovery + meta boost, (unless discover_only) selects `teardowns_per_week` uncovered, analyzes each, marks covered, formats + sends email, archives brief, saves backlog.
  - `seed(url: str, today=None) -> bool` — adds a seed candidate to the backlog.
  - `list_covered() -> list[dict]`
  - `main(argv=None)` — argparse dispatch.
- Clients built via small factories so tests can inject fakes: `_anthropic()`, `_firecrawl()`.

- [ ] **Step 1: Write the failing test `scout/tests/test_scout.py`**

```python
import scout.scout as scout
from scout import backlog


def test_seed_adds_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    assert scout.seed("https://xoda.com/pricing", today="2026-08-06") is True
    recs = backlog.load(tmp_path / "c.jsonl")
    assert recs[0]["domain"] == "xoda.com"
    assert recs[0]["seed"] is True


def test_run_weekly_selects_analyzes_marks_and_sends(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    monkeypatch.setattr(scout.config, "COVERED_FILE", tmp_path / "cov.jsonl")
    monkeypatch.setattr(scout.config, "BRIEFS_DIR", tmp_path / "briefs")

    # pre-stock backlog with two uncovered candidates
    recs = [backlog.new_candidate(f"p{i}.com", f"P{i}", f"https://p{i}.com/", "A", "seed", "2026-08-01")
            for i in range(2)]
    backlog.save(recs, tmp_path / "c.jsonl")

    monkeypatch.setattr(scout, "_firecrawl", lambda: object())
    monkeypatch.setattr(scout, "_anthropic", lambda: object())
    monkeypatch.setattr(scout.discovery, "run_discovery", lambda *a, **k: 0)
    monkeypatch.setattr(scout.discovery, "meta_ad_library_boost", lambda *a, **k: 0)
    monkeypatch.setattr(scout.config, "load_grounding", lambda: "G")

    def fake_analyze(cand, fc, client, grounding):
        return {"name": cand["name"], "url": cand["url"], "bucket": "A",
                "content_hash": "h_" + cand["domain"], "standout": "x",
                "features": [], "os_takeaways": [], "jtbd": {}}
    monkeypatch.setattr(scout.teardown, "analyze", fake_analyze)

    sent = {}
    monkeypatch.setattr(scout.emailer, "send_email",
                        lambda subj, body, recip=None: sent.update(subj=subj) or True)

    result = scout.run_weekly(dry_run=False, today="2026-08-07")
    assert result["teardowns"] == 2
    assert result["sent"] is True

    covered = [r for r in backlog.load(tmp_path / "c.jsonl") if r["covered"]]
    assert len(covered) == 2                       # both marked covered
    assert covered[0]["content_hash"].startswith("h_")


def test_run_weekly_dry_run_does_not_send(tmp_path, monkeypatch):
    monkeypatch.setattr(scout.config, "CANDIDATES_FILE", tmp_path / "c.jsonl")
    monkeypatch.setattr(scout.config, "COVERED_FILE", tmp_path / "cov.jsonl")
    monkeypatch.setattr(scout.config, "BRIEFS_DIR", tmp_path / "briefs")
    backlog.save([backlog.new_candidate("p.com", "P", "https://p.com/", "A", "seed", "2026-08-01")],
                 tmp_path / "c.jsonl")
    monkeypatch.setattr(scout, "_firecrawl", lambda: object())
    monkeypatch.setattr(scout, "_anthropic", lambda: object())
    monkeypatch.setattr(scout.discovery, "run_discovery", lambda *a, **k: 0)
    monkeypatch.setattr(scout.discovery, "meta_ad_library_boost", lambda *a, **k: 0)
    monkeypatch.setattr(scout.config, "load_grounding", lambda: "G")
    monkeypatch.setattr(scout.teardown, "analyze",
                        lambda c, *a: {"name": c["name"], "url": c["url"], "bucket": "A",
                                       "content_hash": "h", "features": [], "os_takeaways": [], "jtbd": {}})
    called = {"sent": False}
    monkeypatch.setattr(scout.emailer, "send_email",
                        lambda *a, **k: called.update(sent=True) or True)
    result = scout.run_weekly(dry_run=True, today="2026-08-07")
    assert called["sent"] is False
    assert result["sent"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest scout/tests/test_scout.py -v`
Expected: FAIL with `ModuleNotFoundError` / attribute errors.

- [ ] **Step 3: Write `scout/scout.py`**

```python
"""Fitness Scout orchestrator + CLI."""
import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from . import backlog, config, discovery, emailer, teardown
from .firecrawl_client import FirecrawlClient

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("scout")


def _anthropic():
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _firecrawl():
    return FirecrawlClient(os.getenv("FIRECRAWL_API_KEY", ""))


def _today(today=None) -> str:
    return today or datetime.now().strftime("%Y-%m-%d")


def seed(url: str, today=None) -> bool:
    recs = backlog.load(config.CANDIDATES_FILE)
    domain = discovery.extract_domain(url)
    if not domain:
        log.error(f"could not parse domain from {url}")
        return False
    cand = backlog.new_candidate(domain, domain.split(".")[0], url, "A", "seed", _today(today), seed=True)
    added = backlog.add(recs, cand)
    backlog.save(recs, config.CANDIDATES_FILE)
    log.info(f"seed {'added' if added else 'already present'}: {domain}")
    return added


def list_covered() -> list:
    return [r for r in backlog.load(config.CANDIDATES_FILE) if r.get("covered")]


def _archive_brief(subject: str, body: str, today: str):
    Path(config.BRIEFS_DIR).mkdir(parents=True, exist_ok=True)
    (Path(config.BRIEFS_DIR) / f"{today}.html").write_text(body, encoding="utf-8")


def run_weekly(dry_run: bool = False, discover_only: bool = False, today=None) -> dict:
    today = _today(today)
    cfg = config.load_config()
    grounding = config.load_grounding()
    fc = _firecrawl()
    client = _anthropic()

    recs = backlog.load(config.CANDIDATES_FILE)

    # 1. Discovery (never blocks delivery)
    n_disc = discovery.run_discovery(cfg, recs, fc, client, grounding, today)
    n_disc += discovery.meta_ad_library_boost(cfg, recs, fc, today)
    backlog.save(recs, config.CANDIDATES_FILE)
    log.info(f"discovery added {n_disc} candidate(s)")

    if discover_only:
        return {"discovered": n_disc, "teardowns": 0, "sent": False}

    # 2. Select + analyze
    picks = backlog.select_uncovered(recs, cfg.get("teardowns_per_week", 2))
    teardowns = []
    for cand in picks:
        td = teardown.analyze(cand, fc, client, grounding)
        if td is None:
            continue
        teardowns.append(td)
        backlog.mark_covered(recs, cand["domain"], td["content_hash"], today)

    # 3. Format
    subject, body = emailer.format_email(teardowns, today)

    # 4. Persist coverage + archive
    backlog.save(recs, config.CANDIDATES_FILE)
    covered_recs = [r for r in recs if r.get("covered")]
    backlog.save(covered_recs, config.COVERED_FILE)
    _archive_brief(subject, body, today)

    # 5. Send (unless dry-run)
    sent = False
    if dry_run:
        print(subject)
        print(body)
    else:
        sent = emailer.send_email(subject, body, cfg.get("recipient", emailer.GMAIL_USER))

    return {"discovered": n_disc, "teardowns": len(teardowns), "sent": sent}


def _git_commit(today: str):
    """Stage + commit scout/data so state persists across cloud runs. Push handled by the workflow."""
    try:
        subprocess.run(["git", "add", "scout/data"], check=False)
        subprocess.run(["git", "commit", "-m", f"scout run {today} [skip ci]"], check=False)
    except Exception as e:
        log.warning(f"git commit skipped: {e}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fitness Scout — weekly competitor teardown agent")
    parser.add_argument("--dry-run", action="store_true", help="run everything except sending the email")
    parser.add_argument("--discover-only", action="store_true", help="refill backlog only, no email")
    parser.add_argument("--seed", metavar="URL", help="add a platform URL to the backlog (jumps the queue)")
    parser.add_argument("--covered", action="store_true", help="list platforms already sent")
    parser.add_argument("--commit", action="store_true", help="git commit scout/data after the run")
    args = parser.parse_args(argv)

    if args.seed:
        return 0 if seed(args.seed) else 1
    if args.covered:
        for r in list_covered():
            print(f"{r['covered_at']}  {r['domain']}")
        return 0

    result = run_weekly(dry_run=args.dry_run, discover_only=args.discover_only)
    log.info(f"run complete: {result}")
    if args.commit and not args.dry_run:
        _git_commit(_today())
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest scout/tests/test_scout.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Run the full module test suite**

Run: `python -m pytest scout/tests/ -v`
Expected: PASS (all tests across all 7 files).

- [ ] **Step 6: Commit**

```bash
git add scout/scout.py scout/tests/test_scout.py
git commit -m "feat(scout): orchestrator + CLI (run/dry-run/discover-only/seed/covered)"
```

---

## Task 8: GitHub Actions workflow (`scout.yml`)

**Files:**
- Create: `.github/workflows/scout.yml`

**Interfaces:**
- Consumes: `scout.py` CLI; secrets `ANTHROPIC_API_KEY`, `GMAIL_APP_PASSWORD`, `FIRECRAWL_API_KEY`.

- [ ] **Step 1: Write `.github/workflows/scout.yml`**

```yaml
name: Fitness Scout Weekly

on:
  schedule:
    # Friday 7am CDT (UTC-5, Apr–Oct). Change to "0 13 * * 5" in November for CST (UTC-6).
    - cron: "0 12 * * 5"
  workflow_dispatch:

jobs:
  run-fitness-scout:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    env:
      TZ: America/Chicago

    steps:
      - uses: actions/checkout@v5
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: scout/requirements.txt

      - name: Install dependencies
        run: pip install -r scout/requirements.txt

      - name: Configure git
        run: |
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git config user.name "github-actions[bot]"

      - name: Run weekly scout
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          FIRECRAWL_API_KEY: ${{ secrets.FIRECRAWL_API_KEY }}
        run: python -m scout.scout --commit

      - name: Push data files
        run: git push origin main
```

Note: `python -m scout.scout` (module form) is required because `scout.py` uses package-relative imports (`from . import ...`). Run it from the repo root (the default working directory), NOT with `working-directory: scout`.

- [ ] **Step 2: Validate the workflow YAML locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/scout.yml'))" && echo OK`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/scout.yml
git commit -m "feat(scout): Friday 7am CDT GitHub Actions workflow"
```

---

## Post-Build Verification (manual, before enabling the cron)

These are not code steps — they confirm the deployed module works end-to-end. Do them after Task 8 and after the three secrets are set in GitHub.

1. **Local dry-run with real keys** (needs `ANTHROPIC_API_KEY` + `FIRECRAWL_API_KEY` in `scout/.env` or the shell): seed two known platforms and dry-run.
   ```bash
   python -m scout.scout --seed https://coachway.io/
   python -m scout.scout --seed https://gymdesk.com/
   python -m scout.scout --dry-run
   ```
   Confirm: two teardowns print, each with a standout wedge, taxonomy-tagged takeaways, and a JTBD verdict; `scout/data/candidates.jsonl` shows both marked covered; `scout/data/briefs/<date>.html` exists.
2. **Discovery smoke test:** `python -m scout.scout --discover-only` and confirm `candidates.jsonl` gains real upstart domains (and no excluded incumbents).
3. **Add the GitHub Secrets:** `FIRECRAWL_API_KEY` (new); confirm `ANTHROPIC_API_KEY` and `GMAIL_APP_PASSWORD` already exist (they power the brief + market-intel).
4. **Manual cloud run:** trigger `Fitness Scout Weekly` via `workflow_dispatch` and confirm the email arrives and `scout/data/` is committed back to `main`.
5. Only after a clean manual cloud run, let the Friday cron take over.

---

## Self-Review

**Spec coverage:**
- Autonomous Friday email, 2 teardowns → Tasks 7 (`run_weekly`) + 8 (cron). ✓
- OS grounding profile injected, never regenerated → Task 1 (`os_grounding.md`) + Task 5 (verbatim injection, test asserts marker present). ✓
- Feature taxonomy + JTBD verdicts, lookup-only → Task 5 `ANALYSIS_SYSTEM` rules; rendered in Task 6. ✓
- Hybrid discovery (web primary + Meta best-effort booster) → Task 4 (`run_discovery` + `meta_ad_library_boost`, latter cannot raise). ✓
- Candidate backlog decoupled from delivery; seeds jump queue → Task 2 (`select_uncovered`) + Task 7. ✓
- Never send nothing on a Friday → Task 6 (`format_email([])` honest body). ✓
- Never repeat a platform; re-cover only if changed → Task 5 (`content_hash`) + Task 2 (`mark_covered`) + Task 7 (covered excluded from selection). *(Note: the "resurface only if content changed" comparison for an already-covered platform is realized by selection excluding covered records; a future enhancement could re-queue a covered platform when a fresh hash differs — out of scope for v1, logged here.)*
- Isolated module, market-intel patterns, no lib imports → all tasks; workflow mirrors `market-intel-weekly.yml`. ✓
- State persists via commit-back → Task 7 (`_git_commit`) + Task 8 (push step); `scout/data/` is not gitignored (verified). ✓
- CLI: run / dry-run / discover-only / seed / covered → Task 7 `main`. ✓
- Model strings, email sender, cron math, Firecrawl-in-Actions (the spec's four open questions) → resolved in Global Constraints + Tasks 3/5/6/8. ✓

**Placeholder scan:** No TBD/TODO/"handle errors appropriately"; every code step shows complete code; every test shows real assertions. ✓

**Type consistency:** teardown dict keys (`name, url, bucket, description, segment, standout, features, pricing, traction, maturity, os_takeaways, jtbd, content_hash`) are produced identically in Task 5 and consumed in Task 6 and the Task 7 fake. `select_uncovered`, `mark_covered`, `new_candidate`, `add`, `has_domain`, `load`, `save` names match across Tasks 2/4/7. `FirecrawlClient.search/scrape` signatures match across Tasks 3/4/5. `run_weekly` return keys (`discovered/teardowns/sent`) match its tests. ✓

**One deliberate v1 limitation logged:** an already-covered platform is not automatically re-queued when its content hash later changes (selection simply skips covered records). The `content_hash` is stored so a future task can add "re-cover on change"; v1 does not, to keep the selection logic simple. Flagged rather than hidden.
