# Account Health — Historical Baseline (Phase 2C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement Tasks 1–4 (TDD). Task 5 is an MCP-driven runbook/skill — execute it as a checklist and validate manually. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A one-time, read-only import that seeds the OS-Metric-Sync store with a *clean* slice of the old Account Health Metrics Notion history — only rows that normalize to a currently-active account — so the CSM surface opens with real per-account history. The old Notion DB(s) are never written, archived, or retired.

**Architecture:** Additive to the live 2A/2B store. History becomes synthetic `bugs` rows carrying a new `source='history'` flag (keyed by Shortcut story id), fanned into `ticket_accounts`. Source-aware reads keep history OUT of the live bug backlog / bug stats / Panel-2 recurrence (no Technical Area to cluster on) while the account list, drill-down, and onboarding counts include it. An MCP-driven runbook fetches + normalizes + matches the old rows into a committed `history_health_data.json` plus a human `history_import_report.md`; delivery to Railway's volume DB mirrors the existing bug ingest (committed JSON → deploy → `POST /api/refresh/history`).

**Tech Stack:** Python 3, FastAPI, sqlite3, pytest. Old-DB reads via the Notion MCP (no `NOTION_TOKEN` on Railway — same constraint as `fetch-bugs`).

## Global Constraints

- **Target repo:** `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync` (all paths relative). Spec: chief-of-staff `docs/superpowers/specs/2026-09-09-account-health-historical-baseline-phase2c.md`.
- **Prereqs merged & live (do NOT rebuild):** 2A data spine (`bugs` +`date_completed`+`tags`, `ticket_accounts` PK `(bug_id, account_name)` +`resolved_for_customer_date`, `accounts` PK `account_name`+`join_date` M/D/YYYY, `dashboard/account_health.py` with `_parse_join_date`/`_parse_iso`/`ONBOARDING_WINDOW_DAYS`, `compute_account_health`, `account_ticket_history`, `compute_bug_recurrence`), and 2B (`GET /api/account-health`, `/api/account-tickets`, `/api/bug-recurrence`, `PATCH /api/ticket-accounts/{bug_id}`, role-aware auth, `dashboard/static/account-health.html`).
- **Additive only.** Existing endpoints/tests must keep passing. The `bugs.source` column is nullable and backfills as `'notion'` via `COALESCE(source,'notion')` — existing rows are unaffected.
- **History exclusion rule (exact):** a bug is "history" iff `COALESCE(source,'notion') = 'history'`. History is EXCLUDED from `GET /api/bugs` (+ its stats, which `/api/metrics/snapshot` reuses) and `compute_bug_recurrence`. History is INCLUDED in `compute_account_health` and `account_ticket_history` (they join `ticket_accounts`→`bugs` regardless of source).
- **Identity/dedup key:** Shortcut story id → synthetic bug id `sc-<storyid>`. A row with no usable Shortcut story id is skipped by the runbook, never given a synthetic id.
- **Date mapping:** old `Date Ticket Closed` → BOTH `bugs.date_completed` AND `ticket_accounts.resolved_for_customer_date` (it was the per-account fixed date). `Date Created` → `bugs.created_at`. Reuse `_parse_iso`; unparseable → NULL.
- **Add-only ingest:** `ticket_accounts` fan-out uses `ON CONFLICT(bug_id, account_name) DO NOTHING` — never clobbers a CSM-set resolved date, safe to re-run, dedups the old DB's duplicate rows.
- **Old Notion DB(s):** read-only. No task writes to them.
- **Run tests:** `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest <path> -v`

## File Structure

- `dashboard/db.py` — **modify.** Add nullable `bugs.source` column (idempotent migration).
- `dashboard/main.py` — **modify.** `get_bugs` filters to non-history; add `POST /api/refresh/history`.
- `dashboard/account_health.py` — **modify.** `compute_bug_recurrence` filters to non-history. (`compute_account_health`/`account_ticket_history` unchanged.)
- `dashboard/history_import.py` — **create.** Pure name-normalize / alias / match / Frankenstein-split logic + the seeded alias map.
- `dashboard/ingest.py` — **modify.** Add `ingest_historical(db_path, json_path) -> int`.
- `tests/test_history_source.py`, `tests/test_history_import.py`, `tests/test_ingest_historical.py`, `tests/test_api.py` — **create/modify.**
- `/Users/trentluecke/.claude/skills/import-account-health-history/SKILL.md` — **create** (Task 5, the MCP runbook).

