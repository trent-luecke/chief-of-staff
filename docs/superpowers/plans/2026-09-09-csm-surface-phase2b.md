# CSM Account-Health Surface (Phase 2B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the standalone, CSM-scoped account-health surface — an account list (sortable by ticket count, onboarding-risk flag), per-account drill-down, the CSM's one write action (mark *resolved-for-customer* per bug×account), and the Onboarding & Recurrence view (Panel 1: bugs in accounts' first 60 days; Panel 2: recurrence by Technical Area with an onboarding-only cut) — behind its own scoped login.

**Architecture:** Additive to the existing FastAPI app (`OS-Metric-Sync`). The 2A data spine (`ticket_accounts`, `bugs.date_completed`, `compute_account_health`, `GET /api/account-health`) is already merged and live. 2B adds: (1) a role-aware `basic_auth` middleware (admin sees everything; a second `CSM_PASSWORD` scopes the CSM to account-health routes only, redirecting elsewhere); (2) three read helpers + endpoints (onboarding enrichment on the health payload, a per-account ticket-history endpoint for drill-down, a bug-recurrence endpoint for Panel 2); (3) a `PATCH` write endpoint that sets `resolved_for_customer_date`; (4) a new self-contained static page `dashboard/static/account-health.html` served at `GET /account-health`. No new tables, no framework, no Notion writes (the store is the health system of record).

**Tech Stack:** Python 3, FastAPI, sqlite3, pytest (backend, TDD). Vanilla HTML/CSS/JS single page matching the existing dark dashboard aesthetic (frontend). Chart.js from the same CDN the existing dashboard already uses, only if a chart is warranted.

## Global Constraints

- **Target repository:** `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync` (all paths below are relative to it). Design spec: chief-of-staff `docs/superpowers/specs/2026-09-04-account-health-metrics-rework-design.md`; upstream plan: `docs/superpowers/plans/2026-09-04-account-health-fanout-phase2a.md`.
- **Prereqs merged (do NOT rebuild):** `accounts` table (`account_name` PK, `join_date` `M/D/YYYY`, `status`), `bugs` (+`date_completed`, `tags` = JSON array of Technical Areas), `ticket_accounts` (PK `(bug_id, account_name)`, `resolved_for_customer_date`), `dashboard/account_health.py` (`compute_account_health`, `_parse_join_date`, `_parse_iso`, `ONBOARDING_WINDOW_DAYS = 60`), and `GET /api/account-health`, `GET /api/accounts`, `GET /api/bugs`.
- **Reuse the 2A helpers** `_parse_join_date` (M/D/YYYY) and `_parse_iso` (ISO) from `dashboard/account_health.py` for every date parse. Do NOT reinvent date parsing. `bugs.created_at`/`date_completed`/`resolved_for_customer_date` are ISO; `accounts.join_date` is `M/D/YYYY` and may be NULL/blank.
- **Onboarding window = 60 days** from `join_date`. Reuse the single constant `ONBOARDING_WINDOW_DAYS` — never hardcode `60`.
- **Additive only.** New health fields are added to existing return dicts; existing 2A tests assert specific keys (not whole-dict equality) and must keep passing. `GET /api/account-health`, `/api/accounts`, `/api/bugs` must keep working unchanged for Trent's dashboard.
- **Auth model (decided):** admin credential `DASHBOARD_PASSWORD` = full access (unchanged). New `CSM_PASSWORD` = scoped: may reach only the account-health page + its APIs; any other GET page redirects (302) to `/account-health`, any other `/api/*` returns 403. When `DASHBOARD_PASSWORD` is unset (local/CI) auth is fully disabled — so auth tests must set the env vars explicitly. `CSM_PASSWORD` must be added to the Railway env before the CSM logs in (noted in Task 6 rollout).
- **Account names contain spaces** (e.g. `410 Fitness`) and are the join key across tables. Pass them in query strings / JSON bodies (URL-encoded), never as a bare path segment — the `PATCH` therefore takes `bug_id` (URL-safe Notion id) in the path and `account_name` in the body.
- **Write endpoint preserves the CSM's intent:** `PATCH` sets/clears `resolved_for_customer_date` on an existing `(bug_id, account_name)` row only; it never creates fan-out rows (ingest owns that) and never touches Notion.
- **Run tests:** `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest <path> -v`
- **Preview:** no `.claude/launch.json` exists — Task 6 creates one running `uvicorn dashboard.main:app` on port 8080.

## File Structure

- `dashboard/main.py` — **modify.** Role-aware `basic_auth` middleware; new endpoints `GET /api/account-tickets`, `GET /api/bug-recurrence`, `PATCH /api/ticket-accounts/{bug_id}`, `GET /account-health` (serves the page).
- `dashboard/account_health.py` — **modify.** Enrich `compute_account_health` (onboarding-scoped severity + areas); add `account_ticket_history(...)` and `compute_bug_recurrence(...)`.
- `dashboard/static/account-health.html` — **create.** The CSM surface (self-contained page).
- `.claude/launch.json` — **create.** Preview config for the Browser pane.
- `tests/test_auth_scoping.py` — **create.** Middleware role tests.
- `tests/test_account_health.py` — **modify.** Onboarding-enrichment + recurrence + ticket-history helper tests.
- `tests/test_api.py` — **modify.** Endpoint tests for the three reads + the PATCH.

---

### Task 1: Role-aware auth middleware (admin vs. scoped CSM)

**Files:**
- Modify: `dashboard/main.py` (the `basic_auth` middleware, ~lines 42-65; add a `RedirectResponse` import and a helper)
- Test: `tests/test_auth_scoping.py` (create)

