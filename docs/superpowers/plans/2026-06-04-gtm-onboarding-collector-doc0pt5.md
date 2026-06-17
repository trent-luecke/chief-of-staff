# GTM Onboarding Collector (Doc 0.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Onboarding Tracker collector (Notion REST API → `data/onboarding_cache.json`), a cache reader that filters to active records, and a durable CronCreate routine that keeps the cache current nightly.

**Architecture:** `collectors/notion_onboarding.py` mirrors `collectors/notion_pipeline.py` exactly — same `_query_all` + `sync()` pattern, same `NOTION_TOKEN` env var, same cache file shape. `collectors/onboarding.py` reads the cache and filters to active-status records (the late-stage count source for doc 1). The CronCreate routine uses the Notion MCP (not the REST API) for the actual automated sync, since MCP session auth is reliable locally whereas `NOTION_TOKEN` is not yet a GitHub Secret. Both paths produce identical cache output.

**Tech Stack:** Python 3.11+, requests (existing), Notion REST API v1, pytest, CronCreate (Claude Code built-in)

---

## Key constants

- **Notion Database ID:** `d4904af6-77b0-4507-8655-353ae4eadbd2`
- **Cache file:** `data/onboarding_cache.json`
- **Active statuses (in the chamber):** `["In Progress", "Awaiting Customer", "Ready to Go Live"]`
- **Excluded:** `"Not Started"` (warm lead, not committed), `"Live"` (already closed)

---

## Notion field → cache field mapping

| Notion property | Notion type | Cache key |
|-----------------|-------------|-----------|
| `Customer Name` | `title` | `customer_name` |
| `Customer Email` | `email` | `customer_email` |
| `Status` | `select` | `status` |
| `Current Phase` | `select` | `current_phase` |
| `Sales Rep` | `select` | `sales_rep` |
| `Start Date` | `date` | `start_date` |
| `Target Go-Live Date` | `date` | `target_go_live_date` |

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `collectors/notion_onboarding.py` | Notion REST API sync → `data/onboarding_cache.json` |
| Create | `collectors/onboarding.py` | Cache reader; filters to active statuses |
| Modify | `config.json` | Add `onboarding` block |
| Create | `tests/test_notion_onboarding.py` | Tests for `_parse_row()` and `sync()` output shape |
| Create | `tests/test_onboarding_collector.py` | Tests for `load_onboarding_active()` |
| Runtime | CronCreate routine | Nightly MCP-based sync prompt (no code file) |

---

## Task 1: Add `onboarding` block to `config.json`

**Files:**
- Modify: `config.json`

- [ ] **Step 1.1: Add the `onboarding` block**

Read `config.json`. Add this block after the `"pipeline"` block (after line 44):

```json
"onboarding": {
  "cache_path": "data/onboarding_cache.json",
  "database_id": "d4904af6-77b0-4507-8655-353ae4eadbd2",
  "active_statuses": ["In Progress", "Awaiting Customer", "Ready to Go Live"],
  "cache_stale_warn_days": 2
},
```

`cache_stale_warn_days: 2` — onboarding data is higher-stakes than pipeline data; warn after 2 days stale vs. the pipeline's 7.

- [ ] **Step 1.2: Verify JSON is valid**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python3 -c "import json; json.load(open('config.json')); print('valid')"
```
Expected: `valid`

- [ ] **Step 1.3: Commit**

```bash
git add config.json
git commit -m "feat: add onboarding config block"
```

---

## Task 2: `collectors/notion_onboarding.py` — REST API sync

Mirrors `collectors/notion_pipeline.py` structure exactly. The `_get()` helper is copied verbatim — it handles all the field types in the onboarding schema.

**Files:**
- Create: `collectors/notion_onboarding.py`
- Create: `tests/test_notion_onboarding.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/test_notion_onboarding.py
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from collectors.notion_onboarding import _parse_row, sync, DATABASE_ID


