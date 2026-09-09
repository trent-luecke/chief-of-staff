# Handoff — Phase 2B: CSM Account-Health Surface

**Purpose:** kick off a fresh session to build Phase 2B of the account-health rework. Everything Phases 0–2A already delivered is live; 2B is the standalone screen the new CSM hire actually operates. Read this, then shape → plan → build.

---

## 1. What this initiative is (one paragraph)

Replacing Quinn's manual Notion "number-moving" for Account Health Metrics (he's moving roles; a new CSM takes over). Intake stays in the Notion **Bug Tracker** (now with an `Affected/Reported Accounts` relation); the analytical/health layer moved OUT to the **OS-Metric-Sync** dashboard store, and the CSM gets a **standalone, scoped surface** (Approach B — chosen so she has singular focus, "access permissions" for focus not secrecy). Two purposes drive it: (1) a light churn-risk signal (clusters of tickets, especially during an account's first 60 days), and (2) informing dev priorities (recurring bugs/issues, especially recurring onboarding issues → audit the onboarding tools).

## 2. Read these first

- **Spec (the source of truth for intent):** `docs/superpowers/specs/2026-09-04-account-health-metrics-rework-design.md` — read the "CSM surface" and "Onboarding & Recurrence view" sections.
- **Plans:** `docs/superpowers/plans/2026-09-04-account-health-fanout-phase2a.md` — its bottom "Phase 2 decomposition" defines 2B/2C. Also the 1A/1B plans for how the store + Notion sync work.
- **Memory:** `project_account_health_rework.md` (auto-loaded) has the compressed current state.

## 3. What's already built and LIVE (do not rebuild)

- **Notion:** Bug Tracker (`collection://29d24bca-36d7-80ef-b574-000b739e37a8`) has `Affected/Reported Accounts` (two-way relation → OS Accounts Database), `Priority Level` incl. "Not actually a bug", `Shortcut URL`, `Date Completed`. **OS Accounts Database** (`collection://3d124bca-36d7-8069-a2fa-000b83deae3d`) seeded with 98 active accounts, kept current by the daily `os-accounts-notion-mirror` scheduled task.
- **OS-Metric-Sync store** (`dashboard.db`): `accounts` (account_name PK, join_date `M/D/YYYY`, status), `bugs` (+`date_completed`), `ticket_accounts` (PK `bug_id`+`account_name`, `resolved_for_customer_date` — currently always NULL; **2B is what writes it**).
- **API (Phase 2A, merged PR #6):** `GET /api/account-health` → `{"accounts": [...], "window_days": 60, "generated_at": iso}`. Each account dict: `account_name`, `join_date`, `ticket_count`, `open_count`, `severity_mix` (dict priority→count), `avg_resolve_days` (float|None), `onboarding_bug_count` (bugs created within 60d of join_date), `currently_onboarding` (bool). Sorted by `ticket_count` desc. Also live: `GET /api/accounts`, `GET /api/bugs`.

## 4. What Phase 2B must build

A CSM-scoped surface reading `GET /api/account-health`, per the spec:

1. **Account list** — sortable by ticket count desc; severity mix; a 🔴 onboarding-risk flag (derived from `onboarding_bug_count` / `currently_onboarding` — the threshold is a UI/team decision, expose the count).
2. **Per-account drill-down** — ticket history (join `ticket_accounts`→`bugs`), avg resolve, response time, the "several majors in a short window" cluster.
3. **The CSM's one write action** — set **`resolved_for_customer_date`** per (bug × account), in the moment she tells the customer it's fixed. Needs a NEW write endpoint, e.g. `PATCH /api/ticket-accounts/{bug_id}/{account_name}` body `{"resolved_for_customer_date": "YYYY-MM-DD"}`. Once set, it supersedes `date_completed` in `avg_resolve_days` automatically (the health query already does `resolved_for_customer_date OR date_completed`).
4. **Onboarding & Recurrence view** (a dedicated tab, reviewed as a team on a cadence — NO push/digest):
   - **Panel 1 — bugs during onboarding:** accounts within their first 60 days from `join_date`, which are hitting bugs, how many, severity, areas.
   - **Panel 2 — frequent bugs by feature/workflow:** cluster by `bugs.tags` (= Notion `Technical Area of Issue`), ranked by frequency, with a **separate onboarding-only cut**. (Grouping axis decided: reuse `Technical Area`, don't invent a taxonomy.) May need a small extra endpoint (e.g. `GET /api/bug-recurrence`).
5. **Scoped access** — a lightweight login that shows the CSM ONLY account-health (focus, not secrecy).

## 5. Environment / patterns to follow

- **Repo:** `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync` (FastAPI, sqlite3, pytest). Deploys on Railway (project `os-dashboard`) on push to `main` — merging = deploying.
- **Frontend pattern:** the existing dashboard is a SINGLE vanilla `dashboard/static/index.html` (no framework, ~61KB, plain JS `fetch`) served at `/` via `FileResponse` (`dashboard/main.py:383`). The CSM surface most naturally is a NEW static page (e.g. `dashboard/static/account-health.html`) on its own route (e.g. `GET /account-health`). Consider the `frontend-design` skill for the UI.
- **Auth:** a `basic_auth` middleware (`dashboard/main.py:43`, `DASHBOARD_PASSWORD`) already guards ALL routes. **Open design decision for 2B:** how to scope the CSM — a second credential/route, or reuse the existing one and just give her the account-health URL. Spec says focus-not-secrecy, so lean lightweight.
- **Tests:** `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest`. Test patterns: `tests/conftest.py` (`db_path` fixture via `init_db`), `tests/test_api.py` (`client` fixture = `TestClient(main_mod.app)` after `importlib.reload`). Follow `ingest_*`/endpoint test styles already there.
- **Preview:** no `.claude/launch.json` exists — create one running `uvicorn dashboard.main:app` (port 8080) to preview in the Browser pane, or run it and screenshot.
- **Railway CLI is linked** — `railway run python3 fetch_accounts.py` fetches real account data with injected creds (used to validate, and by the mirror).

## 6. Critical caveats / gotchas

- **The health data is SPARSE right now.** Existing bugs predate the `Affected/Reported Accounts` relation, so `/api/account-health` returns little until (a) new bugs are tagged with accounts at intake and (b) the `fetch-bugs` MCP skill runs. **For 2B dev/testing, seed `ticket_accounts`/`bugs`/`accounts` fixtures** rather than relying on live data. (There's a **pending validation**: run the `fetch-bugs` skill once against real data to confirm it resolves account NAMES not page ids and `/api/account-health` populates — do this before trusting production numbers.)
- **Dates:** `accounts.join_date` is `M/D/YYYY`; bug/resolved dates are ISO. `dashboard/account_health.py` has `_parse_join_date` / `_parse_iso` helpers — reuse them, don't reinvent.
- **`ingest_ticket_accounts` is add-only / no reconcile:** if a bug is re-tagged (an account removed), the old `ticket_accounts` row lingers. Known v1 limitation — surface accounts honestly in the UI; a reconcile pass is a possible fast-follow, but must never blow away a CSM-set `resolved_for_customer_date`.
- **Bug writes to Notion are MCP-only** (no `NOTION_TOKEN` on Railway). 2B writes go to the STORE (`ticket_accounts`), not back to Notion — correct, the store is the health system of record.

## 7. Suggested flow for the new session

1. (Optional) `os-feature-shaping` if you want to pressure-test the 2B UX/scope first — but the spec already shaped it, so likely skip.
2. `writing-plans` → produce `docs/superpowers/plans/2026-09-0X-csm-surface-phase2b.md` (TDD tasks: the `PATCH` write endpoint + any recurrence endpoint are clean TDD; the HTML/JS surface + `frontend-design`; the scoped-auth decision).
3. `subagent-driven-development` to execute (backend tasks TDD; the frontend task + a preview/screenshot verification).
4. Integrate via PR + merge (additive; Railway deploys on merge).

## 8. Then Phase 2C (after 2B)

Migrate the existing manual Account Health Metrics Notion rows into `ticket_accounts` (best-effort split of the "Frankenstein" combined-gym rows; flag unsplittable), then archive the manual Notion DB read-only. Retire only after 2B is validated.