---

### Task 1: `bugs.source` column + source-aware reads

**Files:**
- Modify: `dashboard/db.py` (`init_db` migrations), `dashboard/main.py` (`get_bugs`), `dashboard/account_health.py` (`compute_bug_recurrence`)
- Test: `tests/test_history_source.py` (create)

**Interfaces:**
- Produces: nullable `bugs.source TEXT`. `get_bugs` and `compute_bug_recurrence` return only `COALESCE(source,'notion')='notion'` rows; `compute_account_health` still returns all.

- [ ] **Step 1: Write the failing tests** — create `tests/test_history_source.py`:

```python
import importlib
import pytest
from fastapi.testclient import TestClient
from dashboard.db import get_conn
import dashboard.main as main_mod


def _seed(db_path):
    conn = get_conn(db_path)
    conn.execute("INSERT INTO accounts (account_name, join_date, status, updated_at) "
                 "VALUES ('Buan', '6/1/2026', 'Active', 'x')")
    # a live (notion) bug and a history bug, both tagged to Buan, both with a Scheduling area
    conn.execute("INSERT INTO bugs (id, title, status, priority, tags, created_at, updated_at, url, date_completed, source) "
                 "VALUES ('n1', 'Live bug', 'Done', 'High', '[\"Kiosk\"]', '2026-06-10T00:00:00Z', 'u', 'u', '2026-06-12', 'notion')")
    conn.execute("INSERT INTO bugs (id, title, status, priority, tags, created_at, updated_at, url, date_completed, source) "
                 "VALUES ('sc-999', 'History bug', 'Done', 'Low', '[]', '2026-06-05T00:00:00Z', 'u', 'u', '2026-06-09', 'history')")
    for bid in ('n1', 'sc-999'):
        conn.execute("INSERT INTO ticket_accounts (bug_id, account_name, resolved_for_customer_date) VALUES (?, 'Buan', NULL)", (bid,))
    conn.commit(); conn.close()


def test_db_has_source_column(db_path):
    conn = get_conn(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bugs)").fetchall()}
    conn.close()
    assert "source" in cols


def test_get_bugs_excludes_history(db_path, tmp_path, monkeypatch):
    _seed(db_path)
    importlib.reload(main_mod)
    monkeypatch.setattr("dashboard.main.DB_PATH", db_path)
    client = TestClient(main_mod.app)
    ids = [b["id"] for b in client.get("/api/bugs").json()["bugs"]]
    assert "n1" in ids and "sc-999" not in ids


def test_recurrence_excludes_history_health_includes_it(db_path):
    from datetime import date
    _seed(db_path)
    conn = get_conn(db_path)
    from dashboard.account_health import compute_bug_recurrence, compute_account_health
    rec_areas = {r["area"] for r in compute_bug_recurrence(conn, today=date(2026, 6, 20))["all"]}
    health = {a["account_name"]: a for a in compute_account_health(conn, today=date(2026, 6, 20))}
    conn.close()
    assert "Kiosk" in rec_areas and "Uncategorized" not in rec_areas   # history's empty-tags bug excluded
    assert health["Buan"]["ticket_count"] == 2                          # BOTH count toward health
```

- [ ] **Step 2: Run — expect FAIL** (no `source` column): `python3 -m pytest tests/test_history_source.py -v`

- [ ] **Step 3: Implement.**

In `dashboard/db.py`, in the migrations section (next to the `date_completed` guard added in 2A), add:

```python
    bug_cols = {r[1] for r in conn.execute("PRAGMA table_info(bugs)").fetchall()}
    if "source" not in bug_cols:
        conn.execute("ALTER TABLE bugs ADD COLUMN source TEXT")
```