MOCK_ROW = {
    "id": "abc-123-def-456",
    "properties": {
        "Customer Name": {
            "type": "title",
            "title": [{"plain_text": "Acme Strength"}],
        },
        "Customer Email": {
            "type": "email",
            "email": "owner@acmestrength.com",
        },
        "Status": {
            "type": "select",
            "select": {"name": "In Progress"},
        },
        "Current Phase": {
            "type": "select",
            "select": {"name": "Phase 3 — Payment / Stripe Transfer"},
        },
        "Sales Rep": {
            "type": "select",
            "select": {"name": "Chris"},
        },
        "Start Date": {
            "type": "date",
            "date": {"start": "2026-05-15"},
        },
        "Target Go-Live Date": {
            "type": "date",
            "date": {"start": "2026-06-10"},
        },
    },
}


def test_parse_row_extracts_all_fields():
    record = _parse_row(MOCK_ROW)
    assert record["page_id"] == "abc-123-def-456"
    assert record["customer_name"] == "Acme Strength"
    assert record["customer_email"] == "owner@acmestrength.com"
    assert record["status"] == "In Progress"
    assert record["current_phase"] == "Phase 3 — Payment / Stripe Transfer"
    assert record["sales_rep"] == "Chris"
    assert record["start_date"] == "2026-05-15"
    assert record["target_go_live_date"] == "2026-06-10"


def test_parse_row_handles_missing_optional_fields():
    row = {
        "id": "xyz-999",
        "properties": {
            "Customer Name": {"type": "title", "title": []},
            "Customer Email": {"type": "email", "email": None},
            "Status": {"type": "select", "select": None},
            "Current Phase": {"type": "select", "select": None},
            "Sales Rep": {"type": "select", "select": None},
            "Start Date": {"type": "date", "date": None},
            "Target Go-Live Date": {"type": "date", "date": None},
        },
    }
    record = _parse_row(row)
    assert record["customer_name"] == ""
    assert record["customer_email"] is None
    assert record["status"] is None
    assert record["start_date"] is None


def test_database_id_constant_is_set():
    assert DATABASE_ID == "d4904af6-77b0-4507-8655-353ae4eadbd2"


def test_sync_writes_valid_cache_file():
    with patch("collectors.notion_onboarding._query_all", return_value=[MOCK_ROW]):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_path = f.name
        sync("fake-token", cache_path)
        data = json.loads(Path(cache_path).read_text())

    assert "synced_at" in data
    assert isinstance(data["records"], list)
    assert len(data["records"]) == 1
    assert data["records"][0]["customer_name"] == "Acme Strength"
    assert data["records"][0]["status"] == "In Progress"
