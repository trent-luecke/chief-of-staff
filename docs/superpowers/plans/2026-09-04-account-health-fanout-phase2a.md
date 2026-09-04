# Account-Health Fan-Out (Phase 2A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans for the TDD tasks (1–3). Task 4 is a skill/runbook edit — execute it as a checklist and validate manually.

**Goal:** Turn the flat `bugs` list into a per-account health layer: fan each bug ticket out to the account(s) it affects, capture the global close date, and expose a computed per-account health API (ticket counts, severity mix, avg resolve time, and the 60-day onboarding-bug signal) — the analytical foundation the CSM surface (Phase 2B) renders.

**Architecture:** Reuse the existing `bugs` table as the ticket record (add a `date_completed` column). Add a `ticket_accounts` fan-out table (one row per bug × affected account) carrying the CSM's per-account `resolved_for_customer_date`. The `fetch-bugs` MCP skill is extended to capture `Affected/Reported Accounts` (resolved to names) and `Date Completed` into `bugs_data.json`; a new `ingest_ticket_accounts` fans them into the table (preserving CSM-set resolved dates). A new `dashboard/account_health.py` computes per-account aggregates behind `GET /api/account-health`.

**Tech Stack:** Python 3, FastAPI, sqlite3, pytest. Notion reads via the MCP `fetch-bugs` skill (no server Notion token exists).

## Global Constraints

- **Target repository:** `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync` (all paths relative to it). Design spec: chief-of-staff `docs/superpowers/specs/2026-09-04-account-health-metrics-rework-design.md`.
- **Prereqs merged:** Phase 1A (`accounts` table, `account_name` PK, `join_date`), Phase 1B (`GET /api/accounts`, OS Accounts Database seeded).
- **Reuse `bugs` as the ticket table** — do NOT create a separate `tickets` table; `GET /api/bugs` consumes `bugs` and must keep working. Add columns additively via the `init_db` migration pattern (see the `demos` ALTER TABLE block in `dashboard/db.py`).
- **Keys:** `bugs.id` (Notion page id) is the ticket key; `account_name` is the account key (must match `accounts.account_name` / the Notion `Account Name` exactly). `ticket_accounts` PK is `(bug_id, account_name)`.
- **Preserve CSM data:** `ingest_ticket_accounts` is add-only (`ON CONFLICT DO NOTHING`) so a re-sync never wipes a CSM-set `resolved_for_customer_date`. It does not delete rows for accounts later removed from a bug (documented limitation; reconciliation is a future refinement).
- **Onboarding window = 60 days** from `join_date`. Single constant `ONBOARDING_WINDOW_DAYS = 60` in `dashboard/account_health.py`.
- **Date formats:** `accounts.join_date` is `M/D/YYYY` (from the sheet); `bugs.created_at`/`date_completed` are ISO-8601. Parse each explicitly; treat `join_date` as possibly NULL/blank.
- **Run tests:** `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest <path> -v`

---

### Task 1: Schema — `ticket_accounts` table + `bugs.date_completed`

**Files:**
- Modify: `dashboard/db.py` (`init_db`)
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `ticket_accounts(bug_id TEXT, account_name TEXT, resolved_for_customer_date TEXT, PRIMARY KEY(bug_id, account_name))`; new nullable `bugs.date_completed TEXT`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_db.py`:

```python
def test_ticket_accounts_table_and_bugs_date_completed(db_path):
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    ta_cols = {r[1] for r in conn.execute("PRAGMA table_info(ticket_accounts)").fetchall()}
    bug_cols = {r[1] for r in conn.execute("PRAGMA table_info(bugs)").fetchall()}
    conn.close()
    assert ta_cols == {"bug_id", "account_name", "resolved_for_customer_date"}
    assert "date_completed" in bug_cols
```

- [ ] **Step 2: Run — expect FAIL** (no `ticket_accounts` table): `python3 -m pytest tests/test_db.py::test_ticket_accounts_table_and_bugs_date_completed -v`

- [ ] **Step 3: Implement** — in `dashboard/db.py`, add to the `executescript` block (after the `bugs` table):

```sql
        CREATE TABLE IF NOT EXISTS ticket_accounts (
            bug_id TEXT NOT NULL,
            account_name TEXT NOT NULL,
            resolved_for_customer_date TEXT,
            PRIMARY KEY (bug_id, account_name)
        );