In `dashboard/main.py`, `get_bugs` — add a WHERE to the query:

```python
    rows = conn.execute("""
        SELECT * FROM bugs
        WHERE COALESCE(source,'notion') = 'notion'
        ORDER BY
            CASE priority WHEN 'High' THEN 1 WHEN 'Moderate' THEN 2 WHEN 'Low' THEN 3 ELSE 4 END,
            updated_at DESC
    """).fetchall()
```

In `dashboard/account_health.py`, `compute_bug_recurrence` — add the filter to its SQL `FROM` block:

```python
        FROM ticket_accounts ta
        JOIN bugs b ON b.id = ta.bug_id
        LEFT JOIN accounts a ON a.account_name = ta.account_name
        WHERE COALESCE(b.source,'notion') = 'notion'
```

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_history_source.py -v`, then the full suite (confirm `test_db.py` table/column assertions and existing bug/recurrence tests still pass).

- [ ] **Step 5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add dashboard/db.py dashboard/main.py dashboard/account_health.py tests/test_history_source.py
git commit -m "feat: bugs.source flag — history excluded from backlog + recurrence, included in health"
```

---

### Task 2: Name normalize / alias / match / Frankenstein-split (pure logic)

**Files:**
- Create: `dashboard/history_import.py`
- Test: `tests/test_history_import.py`

**Interfaces:**
- Produces:
  - `normalize_name(s: str) -> str` — lowercase; strip a trailing parenthetical id (e.g. `(1018)`, `(21)`); drop `.`; collapse internal/edge whitespace.
  - `ALIASES: dict[str, str]` — normalized-raw → canonical account name (seeded from observed mismatches).
  - `DEMO_TOKENS: set[str]` — normalized names that are internal/demo/junk.
  - `resolve_accounts(raw: str, active_by_norm: dict[str, str]) -> dict` → `{"matched": [canonical...], "unmatched": [raw_part...], "reason": str|None}`. Splits `raw` on commas (Frankenstein); each part: demo/blank → unmatched w/ reason `"demo_or_blank"`; else normalize→ALIASES or →active_by_norm → canonical; else unmatched w/ reason `"unknown_account"`. `active_by_norm` maps `normalize_name(canonical)` → canonical.

- [ ] **Step 1: Write the failing tests** — create `tests/test_history_import.py`:

```python
from dashboard.history_import import normalize_name, resolve_accounts, ALIASES


def test_normalize_strips_id_paren_and_case_and_period():
    assert normalize_name("Columbus Sports Performance Center (1018)") == "columbus sports performance center"
    assert normalize_name("Built. Strength and Conditioning") == "built strength and conditioning"
    assert normalize_name("  ZenithX  ") == "zenithx"


def _active():
    # normalize_name(canonical) -> canonical
    return {normalize_name(c): c for c in [
        "Zenith X", "Alpine Performance Labs is not active — omit",  # placeholder not used
        "BUILT. Strength and Conditioning", "Talented Tenth Athletics", "Youthlete Academy",
    ] if "omit" not in c}


def test_alias_maps_zenithx_to_canonical():
    active = {normalize_name("Zenith X"): "Zenith X"}
    out = resolve_accounts("ZenithX", active)
    assert out["matched"] == ["Zenith X"] and out["unmatched"] == []


def test_exact_normalized_match():
    active = {normalize_name("Youthlete Academy"): "Youthlete Academy"}
    out = resolve_accounts("Youthlete Academy", active)
    assert out["matched"] == ["Youthlete Academy"]


def test_frankenstein_split_one_matches_one_reported():
    active = {normalize_name("Zenith X"): "Zenith X"}   # Alpine not active
    out = resolve_accounts("ZenithX, Alpine Performance Labs", active)
    assert out["matched"] == ["Zenith X"]
    assert out["unmatched"] == ["Alpine Performance Labs"]


def test_demo_and_blank_are_skipped():
    active = {normalize_name("Youthlete Academy"): "Youthlete Academy"}
    assert resolve_accounts("Demo", active)["reason"] == "demo_or_blank"
    assert resolve_accounts("", active)["reason"] == "demo_or_blank"


def test_unknown_account_reason():
    active = {normalize_name("Youthlete Academy"): "Youthlete Academy"}
    out = resolve_accounts("Some Churned Gym", active)
    assert out["matched"] == [] and out["reason"] == "unknown_account"
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: dashboard.history_import`).