**Interfaces:**
- Consumes: `os.environ["DASHBOARD_PASSWORD"]` (admin, existing), `os.environ["CSM_PASSWORD"]` (new, scoped). Both read at request time.
- Produces: middleware behavior — admin pw → all routes; csm pw → only paths under `CSM_ALLOWED_PREFIXES`, else 302→`/account-health` for non-API GETs / 403 for everything else; wrong/no pw → 401; `DASHBOARD_PASSWORD` unset → auth disabled. Module constant `CSM_ALLOWED_PREFIXES` and helper `_basic_password(request) -> str | None`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_auth_scoping.py`:

```python
import base64
import importlib
import pytest
from fastapi.testclient import TestClient
import dashboard.main as main_mod


@pytest.fixture
def client(db_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "adminpw")
    monkeypatch.setenv("CSM_PASSWORD", "csmpw")
    importlib.reload(main_mod)
    monkeypatch.setattr("dashboard.main.DB_PATH", db_path)
    return TestClient(main_mod.app, follow_redirects=False)


def _auth(pw):
    return {"Authorization": "Basic " + base64.b64encode(f"csm:{pw}".encode()).decode()}


def test_no_credentials_401(client):
    assert client.get("/api/account-health").status_code == 401


def test_admin_reaches_everything(client):
    assert client.get("/api/arr", headers=_auth("adminpw")).status_code == 200
    assert client.get("/api/account-health", headers=_auth("adminpw")).status_code == 200


def test_csm_reaches_account_health_apis(client):
    for path in ("/api/account-health", "/account-health"):
        assert client.get(path, headers=_auth("csmpw")).status_code == 200


def test_csm_blocked_from_admin_api_403(client):
    assert client.get("/api/arr", headers=_auth("csmpw")).status_code == 403


def test_csm_page_navigation_redirects(client):
    r = client.get("/", headers=_auth("csmpw"))
    assert r.status_code == 302
    assert r.headers["location"] == "/account-health"


def test_health_endpoint_open(client):
    assert client.get("/health").status_code == 200
```

- [ ] **Step 2: Run — expect FAIL** (`/api/arr` returns 200 for the csm pw today; `/` returns 200 not 302): `python3 -m pytest tests/test_auth_scoping.py -v`

- [ ] **Step 3: Implement** — in `dashboard/main.py`:

Add `RedirectResponse` to the responses import (line 13):

```python
from fastapi.responses import HTMLResponse, FileResponse, Response, RedirectResponse
```

Add above the middleware (after line 39):

```python
# Paths a CSM-scoped session may reach; everything else redirects/403s.
CSM_ALLOWED_PREFIXES = (
    "/account-health",
    "/api/account-health",
    "/api/account-tickets",
    "/api/bug-recurrence",
    "/api/ticket-accounts",
)