```

And in the migrations section (after the `demos` ALTER blocks, before `conn.commit()`):

```python
    bug_cols = {r[1] for r in conn.execute("PRAGMA table_info(bugs)").fetchall()}
    if "date_completed" not in bug_cols:
        conn.execute("ALTER TABLE bugs ADD COLUMN date_completed TEXT")
```

- [ ] **Step 4: Run — expect PASS** (full `tests/test_db.py`). Also update any table-count assertion (e.g. `test_init_is_idempotent`) if it counts tables — bump the expected count by 1.

- [ ] **Step 5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add dashboard/db.py tests/test_db.py
git commit -m "feat: ticket_accounts fan-out table + bugs.date_completed column"
```

---

### Task 2: Ingest — fan out accounts + capture completed date

**Files:**
- Modify: `dashboard/ingest.py` (extend `ingest_bugs`; add `ingest_ticket_accounts`)
- Test: `tests/test_ingest_ticket_accounts.py`; extend `tests/test_ingest.py` (or wherever `ingest_bugs` is tested) for `date_completed`

**Interfaces:**
- Consumes enhanced `bugs_data.json` — each bug gains `"accounts": [<account_name>, ...]` and `"date_completed": "<ISO date>"|null` (produced by Task 4).
- Produces: `ingest_bugs` also writes `bugs.date_completed`; new `ingest_ticket_accounts(db_path, json_path) -> int` (count of (bug × account) pairs upserted), add-only, preserving `resolved_for_customer_date`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_ingest_ticket_accounts.py`:

```python
import json
from dashboard.db import get_conn
from dashboard.ingest import ingest_bugs, ingest_ticket_accounts


def _write(tmp_path, bugs):
    p = tmp_path / "bugs_data.json"
    p.write_text(json.dumps({"bugs": bugs}))
    return str(p)


def test_fan_out_creates_one_row_per_account(db_path, tmp_path):
    path = _write(tmp_path, [
        {"id": "bug1", "title": "Kiosk crash", "status": "Done", "priority": "High",
         "tags": [], "created_at": "2026-06-08T00:00:00Z", "updated_at": "2026-06-18T00:00:00Z",
         "url": "u", "date_completed": "2026-06-18", "accounts": ["410 Fitness", "Buan"]},
    ])
    ingest_bugs(db_path, path)
    assert ingest_ticket_accounts(db_path, path) == 2
    conn = get_conn(db_path)
    rows = conn.execute(
        "SELECT account_name FROM ticket_accounts WHERE bug_id='bug1' ORDER BY account_name").fetchall()
    dc = conn.execute("SELECT date_completed FROM bugs WHERE id='bug1'").fetchone()["date_completed"]
    conn.close()
    assert [r["account_name"] for r in rows] == ["410 Fitness", "Buan"]
    assert dc == "2026-06-18"


def test_reingest_preserves_resolved_for_customer_date(db_path, tmp_path):
    path = _write(tmp_path, [
        {"id": "bug1", "title": "x", "status": "Done", "priority": "Low", "tags": [],
         "created_at": "2026-06-08T00:00:00Z", "updated_at": "2026-06-18T00:00:00Z",
         "url": "u", "date_completed": "2026-06-18", "accounts": ["410 Fitness"]},
    ])
    ingest_ticket_accounts(db_path, path)
    conn = get_conn(db_path)
    conn.execute("UPDATE ticket_accounts SET resolved_for_customer_date='2026-06-12' "
                 "WHERE bug_id='bug1' AND account_name='410 Fitness'")
    conn.commit(); conn.close()
    ingest_ticket_accounts(db_path, path)  # re-sync
    conn = get_conn(db_path)
    val = conn.execute("SELECT resolved_for_customer_date FROM ticket_accounts "
                       "WHERE bug_id='bug1'").fetchone()["resolved_for_customer_date"]
    conn.close()
    assert val == "2026-06-12"  # NOT wiped