```

- [ ] **Step 2.2: Run to verify it fails**

```
pytest tests/test_notion_onboarding.py -v
```
Expected: `ImportError: No module named 'collectors.notion_onboarding'`

- [ ] **Step 2.3: Create `collectors/notion_onboarding.py`**

```python
"""Notion onboarding tracker collector — syncs OS Customer Onboarding Tracker to cache."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests


DATABASE_ID = "d4904af6-77b0-4507-8655-353ae4eadbd2"

_HEADERS = lambda token: {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _get(props: dict, key: str, kind: str, fallback=None):
    block = props.get(key, {})
    if kind == "title":
        parts = block.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts) or fallback
    if kind == "select":
        return (block.get("select") or {}).get("name", fallback)
    if kind == "email":
        return block.get("email", fallback)
    if kind == "date":
        return (block.get("date") or {}).get("start", fallback)
    return fallback


def _query_all(token: str, database_id: str) -> list[dict]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    results = []
    cursor = None
    while True:
        body = {}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(url, headers=_HEADERS(token), json=body)
        if resp.status_code != 200:
            print(f"Notion API error {resp.status_code}: {resp.text}", file=sys.stderr)
            break
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _parse_row(row: dict) -> dict:
    props = row.get("properties", {})
    return {
        "page_id": row["id"],
        "customer_name": _get(props, "Customer Name", "title", ""),
        "customer_email": _get(props, "Customer Email", "email"),
        "status": _get(props, "Status", "select"),
        "current_phase": _get(props, "Current Phase", "select"),
        "sales_rep": _get(props, "Sales Rep", "select"),
        "start_date": _get(props, "Start Date", "date"),
        "target_go_live_date": _get(props, "Target Go-Live Date", "date"),
    }


def sync(token: str, cache_path: str) -> None:
    """Pull all onboarding records and write cache file."""
    rows = _query_all(token, DATABASE_ID)
    records = [_parse_row(row) for row in rows]

    out = {
        "synced_at": datetime.utcnow().isoformat() + "Z",
        "records": records,
    }
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(records)} onboarding records to {cache_path}")


if __name__ == "__main__":
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        print("NOTION_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    cache_path = sys.argv[1] if len(sys.argv) > 1 else "data/onboarding_cache.json"
    sync(token, cache_path)
```

- [ ] **Step 2.4: Run to verify tests pass**

```
pytest tests/test_notion_onboarding.py -v
```
Expected: 4 tests PASS

- [ ] **Step 2.5: Commit**

```bash
git add collectors/notion_onboarding.py tests/test_notion_onboarding.py
git commit -m "feat: add notion_onboarding collector and sync function"
```

---

## Task 3: `collectors/onboarding.py` — cache reader

Reads `data/onboarding_cache.json` and filters to active statuses. Returns `list[dict]` — the same dicts written by `sync()`. `len(load_onboarding_active(...))` is the late-stage count for doc 1.

**Files:**
- Create: `collectors/onboarding.py`
- Create: `tests/test_onboarding_collector.py`

- [ ] **Step 3.1: Write the failing tests**

```python
# tests/test_onboarding_collector.py
import json
import tempfile
from pathlib import Path

import pytest

from collectors.onboarding import load_onboarding_active


ACTIVE = ["In Progress", "Awaiting Customer", "Ready to Go Live"]

FIXTURE_CACHE = {
    "synced_at": "2026-06-04T12:00:00Z",
    "records": [
        {"page_id": "a1", "customer_name": "Acme Strength", "status": "In Progress",
         "current_phase": "Phase 3", "sales_rep": "Chris", "start_date": "2026-05-01",
         "target_go_live_date": "2026-06-10", "customer_email": "a@acme.com"},
        {"page_id": "a2", "customer_name": "Peak Perf", "status": "Awaiting Customer",
         "current_phase": "Phase 5", "sales_rep": "Jeff", "start_date": "2026-05-10",
         "target_go_live_date": "2026-06-15", "customer_email": "b@peak.com"},
        {"page_id": "a3", "customer_name": "Old Gym", "status": "Live",
         "current_phase": "Phase 7", "sales_rep": "Ryan", "start_date": "2026-04-01",
         "target_go_live_date": "2026-05-01", "customer_email": "c@old.com"},
        {"page_id": "a4", "customer_name": "Warm Lead", "status": "Not Started",
         "current_phase": None, "sales_rep": "Trent", "start_date": None,
         "target_go_live_date": None, "customer_email": "d@warm.com"},
        {"page_id": "a5", "customer_name": "Almost There", "status": "Ready to Go Live",
         "current_phase": "Phase 7", "sales_rep": "Martin", "start_date": "2026-05-20",
         "target_go_live_date": "2026-06-05", "customer_email": "e@almost.com"},
    ],
}


def _write_fixture(data: dict) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(data, f)
    f.close()
    return f.name


def test_load_onboarding_active_filters_to_active_statuses():
    path = _write_fixture(FIXTURE_CACHE)
    result = load_onboarding_active(path, ACTIVE)
    assert len(result) == 3
    names = {r["customer_name"] for r in result}
    assert names == {"Acme Strength", "Peak Perf", "Almost There"}


def test_load_onboarding_active_excludes_live_and_not_started():
    path = _write_fixture(FIXTURE_CACHE)
    result = load_onboarding_active(path, ACTIVE)
    statuses = {r["status"] for r in result}
    assert "Live" not in statuses
    assert "Not Started" not in statuses


def test_load_onboarding_active_returns_empty_on_missing_file():
    result = load_onboarding_active("/nonexistent/path.json", ACTIVE)
    assert result == []


def test_load_onboarding_active_returns_empty_on_corrupt_json():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    f.write("not json {{{")
    f.close()
    result = load_onboarding_active(f.name, ACTIVE)
    assert result == []


def test_load_onboarding_active_handles_empty_records():
    path = _write_fixture({"synced_at": "2026-06-04T12:00:00Z", "records": []})
    result = load_onboarding_active(path, ACTIVE)
    assert result == []
```

- [ ] **Step 3.2: Run to verify it fails**

```
pytest tests/test_onboarding_collector.py -v
```
Expected: `ImportError: No module named 'collectors.onboarding'`

- [ ] **Step 3.3: Create `collectors/onboarding.py`**

```python
"""Onboarding cache reader — loads data/onboarding_cache.json and filters to active records."""

import json
from pathlib import Path


def load_onboarding_active(cache_path: str, active_statuses: list[str]) -> list[dict]:
    """Return onboarding records whose status is in active_statuses.

    Returns empty list if the cache is missing or unreadable (non-fatal).
    len(result) is the late-stage count for GTM metrics.
    """
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    status_set = set(active_statuses)
    return [r for r in data.get("records", []) if r.get("status") in status_set]
```

- [ ] **Step 3.4: Run to verify tests pass**

```
pytest tests/test_onboarding_collector.py -v
```
Expected: 5 tests PASS

- [ ] **Step 3.5: Run the full suite to confirm no regressions**

```
pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all prior tests still pass, 9 new tests added.

- [ ] **Step 3.6: Commit**

```bash
git add collectors/onboarding.py tests/test_onboarding_collector.py
git commit -m "feat: add load_onboarding_active() cache reader"
```

---

## Task 4: CronCreate nightly sync routine

No Python code — this is a Claude Code scheduled task. The routine fires nightly, uses the Notion MCP (session auth) to fetch the tracker, writes the cache, and commits. It does **not** use `NOTION_TOKEN` or the REST API.

**⚠️ 7-day expiry:** CronCreate routines auto-expire after 7 days regardless of `durable: true`. You must re-run this task weekly. Save the prompt below somewhere convenient to make re-setup fast.

**Files:**
- Runtime only — no file created

- [ ] **Step 4.1: Verify the full test suite passes before setting up the routine**

```
pytest tests/ --tb=short -q
```
Expected: all tests pass. Do not proceed if any fail.

- [ ] **Step 4.2: Push commits to remote**

```bash
git push
```

- [ ] **Step 4.3: Create the durable CronCreate routine**

In Claude Code, run the CronCreate tool with these exact parameters:

```
cron: "47 20 * * *"
durable: true
recurring: true
prompt: |
  Sync the Notion Onboarding Tracker to data/onboarding_cache.json in
  /Users/trentluecke/dev/Claude-Projects/chief-of-staff.

  Steps:
  1. Use the Notion MCP to search or fetch the OS Customer Onboarding Tracker
     database (data source ID: d4904af6-77b0-4507-8655-353ae4eadbd2). Retrieve
     all records — paginate if needed.
  2. For each record extract: page_id (the UUID from the page URL), customer_name,
     customer_email, status, current_phase, sales_rep, start_date,
     target_go_live_date. Use null for missing/empty fields.
  3. Write /Users/trentluecke/dev/Claude-Projects/chief-of-staff/data/onboarding_cache.json:
     {"synced_at": "<current UTC ISO timestamp>Z", "records": [...]}
  4. Run in /Users/trentluecke/dev/Claude-Projects/chief-of-staff:
     git pull && git add data/onboarding_cache.json &&
     git commit -m "chore: sync onboarding cache [skip ci]" && git push
  5. Report: N records written, timestamp.
```

Fires at 8:47pm local time nightly. The off-:00 minute avoids API thundering-herd.

- [ ] **Step 4.4: Trigger a manual first run to verify**

Ask Claude Code to run the sync prompt manually once (copy the prompt from 4.3 and execute it). Verify:
- `data/onboarding_cache.json` is created with real records
- The commit appears in `git log --oneline -3`
- `python3 -c "import json; d=json.load(open('data/onboarding_cache.json')); print(len(d['records']), 'records,', d['synced_at'])"` shows the correct count and a recent timestamp

---

## Canonical source update

After this plan executes, the late-stage count source for doc 1 is:

```python
import json
from collectors.onboarding import load_onboarding_active

cfg = json.load(open("config.json"))
active = load_onboarding_active(
    cfg["onboarding"]["cache_path"],
    cfg["onboarding"]["active_statuses"],
)
late_stage_count = len(active)  # the ≥5 breach input
```

`pipeline.late_stage_statuses` remains in config — it's not the late-stage velocity source anymore, but it may still be useful for Pipeline tracker views. Doc 1 will sort out which config key each breach function reads.