- [ ] **Step 3: Implement** — create `dashboard/history_import.py`:

```python
# dashboard/history_import.py
"""Pure matching logic for the one-time Account Health history import (Phase 2C).
Maps free-text old-DB `Account` names to canonical active account names."""
import re

# Normalized-raw -> canonical account name. Seeded from mismatches observed in the
# old DB on 2026-09-09; extend as the import report surfaces more.
ALIASES = {
    "zenithx": "Zenith X",
    "built strength and conditioning": "BUILT. Strength and Conditioning",
    "excessafit": "Excessafit",
    "henny jurriens": "Henny Jurriens Studio",
    "st marys turkeys": "St. Mary's Turkeys",
    "txt (talented tenth athletics)": "Talented Tenth Athletics",
    "talented tenth athletics": "Talented Tenth Athletics",
    "the gym in the armoury": "The Gym In the Armoury",
    "new era coaching": "New Era Coaching Ltd",
    "new era coaching ltd": "New Era Coaching Ltd",
}

# Internal / non-customer account cells that must never import.
DEMO_TOKENS = {"demo", "staging", "os demo", "os demo (1)", "test"}

_ID_PAREN = re.compile(r"\s*\(\s*[^)]*\d[^)]*\)\s*$")   # trailing "(1018)", "(id: 174)", "(21)"


def normalize_name(s):
    if not s:
        return ""
    s = s.strip()
    s = _ID_PAREN.sub("", s)          # drop a trailing parenthetical containing a digit
    s = s.replace(".", "")            # "Built." -> "Built"
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def resolve_accounts(raw, active_by_norm):
    """Split a free-text Account cell on commas and match each part to a canonical
    active account. Returns {"matched": [...], "unmatched": [...], "reason": str|None}.
    reason is set only when nothing matched."""
    matched, unmatched = [], []
    parts = [p.strip() for p in (raw or "").split(",")]
    parts = [p for p in parts if p != ""] or [""]   # keep a single blank to classify
    for part in parts:
        norm = normalize_name(part)
        if norm == "" or norm in DEMO_TOKENS:
            unmatched.append(part)
            continue
        canonical = ALIASES.get(norm) or active_by_norm.get(norm)
        if canonical:
            matched.append(canonical)
        else:
            unmatched.append(part)
    reason = None
    if not matched:
        only = normalize_name(parts[0])
        reason = "demo_or_blank" if (only == "" or only in DEMO_TOKENS) else "unknown_account"
    return {"matched": matched, "unmatched": unmatched, "reason": reason}
```

Note: the alias map maps to canonical names that must exist in the active `accounts` set at runbook time; an alias whose target has since churned simply won't match there and its rows report as `unknown_account` — acceptable.

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_history_import.py -v`

- [ ] **Step 5: Commit**

```bash
git add dashboard/history_import.py tests/test_history_import.py
git commit -m "feat: history-import name normalize/alias/match + Frankenstein split (pure)"
```

---

### Task 3: `ingest_historical` — synthetic history bugs + fan-out

**Files:**
- Modify: `dashboard/ingest.py`
- Test: `tests/test_ingest_historical.py`

**Interfaces:**
- Consumes `history_health_data.json`: `{"tickets": [{"story_id": str, "ticket_name": str, "priority": str|None, "created_at": str|None, "date_completed": str|None, "url": str, "accounts": [canonical_name, ...]}]}`.
- Produces: `ingest_historical(db_path, json_path) -> int` (count of `(bug × account)` pairs upserted). Upserts a `bugs` row per ticket with `id='sc-'+story_id`, `source='history'`, `status='Done'`, `tags='[]'`, `priority`, `created_at`, `date_completed`, `title`, `url`. Fans out `ticket_accounts` add-only with `resolved_for_customer_date = date_completed`. Skips tickets with a blank `story_id` or empty `accounts`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_ingest_historical.py`:

```python
import json
from dashboard.db import get_conn
from dashboard.ingest import ingest_historical


def _write(tmp_path, tickets):
    p = tmp_path / "history_health_data.json"
    p.write_text(json.dumps({"tickets": tickets}))
    return str(p)


def test_creates_history_bug_and_pair_with_resolved_date(db_path, tmp_path):
    path = _write(tmp_path, [{
        "story_id": "27933", "ticket_name": "Kiosk cancel modal", "priority": "Low",
        "created_at": "2026-08-05", "date_completed": "2026-08-10",
        "url": "https://app.shortcut.com/x/story/27933/y", "accounts": ["410 Fitness"],
    }])
    assert ingest_historical(db_path, path) == 1
    conn = get_conn(db_path)
    bug = conn.execute("SELECT id, source, status, date_completed FROM bugs WHERE id='sc-27933'").fetchone()
    ta = conn.execute("SELECT resolved_for_customer_date FROM ticket_accounts "
                      "WHERE bug_id='sc-27933' AND account_name='410 Fitness'").fetchone()
    conn.close()
    assert bug["source"] == "history" and bug["status"] == "Done" and bug["date_completed"] == "2026-08-10"
    assert ta["resolved_for_customer_date"] == "2026-08-10"


def test_multi_account_fan_out(db_path, tmp_path):
    path = _write(tmp_path, [{
        "story_id": "20763", "ticket_name": "combined", "priority": "High",
        "created_at": "2025-08-05", "date_completed": "2025-08-07", "url": "u",
        "accounts": ["Zenith X", "Alpine Performance Labs"],
    }])
    assert ingest_historical(db_path, path) == 2


def test_reingest_preserves_resolved_and_dedups(db_path, tmp_path):
    path = _write(tmp_path, [{
        "story_id": "27933", "ticket_name": "x", "priority": "Low",
        "created_at": "2026-08-05", "date_completed": "2026-08-10", "url": "u",
        "accounts": ["410 Fitness"],
    }])
    ingest_historical(db_path, path)
    conn = get_conn(db_path)
    conn.execute("UPDATE ticket_accounts SET resolved_for_customer_date='2026-08-06' "
                 "WHERE bug_id='sc-27933' AND account_name='410 Fitness'")
    conn.commit(); conn.close()
    assert ingest_historical(db_path, path) == 1   # re-run counts the attempt
    conn = get_conn(db_path)
    val = conn.execute("SELECT resolved_for_customer_date FROM ticket_accounts "
                       "WHERE bug_id='sc-27933'").fetchone()["resolved_for_customer_date"]
    n = conn.execute("SELECT COUNT(*) FROM ticket_accounts WHERE bug_id='sc-27933'").fetchone()[0]
    conn.close()
    assert val == "2026-08-06" and n == 1          # NOT clobbered, NOT duplicated


def test_skips_blank_story_id_and_empty_accounts(db_path, tmp_path):
    path = _write(tmp_path, [
        {"story_id": "", "ticket_name": "no id", "url": "u", "accounts": ["410 Fitness"]},
        {"story_id": "111", "ticket_name": "no accts", "url": "u", "accounts": []},
    ])
    assert ingest_historical(db_path, path) == 0
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError: ingest_historical`): `python3 -m pytest tests/test_ingest_historical.py -v`

- [ ] **Step 3: Implement** — append to `dashboard/ingest.py` (module already imports `json`, `Path`, `get_conn`):