def test_skips_blank_account_and_missing_id(db_path, tmp_path):
    path = _write(tmp_path, [
        {"id": "bug1", "title": "x", "status": "Done", "priority": "Low", "tags": [],
         "created_at": "2026-06-08T00:00:00Z", "updated_at": "u", "url": "u",
         "date_completed": None, "accounts": ["", "  ", "Real Gym"]},
        {"id": "", "title": "no id", "accounts": ["Ghost"]},
    ])
    assert ingest_ticket_accounts(db_path, path) == 1
    conn = get_conn(db_path)
    names = [r["account_name"] for r in conn.execute("SELECT account_name FROM ticket_accounts").fetchall()]
    conn.close()
    assert names == ["Real Gym"]
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError: ingest_ticket_accounts`): `python3 -m pytest tests/test_ingest_ticket_accounts.py -v`

- [ ] **Step 3: Implement** — in `dashboard/ingest.py`:

Extend `ingest_bugs` to persist `date_completed`. Change its INSERT to:

```python
        conn.execute(
            "INSERT INTO bugs (id, title, status, priority, tags, created_at, updated_at, url, date_completed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "title=excluded.title, status=excluded.status, priority=excluded.priority, "
            "tags=excluded.tags, updated_at=excluded.updated_at, date_completed=excluded.date_completed",
            (b.get("id"), b.get("title"), b.get("status"), b.get("priority"),
             json.dumps(b.get("tags", [])), b.get("created_at"), b.get("updated_at"),
             b.get("url"), b.get("date_completed"))
        )
```

Append the new function:

```python
def ingest_ticket_accounts(db_path, json_path):
    """Fan out each bug's affected accounts into ticket_accounts, one row per
    (bug_id, account_name). Add-only: never overwrites a CSM-set
    resolved_for_customer_date, never deletes. Returns pairs upserted."""
    data = json.loads(Path(json_path).read_text())
    bugs = data.get("bugs", [])
    conn = get_conn(db_path)
    rows = 0
    for b in bugs:
        bug_id = (b.get("id") or "").strip()
        if not bug_id:
            continue
        for name in (b.get("accounts") or []):
            name = (name or "").strip()
            if not name:
                continue
            conn.execute(
                "INSERT INTO ticket_accounts (bug_id, account_name, resolved_for_customer_date) "
                "VALUES (?, ?, NULL) "
                "ON CONFLICT(bug_id, account_name) DO NOTHING",
                (bug_id, name),
            )
            rows += 1
    conn.commit()
    conn.close()
    return rows
```

Note: existing `ingest_bugs` tests may pass bugs without `date_completed` — `b.get("date_completed")` yields `None`, which is fine. Add one assertion to the existing `ingest_bugs` test file that a provided `date_completed` lands in the column.

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_ingest_ticket_accounts.py tests/test_ingest.py -v`, then the full suite.

- [ ] **Step 5: Commit**

```bash
git add dashboard/ingest.py tests/test_ingest_ticket_accounts.py tests/test_ingest.py
git commit -m "feat: fan out bug accounts into ticket_accounts + capture date_completed"
```

---

### Task 3: Per-account health metrics + `GET /api/account-health`

**Files:**
- Create: `dashboard/account_health.py`
- Modify: `dashboard/main.py` (add endpoint)
- Test: `tests/test_account_health.py`

**Interfaces:**
- Produces: `compute_account_health(conn, window_days=ONBOARDING_WINDOW_DAYS, today=None) -> list[dict]`, one dict per account that appears in `ticket_accounts`, each with: `account_name`, `join_date`, `ticket_count`, `open_count`, `severity_mix` (dict of priority→count), `avg_resolve_days` (float|None), `onboarding_bug_count` (bugs created within `window_days` of `join_date`), `currently_onboarding` (bool: today within window of join_date). Endpoint `GET /api/account-health` returns `{"accounts": [...], "generated_at": iso, "window_days": 60}` sorted by `ticket_count` desc.

- [ ] **Step 1: Write the failing tests** — create `tests/test_account_health.py`:

```python
import json
from datetime import date
from dashboard.db import get_conn
from dashboard.ingest import ingest_bugs, ingest_ticket_accounts, ingest_accounts
from dashboard.account_health import compute_account_health


def _seed(db_path, tmp_path):
    acc = tmp_path / "accounts_data.json"
    acc.write_text(json.dumps({"accounts": [
        {"account_name": "Onboarding Gym", "join_date": "6/1/2026", "status": "Active"},
        {"account_name": "Old Gym", "join_date": "1/1/2024", "status": "Active"},
    ]}))
    ingest_accounts(db_path, str(acc))
    bugs = tmp_path / "bugs_data.json"
    bugs.write_text(json.dumps({"bugs": [
        # created 10 days after Onboarding Gym's join -> onboarding bug; resolved 5 days later
        {"id": "b1", "title": "x", "status": "Done", "priority": "High", "tags": [],
         "created_at": "2026-06-11T00:00:00Z", "updated_at": "u", "url": "u",
         "date_completed": "2026-06-16", "accounts": ["Onboarding Gym"]},
        # affects both gyms; open (no completed date)
        {"id": "b2", "title": "y", "status": "In progress", "priority": "Low", "tags": [],
         "created_at": "2026-06-20T00:00:00Z", "updated_at": "u", "url": "u",
         "date_completed": None, "accounts": ["Onboarding Gym", "Old Gym"]},
    ]}))
    ingest_bugs(db_path, str(bugs))
    ingest_ticket_accounts(db_path, str(bugs))


def test_counts_and_onboarding_flag(db_path, tmp_path):
    _seed(db_path, tmp_path)
    conn = get_conn(db_path)
    out = {a["account_name"]: a for a in
           compute_account_health(conn, today=date(2026, 6, 25))}
    conn.close()
    onb = out["Onboarding Gym"]
    assert onb["ticket_count"] == 2
    assert onb["open_count"] == 1
    assert onb["severity_mix"] == {"High": 1, "Low": 1}
    # b1 resolved 2026-06-16 - created 2026-06-11 = 5 days; b2 unresolved -> excluded from avg
    assert onb["avg_resolve_days"] == 5.0
    assert onb["onboarding_bug_count"] == 2   # both b1 (day10) and b2 (day19) within 60d of 6/1
    assert onb["currently_onboarding"] is True  # 6/25 within 60d of 6/1
    old = out["Old Gym"]
    assert old["ticket_count"] == 1
    assert old["onboarding_bug_count"] == 0    # b2 created far outside Old Gym's 2024 window
    assert old["currently_onboarding"] is False


def test_ranked_by_ticket_count_desc(db_path, tmp_path):
    _seed(db_path, tmp_path)
    conn = get_conn(db_path)
    ranked = compute_account_health(conn, today=date(2026, 6, 25))
    conn.close()
    counts = [a["ticket_count"] for a in ranked]
    assert counts == sorted(counts, reverse=True)
    assert ranked[0]["account_name"] == "Onboarding Gym"
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: dashboard.account_health`).

- [ ] **Step 3: Implement** — create `dashboard/account_health.py`:

```python
# dashboard/account_health.py
"""Per-account bug-health aggregates for the CSM surface (Phase 2)."""
from datetime import date, datetime

ONBOARDING_WINDOW_DAYS = 60


def _parse_join_date(s):
    """'M/D/YYYY' -> date, or None."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


def _parse_iso(s):
    """ISO-8601 date or datetime -> date, or None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None


def compute_account_health(conn, window_days=ONBOARDING_WINDOW_DAYS, today=None):
    today = today or date.today()
    rows = conn.execute(
        """
        SELECT ta.account_name AS account_name,
               a.join_date     AS join_date,
               ta.resolved_for_customer_date AS resolved,
               b.priority      AS priority,
               b.status        AS status,
               b.created_at    AS created_at,
               b.date_completed AS date_completed
        FROM ticket_accounts ta
        JOIN bugs b ON b.id = ta.bug_id
        LEFT JOIN accounts a ON a.account_name = ta.account_name
        """
    ).fetchall()

    acc = {}
    for r in rows:
        name = r["account_name"]
        rec = acc.get(name)
        if rec is None:
            jd = _parse_join_date(r["join_date"])
            rec = acc[name] = {
                "account_name": name,
                "join_date": r["join_date"],
                "_join": jd,
                "ticket_count": 0,
                "open_count": 0,
                "severity_mix": {},
                "_resolve_days": [],
                "onboarding_bug_count": 0,
                "currently_onboarding": bool(
                    jd and 0 <= (today - jd).days <= window_days
                ),
            }
        rec["ticket_count"] += 1
        if (r["status"] or "") != "Done":
            rec["open_count"] += 1
        pr = r["priority"] or "Unspecified"
        rec["severity_mix"][pr] = rec["severity_mix"].get(pr, 0) + 1

        created = _parse_iso(r["created_at"])
        resolved = _parse_iso(r["resolved"]) or _parse_iso(r["date_completed"])
        if created and resolved:
            rec["_resolve_days"].append((resolved - created).days)
        jd = rec["_join"]
        if jd and created and 0 <= (created - jd).days <= window_days:
            rec["onboarding_bug_count"] += 1

    out = []
    for rec in acc.values():
        days = rec.pop("_resolve_days")
        rec.pop("_join", None)
        rec["avg_resolve_days"] = round(sum(days) / len(days), 1) if days else None
        out.append(rec)
    out.sort(key=lambda r: r["ticket_count"], reverse=True)
    return out
```

Add the endpoint to `dashboard/main.py` (near the other GET endpoints):