def _basic_password(request):
    """Extract the password from a Basic auth header, or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return None
    try:
        return base64.b64decode(auth[6:]).decode().split(":", 1)[1]
    except Exception:
        return None


def _csm_allowed(path):
    return any(path == p or path.startswith(p + "/") for p in CSM_ALLOWED_PREFIXES)
```

Replace the whole `basic_auth` middleware body (lines 42-65) with:

```python
@app.middleware("http")
async def basic_auth(request: Request, call_next):
    admin_pw = os.environ.get("DASHBOARD_PASSWORD", "")
    csm_pw = os.environ.get("CSM_PASSWORD", "")
    if not admin_pw:
        return await call_next(request)  # auth disabled (local/CI)

    if request.url.path == "/health":
        return await call_next(request)

    provided = _basic_password(request)
    if provided is not None:
        if secrets.compare_digest(provided.encode(), admin_pw.encode()):
            return await call_next(request)  # admin: full access
        if csm_pw and secrets.compare_digest(provided.encode(), csm_pw.encode()):
            if _csm_allowed(request.url.path):
                return await call_next(request)
            if request.method == "GET" and not request.url.path.startswith("/api"):
                return RedirectResponse("/account-health", status_code=302)
            return Response("Forbidden", status_code=403)

    return Response(
        "Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="OS Dashboard"'},
    )
```

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_auth_scoping.py -v`, then the full suite `python3 -m pytest -q` (confirm no existing test broke — existing tests never set `DASHBOARD_PASSWORD`, so they stay on the disabled-auth path).

- [ ] **Step 5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add dashboard/main.py tests/test_auth_scoping.py
git commit -m "feat: role-aware auth — scope CSM_PASSWORD to account-health routes"
```

---

### Task 2: Onboarding-scoped severity + areas on the health payload (Panel 1 backend)

**Files:**
- Modify: `dashboard/account_health.py` (`compute_account_health`)
- Test: `tests/test_account_health.py`

**Interfaces:**
- Consumes: `ticket_accounts` ⋈ `bugs` ⋈ `accounts` (as today) plus `bugs.tags` (JSON array of Technical Areas).
- Produces: each account dict gains `onboarding_severity_mix` (dict priority→count, over that account's onboarding bugs only) and `onboarding_areas` (dict Technical-Area→count, over onboarding bugs only; a bug with N areas contributes to N buckets; empty tags → no area). Existing fields unchanged. Panel 1 reads these off `GET /api/account-health`, filtered to `currently_onboarding == true`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_account_health.py`:

```python
def test_onboarding_severity_and_areas(db_path, tmp_path):
    import json
    from datetime import date
    from dashboard.db import get_conn
    from dashboard.ingest import ingest_bugs, ingest_ticket_accounts, ingest_accounts
    from dashboard.account_health import compute_account_health

    acc = tmp_path / "accounts_data.json"
    acc.write_text(json.dumps({"accounts": [
        {"account_name": "New Gym", "join_date": "6/1/2026", "status": "Active"},
    ]}))
    ingest_accounts(db_path, str(acc))
    bugs = tmp_path / "bugs_data.json"
    bugs.write_text(json.dumps({"bugs": [
        # onboarding bug (day 10): High, areas Scheduling+Kiosk
        {"id": "b1", "title": "x", "status": "Done", "priority": "High",
         "tags": ["Scheduling", "Kiosk"], "created_at": "2026-06-11T00:00:00Z",
         "updated_at": "u", "url": "u", "date_completed": "2026-06-16",
         "accounts": ["New Gym"]},
        # NOT an onboarding bug (day 200): Low, area Billing
        {"id": "b2", "title": "y", "status": "Done", "priority": "Low",
         "tags": ["Billing"], "created_at": "2026-12-18T00:00:00Z",
         "updated_at": "u", "url": "u", "date_completed": None, "accounts": ["New Gym"]},
    ]}))
    ingest_bugs(db_path, str(bugs))
    ingest_ticket_accounts(db_path, str(bugs))

    conn = get_conn(db_path)
    out = {a["account_name"]: a for a in compute_account_health(conn, today=date(2026, 6, 25))}
    conn.close()
    g = out["New Gym"]
    assert g["onboarding_severity_mix"] == {"High": 1}          # only b1
    assert g["onboarding_areas"] == {"Scheduling": 1, "Kiosk": 1}
    assert g["severity_mix"] == {"High": 1, "Low": 1}           # unchanged: all tickets
```

- [ ] **Step 2: Run — expect FAIL** (`KeyError: 'onboarding_severity_mix'`): `python3 -m pytest tests/test_account_health.py::test_onboarding_severity_and_areas -v`

- [ ] **Step 3: Implement** — in `dashboard/account_health.py`:

Add `import json` at the top (after the datetime import). Add `b.tags AS tags` to the SELECT list in `compute_account_health` (e.g. after `b.date_completed`):

```python
               b.date_completed AS date_completed,
               b.tags          AS tags
```

In the `if rec is None:` initializer dict, add two buckets alongside the existing ones:

```python
                "onboarding_bug_count": 0,
                "onboarding_severity_mix": {},
                "onboarding_areas": {},
                "currently_onboarding": bool(
```

In the per-row loop, replace the onboarding-count block:

```python
        jd = rec["_join"]
        if jd and created and 0 <= (created - jd).days <= window_days:
            rec["onboarding_bug_count"] += 1
```

with:

```python
        jd = rec["_join"]
        if jd and created and 0 <= (created - jd).days <= window_days:
            rec["onboarding_bug_count"] += 1
            rec["onboarding_severity_mix"][pr] = rec["onboarding_severity_mix"].get(pr, 0) + 1
            for area in json.loads(r["tags"] or "[]"):
                rec["onboarding_areas"][area] = rec["onboarding_areas"].get(area, 0) + 1
```

(`pr` is already computed just above as `r["priority"] or "Unspecified"`.)

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_account_health.py -v` (all, including the untouched 2A tests).

- [ ] **Step 5: Commit**

```bash
git add dashboard/account_health.py tests/test_account_health.py
git commit -m "feat: onboarding-scoped severity mix + area counts on account health"
```

---

### Task 3: Per-account ticket history + `GET /api/account-tickets` (drill-down)

**Files:**
- Modify: `dashboard/account_health.py` (add `account_ticket_history`)
- Modify: `dashboard/main.py` (add endpoint)
- Test: `tests/test_account_health.py` (helper), `tests/test_api.py` (endpoint)

**Interfaces:**
- Produces: `account_ticket_history(conn, account_name, window_days=ONBOARDING_WINDOW_DAYS, today=None) -> list[dict]`, one row per bug affecting that account, newest `created_at` first, each with: `bug_id`, `title`, `priority`, `status`, `technical_area` (list[str] from `tags`), `created_at`, `date_completed`, `resolved_for_customer_date`, `response_time_days` (int|None: `(resolved_for_customer_date ∥ date_completed) − created_at`), `is_onboarding_bug` (bool). Endpoint `GET /api/account-tickets?account=<name>` → `{"account_name": <name>, "tickets": [...], "generated_at": iso}`. Unknown account → `tickets: []`.

- [ ] **Step 1: Write the failing helper test** — add to `tests/test_account_health.py`:

```python
def test_account_ticket_history(db_path, tmp_path):
    import json
    from datetime import date
    from dashboard.db import get_conn
    from dashboard.ingest import ingest_bugs, ingest_ticket_accounts, ingest_accounts
    from dashboard.account_health import account_ticket_history

    acc = tmp_path / "accounts_data.json"
    acc.write_text(json.dumps({"accounts": [
        {"account_name": "410 Fitness", "join_date": "6/1/2026", "status": "Active"},
    ]}))
    ingest_accounts(db_path, str(acc))
    bugs = tmp_path / "bugs_data.json"
    bugs.write_text(json.dumps({"bugs": [
        {"id": "b1", "title": "Kiosk crash", "status": "Done", "priority": "High",
         "tags": ["Kiosk"], "created_at": "2026-06-11T00:00:00Z", "updated_at": "u",
         "url": "u", "date_completed": "2026-06-20", "accounts": ["410 Fitness"]},
        {"id": "b2", "title": "Later bug", "status": "In progress", "priority": "Low",
         "tags": [], "created_at": "2026-07-01T00:00:00Z", "updated_at": "u",
         "url": "u", "date_completed": None, "accounts": ["410 Fitness"]},
    ]}))
    ingest_bugs(db_path, str(bugs))
    ingest_ticket_accounts(db_path, str(bugs))
    conn = get_conn(db_path)
    # CSM marked b1 fixed-for-customer earlier than the global close
    conn.execute("UPDATE ticket_accounts SET resolved_for_customer_date='2026-06-15' "
                 "WHERE bug_id='b1' AND account_name='410 Fitness'")
    conn.commit()
    tickets = account_ticket_history(conn, "410 Fitness", today=date(2026, 7, 5))
    conn.close()

    assert [t["bug_id"] for t in tickets] == ["b2", "b1"]  # newest created first
    b1 = next(t for t in tickets if t["bug_id"] == "b1")
    assert b1["technical_area"] == ["Kiosk"]
    assert b1["resolved_for_customer_date"] == "2026-06-15"
    assert b1["response_time_days"] == 4          # 6/15 - 6/11, resolved-for-customer wins
    assert b1["is_onboarding_bug"] is True
    b2 = next(t for t in tickets if t["bug_id"] == "b2")
    assert b2["response_time_days"] is None       # unresolved
    assert b2["is_onboarding_bug"] is False       # created day 30... within 60? 6/1->7/1 = 30d
```

> Note: `2026-07-01 − 2026-06-01 = 30` days ≤ 60, so `b2` IS an onboarding bug. Fix the assertion to `is True` before running — the comment above is deliberately wrong to force you to compute it. Actual expected: `b2["is_onboarding_bug"] is True`.

- [ ] **Step 2: Run — expect FAIL** (`ImportError: account_ticket_history`): `python3 -m pytest tests/test_account_health.py::test_account_ticket_history -v`

- [ ] **Step 3: Implement** — append to `dashboard/account_health.py`:

```python
def account_ticket_history(conn, account_name, window_days=ONBOARDING_WINDOW_DAYS, today=None):
    """One row per bug affecting `account_name`, newest created first, with the
    per-account resolved date, response time, and onboarding flag resolved."""
    import json
    row = conn.execute(
        "SELECT join_date FROM accounts WHERE account_name = ?", (account_name,)
    ).fetchone()
    join = _parse_join_date(row["join_date"]) if row else None
    rows = conn.execute(
        """
        SELECT b.id AS bug_id, b.title AS title, b.priority AS priority,
               b.status AS status, b.tags AS tags, b.created_at AS created_at,
               b.date_completed AS date_completed,
               ta.resolved_for_customer_date AS resolved
        FROM ticket_accounts ta
        JOIN bugs b ON b.id = ta.bug_id
        WHERE ta.account_name = ?
        ORDER BY b.created_at DESC
        """,
        (account_name,),
    ).fetchall()
    tickets = []
    for r in rows:
        created = _parse_iso(r["created_at"])
        resolved = _parse_iso(r["resolved"]) or _parse_iso(r["date_completed"])
        rt = (resolved - created).days if (created and resolved) else None
        is_onb = bool(join and created and 0 <= (created - join).days <= window_days)
        tickets.append({
            "bug_id": r["bug_id"],
            "title": r["title"],
            "priority": r["priority"],
            "status": r["status"],
            "technical_area": json.loads(r["tags"] or "[]"),
            "created_at": r["created_at"],
            "date_completed": r["date_completed"],
            "resolved_for_customer_date": r["resolved"],
            "response_time_days": rt,
            "is_onboarding_bug": is_onb,
        })
    return tickets
```

Add the endpoint to `dashboard/main.py` (near `account_health()`):

```python
@app.get("/api/account-tickets")
def account_tickets(account: str):
    from dashboard.account_health import account_ticket_history
    conn = get_conn(DB_PATH)
    tickets = account_ticket_history(conn, account)
    conn.close()
    return {
        "account_name": account,
        "tickets": tickets,
        "generated_at": datetime.utcnow().isoformat(),
    }
```

- [ ] **Step 4: Add the endpoint test** — add to `tests/test_api.py` (after the account-health test, using `client`/`db_path`):

```python
def test_account_tickets_endpoint(client, db_path):
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    conn.execute("INSERT INTO accounts (account_name, join_date, status, updated_at) "
                 "VALUES ('Buan', '12/4/2025', 'Active', '2026-09-04T00:00:00')")
    conn.execute("INSERT INTO bugs (id, title, status, priority, tags, created_at, updated_at, url, date_completed) "
                 "VALUES ('b1', 'Login loop', 'Done', 'High', '[\"Auth\"]', '2025-12-10T00:00:00Z', 'u', 'u', '2025-12-14')")
    conn.execute("INSERT INTO ticket_accounts (bug_id, account_name, resolved_for_customer_date) "
                 "VALUES ('b1', 'Buan', NULL)")
    conn.commit(); conn.close()

    resp = client.get("/api/account-tickets", params={"account": "Buan"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_name"] == "Buan"
    assert len(body["tickets"]) == 1
    t = body["tickets"][0]
    assert t["bug_id"] == "b1"
    assert t["technical_area"] == ["Auth"]
    assert t["response_time_days"] == 4  # 12/14 - 12/10 via date_completed

    empty = client.get("/api/account-tickets", params={"account": "Nobody"})
    assert empty.status_code == 200 and empty.json()["tickets"] == []
```

- [ ] **Step 5: Run — expect PASS**: `python3 -m pytest tests/test_account_health.py tests/test_api.py -v`

- [ ] **Step 6: Commit**

```bash
git add dashboard/account_health.py dashboard/main.py tests/test_account_health.py tests/test_api.py
git commit -m "feat: per-account ticket history + GET /api/account-tickets (drill-down)"
```

---

### Task 4: Bug recurrence by Technical Area + `GET /api/bug-recurrence` (Panel 2)

**Files:**
- Modify: `dashboard/account_health.py` (add `compute_bug_recurrence`)
- Modify: `dashboard/main.py` (add endpoint)
- Test: `tests/test_account_health.py` (helper), `tests/test_api.py` (endpoint)

**Interfaces:**
- Produces: `compute_bug_recurrence(conn, window_days=ONBOARDING_WINDOW_DAYS, today=None) -> dict` = `{"all": [...], "onboarding": [...]}`. Each list item: `{"area": str, "ticket_count": int (distinct bug ids in that area), "account_count": int (distinct accounts hit)}`, sorted by `(ticket_count, account_count)` desc. `all` = every `ticket_accounts`⋈`bugs` pair grouped by each of the bug's `tags`; empty tags → the bucket `"Uncategorized"`. `onboarding` = the same, restricted to pairs where the bug's `created_at` is within `window_days` of that account's `join_date`. Endpoint `GET /api/bug-recurrence` → `{"all": [...], "onboarding": [...], "window_days": 60, "generated_at": iso}`.

- [ ] **Step 1: Write the failing helper test** — add to `tests/test_account_health.py`:

```python
def test_bug_recurrence_all_and_onboarding(db_path, tmp_path):
    import json
    from datetime import date
    from dashboard.db import get_conn
    from dashboard.ingest import ingest_bugs, ingest_ticket_accounts, ingest_accounts
    from dashboard.account_health import compute_bug_recurrence

    acc = tmp_path / "accounts_data.json"
    acc.write_text(json.dumps({"accounts": [
        {"account_name": "A", "join_date": "6/1/2026", "status": "Active"},
        {"account_name": "B", "join_date": "6/1/2026", "status": "Active"},
        {"account_name": "Old", "join_date": "1/1/2024", "status": "Active"},
    ]}))
    ingest_accounts(db_path, str(acc))
    bugs = tmp_path / "bugs_data.json"
    bugs.write_text(json.dumps({"bugs": [
        # Scheduling bug hits A & B during onboarding (day 10)
        {"id": "b1", "title": "x", "status": "Done", "priority": "High",
         "tags": ["Scheduling"], "created_at": "2026-06-11T00:00:00Z",
         "updated_at": "u", "url": "u", "date_completed": None, "accounts": ["A", "B"]},
        # Scheduling bug hits Old, NOT onboarding (Old joined 2024)
        {"id": "b2", "title": "y", "status": "Done", "priority": "Low",
         "tags": ["Scheduling"], "created_at": "2026-06-20T00:00:00Z",
         "updated_at": "u", "url": "u", "date_completed": None, "accounts": ["Old"]},
        # untagged bug hits A during onboarding -> Uncategorized
        {"id": "b3", "title": "z", "status": "Done", "priority": "Low",
         "tags": [], "created_at": "2026-06-15T00:00:00Z",
         "updated_at": "u", "url": "u", "date_completed": None, "accounts": ["A"]},
    ]}))
    ingest_bugs(db_path, str(bugs))
    ingest_ticket_accounts(db_path, str(bugs))
    conn = get_conn(db_path)
    out = compute_bug_recurrence(conn, today=date(2026, 6, 25))
    conn.close()

    all_by_area = {r["area"]: r for r in out["all"]}
    assert all_by_area["Scheduling"]["ticket_count"] == 2      # b1, b2
    assert all_by_area["Scheduling"]["account_count"] == 3     # A, B, Old
    assert all_by_area["Uncategorized"]["ticket_count"] == 1   # b3
    assert out["all"][0]["area"] == "Scheduling"               # ranked desc

    onb_by_area = {r["area"]: r for r in out["onboarding"]}
    assert onb_by_area["Scheduling"]["ticket_count"] == 1      # only b1 (b2 not onboarding)
    assert onb_by_area["Scheduling"]["account_count"] == 2     # A, B
    assert "b2" not in [r["area"] for r in out["onboarding"]]  # sanity
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError: compute_bug_recurrence`).

- [ ] **Step 3: Implement** — append to `dashboard/account_health.py`:

```python
def compute_bug_recurrence(conn, window_days=ONBOARDING_WINDOW_DAYS, today=None):
    """Cluster tickets by Technical Area (bugs.tags), ranked by frequency, with a
    separate onboarding-only cut (bug created within window_days of the account's
    join_date). Counts distinct bug ids and distinct accounts per area."""
    import json
    rows = conn.execute(
        """
        SELECT b.id AS bug_id, b.tags AS tags, b.created_at AS created_at,
               ta.account_name AS account_name, a.join_date AS join_date
        FROM ticket_accounts ta
        JOIN bugs b ON b.id = ta.bug_id
        LEFT JOIN accounts a ON a.account_name = ta.account_name
        """
    ).fetchall()

    all_areas = {}
    onb_areas = {}

    def _add(bucket, area, bug_id, account_name):
        d = bucket.setdefault(area, {"bugs": set(), "accounts": set()})
        d["bugs"].add(bug_id)
        d["accounts"].add(account_name)

    for r in rows:
        areas = json.loads(r["tags"] or "[]") or ["Uncategorized"]
        for area in areas:
            _add(all_areas, area, r["bug_id"], r["account_name"])
        created = _parse_iso(r["created_at"])
        join = _parse_join_date(r["join_date"])
        if join and created and 0 <= (created - join).days <= window_days:
            for area in areas:
                _add(onb_areas, area, r["bug_id"], r["account_name"])

    def _fmt(bucket):
        out = [
            {"area": a, "ticket_count": len(v["bugs"]), "account_count": len(v["accounts"])}
            for a, v in bucket.items()
        ]
        out.sort(key=lambda x: (x["ticket_count"], x["account_count"]), reverse=True)
        return out

    return {"all": _fmt(all_areas), "onboarding": _fmt(onb_areas)}
```

Add the endpoint to `dashboard/main.py`:

```python
@app.get("/api/bug-recurrence")
def bug_recurrence():
    from dashboard.account_health import compute_bug_recurrence, ONBOARDING_WINDOW_DAYS
    conn = get_conn(DB_PATH)
    data = compute_bug_recurrence(conn)
    conn.close()
    return {
        **data,
        "window_days": ONBOARDING_WINDOW_DAYS,
        "generated_at": datetime.utcnow().isoformat(),
    }
```

- [ ] **Step 4: Add the endpoint test** — add to `tests/test_api.py`:

```python
def test_bug_recurrence_endpoint(client, db_path):
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    conn.execute("INSERT INTO accounts (account_name, join_date, status, updated_at) "
                 "VALUES ('Buan', '6/1/2026', 'Active', '2026-09-04T00:00:00')")
    conn.execute("INSERT INTO bugs (id, title, status, priority, tags, created_at, updated_at, url, date_completed) "
                 "VALUES ('b1', 'x', 'Done', 'High', '[\"Scheduling\"]', '2026-06-10T00:00:00Z', 'u', 'u', NULL)")
    conn.execute("INSERT INTO ticket_accounts (bug_id, account_name, resolved_for_customer_date) "
                 "VALUES ('b1', 'Buan', NULL)")
    conn.commit(); conn.close()

    resp = client.get("/api/bug-recurrence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_days"] == 60
    assert {"all", "onboarding"} <= body.keys()
    assert body["all"][0]["area"] == "Scheduling"
    assert body["onboarding"][0]["area"] == "Scheduling"  # b1 within 60d of 6/1
```

- [ ] **Step 5: Run — expect PASS**: `python3 -m pytest tests/test_account_health.py tests/test_api.py -v`

- [ ] **Step 6: Commit**

```bash
git add dashboard/account_health.py dashboard/main.py tests/test_account_health.py tests/test_api.py
git commit -m "feat: bug recurrence by technical area + GET /api/bug-recurrence (onboarding cut)"
```

---

### Task 5: The CSM write action — `PATCH /api/ticket-accounts/{bug_id}`

**Files:**
- Modify: `dashboard/main.py` (add endpoint + Pydantic body model)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: existing `ticket_accounts` rows (created by ingest).
- Produces: `PATCH /api/ticket-accounts/{bug_id}` with JSON body `{"account_name": str, "resolved_for_customer_date": "YYYY-MM-DD" | null}`. Sets/clears `resolved_for_customer_date` on the `(bug_id, account_name)` row. `200` → `{"bug_id", "account_name", "resolved_for_customer_date"}`; `404` if the pair doesn't exist; `422` if the date is present but not `YYYY-MM-DD`. Never inserts a row.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_api.py`:

```python
def _seed_ticket_account(db_path):
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    conn.execute("INSERT INTO bugs (id, title, status, priority, tags, created_at, updated_at, url, date_completed) "
                 "VALUES ('b1', 'x', 'Done', 'High', '[]', '2026-06-10T00:00:00Z', 'u', 'u', '2026-06-20')")
    conn.execute("INSERT INTO ticket_accounts (bug_id, account_name, resolved_for_customer_date) "
                 "VALUES ('b1', '410 Fitness', NULL)")
    conn.commit(); conn.close()


def test_patch_sets_resolved_date(client, db_path):
    _seed_ticket_account(db_path)
    resp = client.patch("/api/ticket-accounts/b1",
                        json={"account_name": "410 Fitness", "resolved_for_customer_date": "2026-06-15"})
    assert resp.status_code == 200
    assert resp.json()["resolved_for_customer_date"] == "2026-06-15"
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    val = conn.execute("SELECT resolved_for_customer_date FROM ticket_accounts "
                       "WHERE bug_id='b1' AND account_name='410 Fitness'").fetchone()[0]
    conn.close()
    assert val == "2026-06-15"


def test_patch_clears_resolved_date(client, db_path):
    _seed_ticket_account(db_path)
    client.patch("/api/ticket-accounts/b1",
                 json={"account_name": "410 Fitness", "resolved_for_customer_date": "2026-06-15"})
    resp = client.patch("/api/ticket-accounts/b1",
                        json={"account_name": "410 Fitness", "resolved_for_customer_date": None})
    assert resp.status_code == 200
    assert resp.json()["resolved_for_customer_date"] is None


def test_patch_unknown_pair_404(client, db_path):
    _seed_ticket_account(db_path)
    resp = client.patch("/api/ticket-accounts/b1",
                        json={"account_name": "Nobody", "resolved_for_customer_date": "2026-06-15"})
    assert resp.status_code == 404


def test_patch_bad_date_422(client, db_path):
    _seed_ticket_account(db_path)
    resp = client.patch("/api/ticket-accounts/b1",
                        json={"account_name": "410 Fitness", "resolved_for_customer_date": "June 15"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run — expect FAIL** (405/404 — no PATCH route): `python3 -m pytest tests/test_api.py -k patch -v`

- [ ] **Step 3: Implement** — add to `dashboard/main.py` (a model near `MRRUpdate`, and the route near `account_tickets`):

```python
class ResolvedDateUpdate(BaseModel):
    account_name: str
    resolved_for_customer_date: str | None = None

    @field_validator("resolved_for_customer_date")
    @classmethod
    def valid_iso_date(cls, v):
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("resolved_for_customer_date must be YYYY-MM-DD or null")
        return v
```

```python
@app.patch("/api/ticket-accounts/{bug_id}")
def set_resolved_for_customer(bug_id: str, body: ResolvedDateUpdate):
    conn = get_conn(DB_PATH)
    row = conn.execute(
        "SELECT 1 FROM ticket_accounts WHERE bug_id=? AND account_name=?",
        (bug_id, body.account_name),
    ).fetchone()
    if row is None:
        conn.close()
        return Response("ticket_account not found", status_code=404)
    conn.execute(
        "UPDATE ticket_accounts SET resolved_for_customer_date=? WHERE bug_id=? AND account_name=?",
        (body.resolved_for_customer_date, bug_id, body.account_name),
    )
    conn.commit()
    conn.close()
    return {
        "bug_id": bug_id,
        "account_name": body.account_name,
        "resolved_for_customer_date": body.resolved_for_customer_date,
    }
```

- [ ] **Step 4: Run — expect PASS**: `python3 -m pytest tests/test_api.py -k patch -v`, then the full suite `python3 -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add dashboard/main.py tests/test_api.py
git commit -m "feat: PATCH /api/ticket-accounts/{bug_id} sets resolved-for-customer date"
```

---

### Task 6: The CSM surface page + `GET /account-health`

**Files:**
- Create: `dashboard/static/account-health.html`
- Modify: `dashboard/main.py` (add the `GET /account-health` route)
- Create: `.claude/launch.json` (preview)

**Interfaces:**
- Consumes: `GET /api/account-health`, `GET /api/account-tickets?account=<name>`, `GET /api/bug-recurrence`, `PATCH /api/ticket-accounts/{bug_id}`.
- Produces: a self-contained dark-themed page with two tabs — **Accounts** (list + drill-down + write action) and **Onboarding & Recurrence** (Panel 1 + Panel 2). No build step; inline CSS/JS; matches `dashboard/static/index.html` design tokens.

**REQUIRED SUB-SKILL:** Use the `frontend-design` skill for this task.

- [ ] **Step 1: Add the route** to `dashboard/main.py` (near `index()`):

```python
@app.get("/account-health", response_class=HTMLResponse)
def account_health_page():
    return FileResponse(STATIC_DIR / "account-health.html")
```

- [ ] **Step 2: Create the preview config** `.claude/launch.json`:

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "os-metric-sync",
      "runtimeExecutable": "python3",
      "runtimeArgs": ["-m", "uvicorn", "dashboard.main:app", "--port", "8080"],
      "port": 8080
    }
  ]
}
```

- [ ] **Step 3: Build `dashboard/static/account-health.html`** — a single self-contained page. Reuse the design tokens from `dashboard/static/index.html` (`--color-primary #1a1a2e`, `--color-surface #16213e`, `--color-accent #63b3ed`, `--color-danger #e07070`, `--color-warning #e8b84b`, `--color-success #68d391`, Inter font, 14px base). Requirements, each independently verifiable:

  - **Header:** title "Account Health" + a subtitle noting the 60-day onboarding window and `generated_at` freshness.
  - **Two tabs:** "Accounts" and "Onboarding & Recurrence".
  - **Accounts tab — list:** table of accounts from `/api/account-health`, columns: Account, Join Date, Tickets (`ticket_count`), Open (`open_count`), Avg resolve (`avg_resolve_days` or "—"), Severity mix (small inline chips High/Moderate/Low), Onboarding risk. **Onboarding-risk flag:** show 🔴 when `currently_onboarding && onboarding_bug_count >= ONBOARDING_RISK_THRESHOLD` (a JS const, default `3`, with a comment that the threshold is a team decision); always show the raw `onboarding_bug_count` next to it so the number is visible regardless of threshold. Default sort by `ticket_count` desc; clicking a column header re-sorts.
  - **Accounts tab — drill-down:** clicking an account row fetches `/api/account-tickets?account=<name>` and shows its ticket history (Title, Area chips, Priority, Status, Created, Resolved-for-customer, Response days, an onboarding badge). Render a **cluster warning** ("N majors in a short window") when ≥`CLUSTER_MAJOR_THRESHOLD` (JS const, default `2`) `High`-priority tickets fall within any 30-day window of `created_at` — compute client-side.
  - **Write action:** each drill-down ticket row has a date input + Save for `resolved_for_customer_date`, calling `PATCH /api/ticket-accounts/{bug_id}` with `{account_name, resolved_for_customer_date}`. On success, update the row in place and re-pull the account list (avg resolve may change). Provide a "clear" affordance (empty the input + Save → sends `null`). Surface non-200s inline (e.g. a 404 banner), never silently.
  - **Onboarding & Recurrence tab — Panel 1:** from `/api/account-health`, filter `currently_onboarding === true`, sort by `onboarding_bug_count` desc; per account show `onboarding_bug_count`, `onboarding_severity_mix` chips, and `onboarding_areas` (area:count). Empty state: "No accounts currently in their first 60 days."
  - **Onboarding & Recurrence tab — Panel 2:** from `/api/bug-recurrence`, two ranked lists side by side — "All tickets by area" (`all`) and "Onboarding only" (`onboarding`) — each row `area — ticket_count tickets · account_count accounts`. Empty state per list.
  - **Fetch/error/loading:** every fetch has a loading state and an error state; a failed API call shows an inline message, not a blank panel. All requests are same-origin (the browser carries the CSM's Basic-auth credentials automatically).

- [ ] **Step 4: Preview & verify** (frontend verification workflow — do NOT ask the user to check manually):
  1. `preview_start` with `{name: "os-metric-sync"}`.
  2. Seed a little data so the page isn't empty — run this once against the dev DB before previewing:

     ```bash
     cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -c "
     from dashboard.db import get_conn, DEFAULT_DB, init_db
     p=str(DEFAULT_DB); init_db(p); c=get_conn(p)
     c.execute(\"INSERT OR REPLACE INTO accounts(account_name,join_date,status,updated_at) VALUES('Demo Onboarding Gym','8/20/2026','Active','2026-09-09')\")
     c.execute(\"INSERT OR REPLACE INTO accounts(account_name,join_date,status,updated_at) VALUES('Demo Old Gym','1/1/2024','Active','2026-09-09')\")
     for bid,area,pri,acc,created,done in [('demo1','[\\\"Scheduling\\\"]','High','Demo Onboarding Gym','2026-08-25T00:00:00Z',None),('demo2','[\\\"Kiosk\\\"]','High','Demo Onboarding Gym','2026-08-28T00:00:00Z',None),('demo3','[\\\"Scheduling\\\"]','Low','Demo Old Gym','2026-06-01T00:00:00Z','2026-06-05')]:
         c.execute('INSERT OR REPLACE INTO bugs(id,title,status,priority,tags,created_at,updated_at,url,date_completed) VALUES(?,?,?,?,?,?,?,?,?)',(bid,'Demo '+bid,'In progress',pri,area,created,created,'u',done))
         c.execute('INSERT OR IGNORE INTO ticket_accounts(bug_id,account_name,resolved_for_customer_date) VALUES(?,?,NULL)',(bid,acc))
     c.commit(); c.close(); print('seeded')
     "
     ```
  3. `navigate` to `http://localhost:8080/account-health`.
  4. `read_console_messages` (no errors), `read_page` (accounts render; "Demo Onboarding Gym" shows the 🔴 risk flag with count 2), switch to the Onboarding tab and confirm Panel 1 lists the onboarding gym and Panel 2 ranks "Scheduling" top.
  5. Exercise the write action in-browser (set a resolved date on a `demo` ticket via `computer`/`form_input`), confirm the `PATCH` returns 200 in `read_network_requests` and the row updates.
  6. `computer {action: "screenshot"}` of both tabs to share as proof.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/account-health.html dashboard/main.py .claude/launch.json
git commit -m "feat: CSM account-health surface (accounts, drill-down, onboarding & recurrence)"
```

- [ ] **Step 6: Manual rollout note (post-merge, not code):** after this merges and Railway deploys, set the `CSM_PASSWORD` env var in the Railway `os-dashboard` project and hand the CSM the `/account-health` URL. Until `CSM_PASSWORD` is set, no CSM login exists (admin access is unchanged).

---

## Integration

After Task 6, integrate via PR against `OS-Metric-Sync` `main` (merging = deploying on Railway). Additive change; no migration. Follow `superpowers:finishing-a-development-branch`.

**Pending validation (carry-forward from 2A, not blocking 2B dev — the surface is built and tested on fixtures):** run the `fetch-bugs` MCP skill once against real Notion data to confirm the `Affected/Reported Accounts` relation resolves to account **names** (not page ids) and that `/api/account-health` + the new endpoints populate with production numbers before the CSM trusts them.

## Self-Review

**Spec coverage (2B scope):**
- Account list, sortable by ticket count, severity mix, onboarding-risk flag → Task 6 (reads Task 2-enriched `/api/account-health`). ✅
- Per-account drill-down (ticket history, avg resolve, response time, "majors in a short window" cluster) → Task 3 endpoint + Task 6 render/cluster-flag. ✅
- The CSM write action (set `resolved_for_customer_date` per bug×account; supersedes `date_completed` in avg automatically via the 2A query) → Task 5 PATCH + Task 6 UI. ✅
- Onboarding & Recurrence — Panel 1 (onboarding accounts: count/severity/areas) → Task 2 fields + Task 6 Panel 1; Panel 2 (frequency by Technical Area, onboarding-only cut) → Task 4 endpoint + Task 6 Panel 2. ✅
- Scoped access (focus, not secrecy; her own login → account-health only) → Task 1 middleware. ✅
- No push/digest — the surface is the reviewed artifact → satisfied by omission (no notification code). ✅

**Placeholder scan:** every code/test step is complete; the one deliberately-wrong assertion (Task 3 Step 1 `is_onboarding_bug`) is called out with the correct value inline. Frontend requirements are enumerated as individually-verifiable bullets, not "build the UI." ✅

**Type consistency:** `compute_account_health` gains `onboarding_severity_mix`/`onboarding_areas` (Task 2) consumed by Panel 1 (Task 6); `account_ticket_history` return keys (Task 3) match the drill-down render + the PATCH body's `account_name`/`resolved_for_customer_date` (Task 5); `compute_bug_recurrence` `{all,onboarding}` with `area`/`ticket_count`/`account_count` (Task 4) match Panel 2 (Task 6); `CSM_ALLOWED_PREFIXES` (Task 1) enumerates exactly the paths Tasks 3-6 add (`/api/account-tickets`, `/api/bug-recurrence`, `/api/ticket-accounts`, `/account-health`, `/api/account-health`). ✅
</content>
</invoke>