```python
def ingest_historical(db_path, json_path):
    """One-time import of the old Account Health Metrics rows (Phase 2C).
    Each ticket -> a synthetic bugs row (id 'sc-<story_id>', source='history') +
    add-only ticket_accounts fan-out with resolved_for_customer_date = date_completed.
    Returns (bug x account) pairs upserted. Skips blank story_id / empty accounts."""
    data = json.loads(Path(json_path).read_text())
    tickets = data.get("tickets", [])
    conn = get_conn(db_path)
    pairs = 0
    for t in tickets:
        story_id = (t.get("story_id") or "").strip()
        accounts = [a for a in (t.get("accounts") or []) if (a or "").strip()]
        if not story_id or not accounts:
            continue
        bug_id = "sc-" + story_id
        conn.execute(
            "INSERT INTO bugs (id, title, status, priority, tags, created_at, updated_at, url, date_completed, source) "
            "VALUES (?, ?, 'Done', ?, '[]', ?, ?, ?, ?, 'history') "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, priority=excluded.priority, "
            "created_at=excluded.created_at, date_completed=excluded.date_completed, "
            "url=excluded.url, source='history'",
            (bug_id, t.get("ticket_name"), t.get("priority"), t.get("created_at"),
             t.get("created_at"), t.get("url"), t.get("date_completed")),
        )
        for name in accounts:
            conn.execute(
                "INSERT INTO ticket_accounts (bug_id, account_name, resolved_for_customer_date) "
                "VALUES (?, ?, ?) ON CONFLICT(bug_id, account_name) DO NOTHING",
                (bug_id, name.strip(), t.get("date_completed")),
            )
            pairs += 1
    conn.commit()
    conn.close()
    return pairs
```

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_ingest_historical.py -v`, then the full suite.

- [ ] **Step 5: Commit**

```bash
git add dashboard/ingest.py tests/test_ingest_historical.py
git commit -m "feat: ingest_historical — synthetic history bugs + add-only fan-out (resolved=closed date)"
```

---

### Task 4: `POST /api/refresh/history` delivery endpoint

**Files:**
- Modify: `dashboard/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `POST /api/refresh/history` → `_run_refresh("history", None, ingest_historical, "history_health_data.json")` → `{"status","rows_affected",...}`. Ingests the committed `history_health_data.json` into the volume DB (mirrors `refresh_bugs`). One-time; intentionally NOT added to `/api/sync-all`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_api.py`:

```python
def test_refresh_history_populates_account_health(client, db_path, tmp_path, monkeypatch):
    import json
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    conn.execute("INSERT INTO accounts (account_name, join_date, status, updated_at) "
                 "VALUES ('410 Fitness', '11/20/2025', 'Active', 'x')")
    conn.commit(); conn.close()
    hist = tmp_path / "history_health_data.json"
    hist.write_text(json.dumps({"tickets": [{
        "story_id": "27933", "ticket_name": "Kiosk", "priority": "Low",
        "created_at": "2026-08-05", "date_completed": "2026-08-10", "url": "u",
        "accounts": ["410 Fitness"],
    }]}))
    monkeypatch.setattr("dashboard.main.ROOT", tmp_path)          # ROOT/history_health_data.json
    r = client.post("/api/refresh/history")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    health = {a["account_name"]: a for a in client.get("/api/account-health").json()["accounts"]}
    assert health["410 Fitness"]["ticket_count"] == 1            # history reached the health API
    assert "sc-27933" not in [b["id"] for b in client.get("/api/bugs").json()["bugs"]]  # excluded from backlog
```

- [ ] **Step 2: Run — expect FAIL** (404, no route): `python3 -m pytest tests/test_api.py -k refresh_history -v`

- [ ] **Step 3: Implement** — in `dashboard/main.py`, import `ingest_historical` (extend the existing `from dashboard.ingest import (...)`), and add near `refresh_bugs`:

```python
@app.post("/api/refresh/history")
def refresh_history():
    return _run_refresh("history", None, ingest_historical, "history_health_data.json")
```

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_api.py -k "refresh_history or bugs or account_health" -v`, then the full suite.

- [ ] **Step 5: Commit**

```bash
git add dashboard/main.py tests/test_api.py
git commit -m "feat: POST /api/refresh/history ingests committed history_health_data.json"
```

---

### Task 5: MCP runbook — fetch, match, emit JSON + report (manual)

**Files:**
- Create: `/Users/trentluecke/.claude/skills/import-account-health-history/SKILL.md`