```python
@app.get("/api/account-health")
def account_health():
    from dashboard.account_health import compute_account_health, ONBOARDING_WINDOW_DAYS
    conn = get_conn(DB_PATH)
    accounts = compute_account_health(conn)
    conn.close()
    return {
        "accounts": accounts,
        "window_days": ONBOARDING_WINDOW_DAYS,
        "generated_at": datetime.utcnow().isoformat(),
    }
```

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_account_health.py -v`, then the full suite.

- [ ] **Step 5: Add one endpoint test** to `tests/test_api.py` (uses the `client`/`db_path` fixtures): seed one account + one bug + one ticket_account, `GET /api/account-health`, assert 200, `window_days == 60`, and the account appears with `ticket_count == 1`.

- [ ] **Step 6: Commit**

```bash
git add dashboard/account_health.py dashboard/main.py tests/test_account_health.py tests/test_api.py
git commit -m "feat: per-account health aggregates + GET /api/account-health (60-day onboarding signal)"
```

---

### Task 4: Extend the `fetch-bugs` skill to capture accounts + completed date

**Files:**
- Modify: `/Users/trentluecke/.claude/skills/fetch-bugs/SKILL.md`

This is the MCP-driven fetch (no server Notion token exists). It must add two fields per bug to `bugs_data.json` so Tasks 2–3 have data.

- [ ] **Step 1:** In the skill's field-extraction table, add:

| JSON field | Notion property | Type |
|---|---|---|
| `accounts` | `Affected/Reported Accounts` | relation — resolve each related page to its `Account Name` title (array of strings) |
| `date_completed` | `Date Completed` | date — `.date.start` or null |

- [ ] **Step 2:** Add a note: the relation returns related **page ids** in the OS Accounts Database (`collection://3d124bca-36d7-8069-a2fa-000b83deae3d`); resolve them to names by querying that data source once (map id→`Account Name`) rather than fetching each page, to keep it cheap.

- [ ] **Step 3:** Update the ingest step of the skill to also call `ingest_ticket_accounts` after `ingest_bugs`:

```python
from dashboard.ingest import ingest_bugs, ingest_ticket_accounts
ingest_bugs('dashboard.db', 'bugs_data.json')
ingest_ticket_accounts('dashboard.db', 'bugs_data.json')
```

- [ ] **Step 4 (manual validation):** Run the skill once. Confirm `bugs_data.json` bugs now carry `accounts` (names) and `date_completed`, then `GET /api/account-health` returns populated per-account rows. Note any bug whose relation is empty (fan-out simply skips it).

---

## Phase 2 decomposition (this plan = 2A)

- **2A — data spine (this plan):** fan-out tables, ingest, health API. Independently valuable and testable; unblocks the UI.
- **2B — CSM surface (next plan):** a standalone, CSM-scoped web app reading `GET /api/account-health` — the account list (sortable by ticket count, onboarding-risk flag), per-account drill-down, the **resolved-for-customer write action** (a `PATCH /api/ticket-accounts/{bug_id}/{account}` setting `resolved_for_customer_date`), and the **Onboarding & Recurrence view** (Panel 1: bugs in accounts' first 60 days; Panel 2: frequency by `Technical Area of Issue` with an onboarding-only cut). Its own lightweight login.
- **2C — migration & retirement (next plan):** import the existing manual Account Health Metrics Notion rows into `ticket_accounts` (best-effort account split of the "Frankenstein" combined-gym rows; unsplittable rows flagged), then archive the manual Notion DB read-only.

## Self-Review

**Spec coverage (2A scope):** fan-out per account (Task 2, kills the combined-gym problem structurally), global close date (Tasks 1–2), per-account resolve time preserved for the CSM (Task 2 add-only + Task 3 avg), 60-day onboarding signal (Task 3, from `join_date`), frequency data available via `severity_mix`/counts and the `bugs.tags` already stored (Panel 2 grouping happens in 2B off `Technical Area`). CSM write action, UI, recurrence view, migration, retirement → explicitly 2B/2C. ✅

**Placeholder scan:** every code and test step is complete; no TBD. ✅

**Type consistency:** enhanced `bugs_data.json` bug adds `accounts: list[str]` + `date_completed: str|None`; `ingest_bugs` writes `date_completed`; `ingest_ticket_accounts` reads `accounts`; `compute_account_health` joins `ticket_accounts`↔`bugs`↔`accounts` on the columns those tasks create (`bug_id`, `account_name`, `date_completed`, `join_date`). `ticket_accounts` PK `(bug_id, account_name)` matches the `ON CONFLICT` target. ✅
