# Accounts Dimension (Phase 1A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a synced `accounts` dimension in the OS-Metric-Sync store — one row per active OS account with its `Join Date` (go-live) — sourced one-way from the Client List Google Sheet, following the repo's existing fetch→ingest→db pattern.

**Architecture:** A new `fetch_accounts.py` reads the Active Customers tab (reusing `fetch_mrr.py`'s tab detection and header-name matching), writes `accounts_data.json`; a new `ingest_accounts()` upserts it into a new `accounts` table in `dashboard.db`; both are wired into the existing `_run_refresh` / `_SYNC_SOURCES` orchestration and a `/api/refresh/accounts` endpoint. This is the account dimension the fan-out ingest and 60-day onboarding flag (Phase 2+) build on.

**Tech Stack:** Python 3, FastAPI, sqlite3, pytest, Google Sheets API (service account, read-only).

## Global Constraints

- **Target repository:** `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync` (all paths below are relative to it). The design spec lives in the chief-of-staff repo at `docs/superpowers/specs/2026-09-04-account-health-metrics-rework-design.md`.
- **Follow the established pattern verbatim:** `fetch_*.py` → `*_data.json` → `dashboard/ingest.py::ingest_*` → `dashboard.db`. Schema via `dashboard/db.py::init_db` using `CREATE TABLE IF NOT EXISTS`. Upserts via `INSERT ... ON CONFLICT`.
- **Natural key:** `account_name`. The sync is **one-way (Sheet wins), upsert-only — it never deletes** rows.
- **Sheet contract (do not break):** the Active Customers tab is located by the `"Price Point"` header (via `fetch_mrr.detect_active_tab`); columns are matched by header **name**, not position. Confirmed live headers include `Account Name`, `Join Date`, `Status`, `Price Point`.
- **Run tests:** `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest <path> -v`
- **Onboarding-window derivation (60 days from Join Date) is NOT in this plan** — it is computed at query time downstream (Phase 2+). This plan only lands the raw `join_date`.

---

### Task 1: `accounts` table in the store schema

**Files:**
- Modify: `dashboard/db.py` (inside `init_db`, the `executescript` block)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `dashboard.db.get_conn`, `dashboard.db.init_db` (existing).
- Produces: an `accounts` table with columns `account_name` (TEXT PRIMARY KEY), `join_date` (TEXT), `status` (TEXT), `updated_at` (TEXT).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_accounts_table_exists_with_expected_columns(db_path):
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    conn.close()
    assert cols == {"account_name", "join_date", "status", "updated_at"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_db.py::test_accounts_table_exists_with_expected_columns -v`
Expected: FAIL — `accounts` table does not exist (empty `PRAGMA table_info` → cols == set()).

- [ ] **Step 3: Write minimal implementation**

In `dashboard/db.py`, inside the `conn.executescript("""...""")` block, add this table definition (e.g. after the `bugs` table, before `scrape_log`):

```sql
        CREATE TABLE IF NOT EXISTS accounts (
            account_name TEXT PRIMARY KEY,
            join_date TEXT,
            status TEXT,
            updated_at TEXT
        );
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_db.py -v`
Expected: PASS (all existing db tests still pass; new one passes).

- [ ] **Step 5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add dashboard/db.py tests/test_db.py
git commit -m "feat: add accounts dimension table to store schema"
```

---

### Task 2: `fetch_accounts.py` — read Active Customers tab

**Files:**
- Create: `fetch_accounts.py`
- Test: `tests/test_fetch_accounts.py`

**Interfaces:**
- Consumes (imported from `fetch_mrr`): `SPREADSHEET_ID`, `detect_active_tab`, `_read_tab_headers`, `_svc_or_default`.
- Produces: `build_accounts_payload(header: list[str], rows: list[list[str]]) -> dict` returning `{"accounts": [{"account_name": str, "status": str, "join_date": str}], "count": int}`; and `fetch_accounts_payload(svc=None) -> dict` (same shape plus `"fetched_at"`). `main()` writes `accounts_data.json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fetch_accounts.py`:

```python
import pytest
from unittest.mock import MagicMock
import fetch_accounts

HEADER = ["Account Name", "Join Date", "POC", "Email", "Phone", "Status", "Price Point", "Length of Engagement"]


def test_build_payload_extracts_name_status_join_date():
    rows = [
        ["410 Fitness", "11/20/2025", "A", "a@x.com", "1", "Active", "200", "6"],
        ["Buan", "12/4/2025", "B", "b@x.com", "", "Active", "150", "17"],
    ]
    payload = fetch_accounts.build_accounts_payload(HEADER, rows)
    assert payload["count"] == 2
    assert payload["accounts"] == [
        {"account_name": "410 Fitness", "status": "Active", "join_date": "11/20/2025"},
        {"account_name": "Buan", "status": "Active", "join_date": "12/4/2025"},
    ]


def test_build_payload_skips_blank_account_name():
    rows = [
        ["410 Fitness", "11/20/2025", "", "", "", "Active", "200", ""],
        ["", "1/1/2026", "", "", "", "Active", "300", ""],  # no name -> skipped
    ]
    payload = fetch_accounts.build_accounts_payload(HEADER, rows)
    assert payload["count"] == 1
    assert payload["accounts"][0]["account_name"] == "410 Fitness"


def test_build_payload_handles_short_rows():
    rows = [["410 Fitness", "11/20/2025", "", "", "", "Active"]]  # trailing cols missing
    payload = fetch_accounts.build_accounts_payload(HEADER, rows)
    assert payload["accounts"][0]["join_date"] == "11/20/2025"
    assert payload["accounts"][0]["status"] == "Active"


def _make_svc(tabs, header_row, data_rows):
    svc = MagicMock()
    svc.spreadsheets().get(
        spreadsheetId=fetch_accounts.SPREADSHEET_ID, fields="sheets.properties"
    ).execute.return_value = {"sheets": [{"properties": {"title": t}} for t in tabs]}
    header_response = {"values": [header_row]}
    data_response = {"values": data_rows}

    def values_get_side_effect(spreadsheetId, range):  # noqa: A002
        mock = MagicMock()
        mock.execute.return_value = header_response if range.endswith("!1:1") else data_response
        return mock

    svc.spreadsheets().values().get.side_effect = values_get_side_effect
    return svc


def test_fetch_payload_stamps_fetched_at():
    svc = _make_svc(
        ["Active Customers"],
        ["Account Name", "Join Date", "Status", "Price Point"],
        [["Gym Alpha", "1/2/2026", "Active", "500"]],
    )
    payload = fetch_accounts.fetch_accounts_payload(svc=svc)
    assert payload["count"] == 1
    assert payload["accounts"][0]["account_name"] == "Gym Alpha"
    assert payload["fetched_at"] != ""


def test_fetch_payload_raises_when_join_date_column_absent():
    svc = _make_svc(
        ["Active Customers"],
        ["Account Name", "Status", "Price Point"],  # no Join Date
        [["Gym Alpha", "Active", "500"]],
    )
    with pytest.raises(RuntimeError, match="Join Date"):
        fetch_accounts.fetch_accounts_payload(svc=svc)


def test_fetch_payload_raises_when_no_price_point_tab():
    svc = _make_svc(["Sheet1"], ["Account Name", "Join Date", "Status"], [])
    with pytest.raises(RuntimeError, match="Price Point"):
        fetch_accounts.fetch_accounts_payload(svc=svc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_fetch_accounts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fetch_accounts'`.

- [ ] **Step 3: Write minimal implementation**

Create `fetch_accounts.py`:

```python
#!/usr/bin/env python3
"""
Accounts Fetcher
Reads the Active Customers tab of the Client List spreadsheet and writes
accounts_data.json — one record per active account with its Join Date —
for the account-health dimension in dashboard.db.

Reuses fetch_mrr's tab detection: the Active Customers tab is located by
the presence of a "Price Point" header, and columns are matched by header
NAME (not position), so reordering columns is safe.

Usage: python3 fetch_accounts.py
"""

import json
from datetime import datetime
from pathlib import Path

from fetch_mrr import (
    SPREADSHEET_ID,
    detect_active_tab,
    _read_tab_headers,
    _svc_or_default,
)

OUTPUT_FILE = Path(__file__).parent / "accounts_data.json"

ACCOUNT_COL = "Account Name"
STATUS_COL = "Status"
JOIN_DATE_COL = "Join Date"


def build_accounts_payload(header: list[str], rows: list[list[str]]) -> dict:
    """One record per row with a non-blank account name."""
    name_idx = header.index(ACCOUNT_COL)
    status_idx = header.index(STATUS_COL)
    join_idx = header.index(JOIN_DATE_COL)
    width = max(name_idx, status_idx, join_idx) + 1

    accounts = []
    for row in rows:
        row = row + [""] * (width - len(row))
        name = row[name_idx].strip()
        if not name:
            continue
        accounts.append({
            "account_name": name,
            "status": row[status_idx].strip(),
            "join_date": row[join_idx].strip(),
        })
    return {"accounts": accounts, "count": len(accounts)}


def fetch_accounts_payload(svc=None) -> dict:
    svc = _svc_or_default(svc)
    tab_headers = _read_tab_headers(svc)
    tab = detect_active_tab(tab_headers)
    if tab is None:
        raise RuntimeError("No tab with a 'Price Point' column found in Client List")
    header = tab_headers[tab]
    if JOIN_DATE_COL not in header:
        raise RuntimeError(f"'{JOIN_DATE_COL}' column not found on tab '{tab}'")
    result = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!2:100000",
    ).execute(num_retries=6)
    rows = result.get("values", [])
    payload = build_accounts_payload(header, rows)
    payload["fetched_at"] = datetime.utcnow().isoformat() + "Z"
    return payload


def main():
    payload = fetch_accounts_payload()
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2))
    print(f"Accounts: {payload['count']}  ->  accounts_data.json")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_fetch_accounts.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add fetch_accounts.py tests/test_fetch_accounts.py
git commit -m "feat: fetch_accounts reads Active Customers tab into accounts_data.json"
```

---

### Task 3: `ingest_accounts()` — upsert into the store

**Files:**
- Modify: `dashboard/ingest.py`
- Test: `tests/test_ingest_accounts.py`

**Interfaces:**
- Consumes: `dashboard.db.get_conn`; `accounts_data.json` shape `{"accounts": [{"account_name", "join_date", "status"}]}` (from Task 2); the `accounts` table (from Task 1).
- Produces: `ingest_accounts(db_path, json_path) -> int` (count upserted). Upsert key `account_name`; on conflict updates `join_date`, `status`, `updated_at`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest_accounts.py`:

```python
import json
from dashboard.db import get_conn
from dashboard.ingest import ingest_accounts


def _write(tmp_path, payload):
    p = tmp_path / "accounts_data.json"
    p.write_text(json.dumps(payload))
    return str(p)


def test_ingest_inserts_accounts(db_path, tmp_path):
    path = _write(tmp_path, {"accounts": [
        {"account_name": "410 Fitness", "join_date": "11/20/2025", "status": "Active"},
        {"account_name": "Buan", "join_date": "12/4/2025", "status": "Active"},
    ]})
    assert ingest_accounts(db_path, path) == 2
    conn = get_conn(db_path)
    rows = {r["account_name"]: r for r in conn.execute(
        "SELECT account_name, join_date, status FROM accounts").fetchall()}
    conn.close()
    assert rows["410 Fitness"]["join_date"] == "11/20/2025"
    assert rows["Buan"]["status"] == "Active"


def test_ingest_upserts_in_place_by_account_name(db_path, tmp_path):
    ingest_accounts(db_path, _write(tmp_path, {"accounts": [
        {"account_name": "410 Fitness", "join_date": "11/20/2025", "status": "Active"},
    ]}))
    # Same account, corrected join date -> update, not duplicate.
    ingest_accounts(db_path, _write(tmp_path, {"accounts": [
        {"account_name": "410 Fitness", "join_date": "11/21/2025", "status": "Active"},
    ]}))
    conn = get_conn(db_path)
    rows = conn.execute("SELECT join_date FROM accounts WHERE account_name='410 Fitness'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["join_date"] == "11/21/2025"


def test_ingest_skips_blank_account_name(db_path, tmp_path):
    path = _write(tmp_path, {"accounts": [
        {"account_name": "", "join_date": "1/1/2026", "status": "Active"},
        {"account_name": "Real Gym", "join_date": "1/2/2026", "status": "Active"},
    ]})
    assert ingest_accounts(db_path, path) == 1
    conn = get_conn(db_path)
    names = [r["account_name"] for r in conn.execute("SELECT account_name FROM accounts").fetchall()]
    conn.close()
    assert names == ["Real Gym"]


def test_ingest_sets_updated_at(db_path, tmp_path):
    path = _write(tmp_path, {"accounts": [
        {"account_name": "Real Gym", "join_date": "1/2/2026", "status": "Active"},
    ]})
    ingest_accounts(db_path, path)
    conn = get_conn(db_path)
    updated = conn.execute("SELECT updated_at FROM accounts WHERE account_name='Real Gym'").fetchone()["updated_at"]
    conn.close()
    assert updated  # non-empty ISO timestamp
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_ingest_accounts.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_accounts'`.

- [ ] **Step 3: Write minimal implementation**

Append to `dashboard/ingest.py` (module already imports `json`, `Path`, and `datetime`):

```python
def ingest_accounts(db_path, json_path):
    """Upsert the accounts dimension from JSON. Sheet is source of truth;
    upsert-only, never deletes. Returns count upserted."""
    data = json.loads(Path(json_path).read_text())
    accounts = data.get("accounts", [])
    conn = get_conn(db_path)
    updated_at = datetime.utcnow().isoformat()
    rows = 0
    for a in accounts:
        name = (a.get("account_name") or "").strip()
        if not name:
            continue
        conn.execute(
            "INSERT INTO accounts (account_name, join_date, status, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(account_name) DO UPDATE SET "
            "join_date=excluded.join_date, status=excluded.status, updated_at=excluded.updated_at",
            (name, a.get("join_date") or None, a.get("status") or None, updated_at),
        )
        rows += 1
    conn.commit()
    conn.close()
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_ingest_accounts.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add dashboard/ingest.py tests/test_ingest_accounts.py
git commit -m "feat: ingest_accounts upserts accounts dimension into store"
```

---

### Task 4: Wire accounts into refresh orchestration

**Files:**
- Modify: `dashboard/main.py` (ingest import line ~18; add endpoint near `refresh_arr` ~373; `_SYNC_SOURCES` list ~712)
- Test: `tests/test_api.py` (update the three sync-all source-set assertions; add an endpoint-registration test)

**Interfaces:**
- Consumes: `ingest_accounts` (Task 3), `_run_refresh`, `_SYNC_SOURCES` (existing).
- Produces: `POST /api/refresh/accounts`; `"accounts"` registered as a `_SYNC_SOURCES` entry `("accounts", "fetch_accounts.py", ingest_accounts, "accounts_data.json")`, so `/api/sync-all` reports it.

- [ ] **Step 1: Update the failing tests**

In `tests/test_api.py`, the three tests currently assert the source set is `{"revenue", "retention", "bugs", "arr"}`. Update each to include `"accounts"`:

```python
# test_sync_all_reports_each_source:
    assert set(sources) == {"revenue", "retention", "bugs", "arr", "accounts"}

# test_sync_all_no_pipeline_demos_fetch:
    assert sources == {"revenue", "retention", "bugs", "arr", "accounts"}
```

(`test_sync_all_all_ok` asserts `all(status == "ok")` and needs no set change — the stubbed `_run_refresh` returns ok for every source including the new one.)

Add a new test to `tests/test_api.py`:

```python
def test_refresh_accounts_endpoint_runs_accounts_source(client, monkeypatch):
    captured = {}

    def fake_refresh(scraper, fetch_script, ingest_fn, json_filename):
        captured["args"] = (scraper, fetch_script, json_filename)
        return {"status": "ok", "rows_affected": 5, "fetch_output": ""}

    monkeypatch.setattr(main_mod, "_run_refresh", fake_refresh)
    resp = client.post("/api/refresh/accounts")
    assert resp.status_code == 200
    assert captured["args"] == ("accounts", "fetch_accounts.py", "accounts_data.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_api.py -k "sync_all or refresh_accounts" -v`
Expected: FAIL — `test_sync_all_reports_each_source` / `..._no_pipeline_demos_fetch` fail on the set assertion; `test_refresh_accounts_endpoint...` returns 404 (endpoint not defined).

- [ ] **Step 3: Write minimal implementation**

In `dashboard/main.py`:

1. Add `ingest_accounts` to the ingest import (around line 18):

```python
from dashboard.ingest import (
    ingest_sales, ingest_demos, ingest_cancellations,
    ingest_onboarding, ingest_bugs, ingest_mrr, ingest_accounts,
)
```
(Match the existing import statement's exact form — add `ingest_accounts` to the imported names.)

2. Add the endpoint next to `refresh_arr` (around line 373):

```python
@app.post("/api/refresh/accounts")
def refresh_accounts():
    return _run_refresh("accounts", "fetch_accounts.py", ingest_accounts, "accounts_data.json")
```

3. Add the source to `_SYNC_SOURCES` (around line 712):

```python
    ("accounts", "fetch_accounts.py", ingest_accounts, "accounts_data.json"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_api.py -v`
Expected: PASS (updated sync-all tests + new endpoint test + all others).

- [ ] **Step 5: Run the full suite**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest -q`
Expected: PASS (no regressions across the repo).

- [ ] **Step 6: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add dashboard/main.py tests/test_api.py
git commit -m "feat: wire accounts source into refresh orchestration + /api/refresh/accounts"
```

---

### Task 5: Live smoke test (manual, gated on credentials)

**Files:** none (operational verification).

This is the one place the Sheet contract meets reality (spec open-item #1). Run only where `GOOGLE_SERVICE_ACCOUNT_JSON` is set and the service account can read the Client List sheet.

- [ ] **Step 1: Fetch for real**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 fetch_accounts.py`
Expected: prints `Accounts: <N>  ->  accounts_data.json`; `accounts_data.json` exists with a non-empty `accounts` array; spot-check a few `join_date` values are populated (not blank). If it raises `'Join Date' column not found`, the live header differs from the assumed name — reconcile the header string before proceeding.

- [ ] **Step 2: Ingest for real**

Run:
```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -c "
from dashboard.db import init_db
from dashboard.ingest import ingest_accounts
init_db('dashboard.db')
print('upserted', ingest_accounts('dashboard.db', 'accounts_data.json'))
"
```
Expected: `upserted <N>` matching the fetch count. Spot-check: `sqlite3 dashboard.db "SELECT count(*), count(join_date) FROM accounts"` shows most rows carry a `join_date`.

- [ ] **Step 3: Note results** in the PR description (row count, any accounts missing a Join Date) so the downstream 60-day flag knows its coverage.

---

## Deferred to Phase 1B (separate plan) — the Notion capture layer

**Not in this plan**, because it hinges on a transport decision and involves Notion structural config rather than TDD code. Surfaced here so it isn't lost:

1. **Bug Tracker structural changes** (executed directly via Notion MCP, one-time): create the `Affected/Reported Accounts` **relation** property; add the **"Not actually a bug"** option to `Priority Level`; bake `Shortcut URL` + `Date Completed` + Accounts into the **Bug Ticket Template**.
2. **A new canonical Accounts database in Notion** — the relation target for `Affected/Reported Accounts`.
3. **Sheet → Notion Accounts DB mirror** — keeps the dropdown current from the Sheet. **Open decision (blocking 1B):** OS-Metric-Sync has *no* working Notion-write path today (`notion_sync.py` is a Gmail summarizer; `fetch_bugs.py`'s `NOTION_TOKEN` isn't reliably available). Two transports:
   - **(a) Provision a Notion internal-integration token** for OS-Metric-Sync, share the Accounts DB with it, upsert via the Notion REST API (robust, fully automatable; one-time setup). **Recommended.**
   - **(b) A Claude Code scheduled MCP task** (mirrors the existing `fetch-bugs` MCP path; no token, but depends on a scheduled Claude run).

Phase 1A (this plan) has **zero dependency** on that decision and fully unblocks Phase 2 (bug fan-out + 60-day flag), so it's safe to build first.

---

## Self-Review

**Spec coverage (Phase 1 scope):**
- Accounts dimension synced from the Sheet with go-live (`Join Date`) → Tasks 1–3, 5. ✅
- One-way, Sheet-wins, upsert-only → Task 3 (ON CONFLICT, no deletes) + constraint. ✅
- Wired into the store's refresh orchestration → Task 4. ✅
- Bug Tracker field enhancements + Notion Accounts DB + mirror → explicitly deferred to Phase 1B with the transport fork surfaced. ✅ (scoped out, not dropped)

**Placeholder scan:** No TBD/TODO; every code and test step shows complete content. ✅

**Type consistency:** `build_accounts_payload` / `fetch_accounts_payload` return `{"accounts": [{"account_name","status","join_date"}], "count", "fetched_at"}`; `ingest_accounts` reads exactly those keys; `accounts` table columns (`account_name, join_date, status, updated_at`) match the ingest INSERT and the Task 1 test. `_SYNC_SOURCES` tuple shape `(scraper, fetch_script, ingest_fn, json_filename)` matches the existing four entries and the Task 4 endpoint test. ✅