This is the one-time, MCP-driven Unit 1. It is NOT TDD — it orchestrates the Notion MCP + the Task-2 logic + the store, then is validated by running once. Model it on the `fetch-bugs` skill.

- [ ] **Step 1:** Author `SKILL.md` documenting these steps:
  1. **Load active accounts** from the store: `GET /api/accounts` (or `SELECT account_name FROM accounts`) → build `active_by_norm = {normalize_name(name): name}` using `dashboard.history_import.normalize_name`.
  2. **Fetch both old data sources** via `notion-query-data-sources` (SQL or rows mode, read-only): `collection://31224bca-36d7-80e7-999d-000b1202ec9b` and the "Account Health Metrics Continued" data source (get its `collection://` URL by fetching database page `32124bca-36d7-80a7-99e0-d696231266ea`). Select `Account`, `Ticket Name`, `Shortcut URL`, `date:Date Created:start`, `date:Date Ticket Closed:start`, `Severity of Ticket`.
  3. **Per row:** extract the Shortcut **story id** (regex `/story/(\d+)/` on the URL). Call `resolve_accounts(Account, active_by_norm)`. Priority = first element of the `Severity of Ticket` JSON array (blank → null). A row with no story id, or `resolve_accounts` returning no `matched`, is a SKIP.
  4. **Emit `history_health_data.json`** (matched rows only) at the OS-Metric-Sync repo root, shape per Task 3's Interfaces (`accounts` = the `matched` list).
  5. **Emit `history_import_report.md`** at repo root: every skipped row grouped by reason (`unknown_account`, `demo_or_blank`, `frankenstein_partial` [rows where some parts matched and some were reported], `missing_story_id`), plus a summary line (N imported / N skipped by reason). Nothing silently dropped.
  6. Do NOT write to the old Notion DB(s).

- [ ] **Step 2 (manual validation, after Tasks 1–4 merge + deploy):**
  1. Run the skill locally → produces `history_health_data.json` + `history_import_report.md`.
  2. Eyeball the report; extend `ALIASES` in `dashboard/history_import.py` for any obvious mismatches worth rescuing, and re-run.
  3. Commit `history_health_data.json`, push (deploys to Railway), then `POST /api/refresh/history`.
  4. Confirm `/api/account-health` now shows historical accounts and the CSM surface renders them; confirm `/api/bugs` is unchanged (no `sc-*` rows).

---

## Integration

Tasks 1–4 integrate via PR against `OS-Metric-Sync` `main` (merging = deploying on Railway; additive, no destructive migration). Task 5's JSON is delivered exactly like `bugs_data.json`: committed to the repo → deploy → `POST /api/refresh/history` loads it into the volume DB. Follow `superpowers:finishing-a-development-branch`.

## Self-Review

**Spec coverage:** clean-baseline match (Task 2 `resolve_accounts` + active-only set), one-time import (Task 5 runbook, no sync-all entry), old DB read-only (no write step anywhere), `source='history'` synthetic bugs (Tasks 1+3), excluded from backlog/stats/recurrence but included in health (Task 1 filters + Task 3 fan-out + unchanged `compute_account_health`), `Date Ticket Closed`→resolved-date (Task 3), Shortcut-id identity + add-only dedup (Task 3), unmatched report (Task 5 step 1.5), Railway delivery mirrors bugs (Task 4). ✅

**Placeholder scan:** every code/test step is complete. The "Continued" data source URL is fetched at runbook time (a real step, not a gap). ✅

**Type consistency:** `history_health_data.json` shape (`tickets[].{story_id,ticket_name,priority,created_at,date_completed,url,accounts[]}`) is identical across Task 3's Interfaces, its ingest code, Task 4's test, and Task 5's emit step. `resolve_accounts` return (`{matched,unmatched,reason}`) is consumed only by Task 5. `bugs.source` values `'notion'`/`'history'` and the `COALESCE(source,'notion')` filter match across db.py, get_bugs, and compute_bug_recurrence. Synthetic id format `sc-<story_id>` matches across Tasks 3–5. ✅
</content>
