# Notion Capture Layer (Phase 1B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans for the one TDD task (Task 3). The remaining tasks are Notion structural config and a scheduled-MCP-task setup — execute them as an ordered checklist, verifying each deliverable before moving on.

**Goal:** Make the Bug Tracker capture accounts at intake and keep a canonical Notion Accounts database current from the Client List Sheet — so multi-account tickets fan out correctly downstream and the intake dropdown never goes stale — using a **Claude scheduled MCP task** as the Sheet→Notion transport (no Notion API token in OS-Metric-Sync).

**Architecture:** A new canonical **Accounts** database in Notion is the relation target for a new **Affected/Reported Accounts** relation on the Bug Tracker. OS-Metric-Sync exposes the synced account list at `GET /api/accounts` (its store is already Sheet-synced by Phase 1A). A daily **Claude scheduled task** refreshes that store, reads the list, and add/upserts missing accounts into the Notion Accounts DB via the Notion MCP — one-way, Sheet-wins.

**Tech Stack:** Notion (databases, relations, MCP tools), Claude scheduled tasks (`mcp__scheduled-tasks__*`), FastAPI + sqlite3 (the one read endpoint), pytest.

## Global Constraints

- **Prereq:** Phase 1A (accounts dimension) is merged — the `accounts` table exists and is Sheet-synced. This plan depends on it for `GET /api/accounts`.
- **Two repos / surfaces:** the read endpoint lives in `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync`; the Notion structure and scheduled task live in Trent's Notion workspace + Claude scheduled tasks.
- **Account identity key:** `Account Name` (title in Notion) must match the Sheet's `Account Name` **exactly** — it's the join key for downstream fan-out. The mirror is **add/upsert-only, never deletes** (Sheet wins; removing an account is a manual Notion action).
- **Notion MCP availability:** scheduled tasks run in-app and inherit the claude.ai Notion connector; the known gotcha is one-time **tool pre-approval** on the first supervised run (see Task 6), not auth.
- **Live Bug Tracker data source:** `collection://29d24bca-36d7-80ef-b574-000b739e37a8` (title "TeamBuildr OS 🪲 Tracker"). Existing `Priority Level` options: High / Moderate / Low.

---

### Task 1: Create the canonical Accounts database in Notion

**Deliverable:** a new Notion database "OS Accounts" with the properties below, its URL + `collection://` data-source URL recorded in this plan and in the Phase 1B PR/notes.

**Placement:** under **OS Customer Success** (same parent area as the Bug Tracker and the retiring Account Health Metrics), so it sits with the CS surfaces.

**Schema:**

| Property | Type | Notes |
|---|---|---|
| `Account Name` | Title | The canonical key. Must match the Sheet's `Account Name` verbatim. |
| `Join Date` | Date | Go-live; sourced from the Sheet `Join Date`. |
| `Status` | Select | Options: `Active`, `Churned`. At-a-glance only; downstream derives onboarding from Join Date. |
| `Source` | Text | Constant note: "Synced from Client List sheet — do not hand-edit." |

*(The `Affected/Reported Accounts` relation created in Task 2 will auto-add a reverse "Related Bug Tickets" property here — leave it.)*

- [ ] **Step 1:** Create the database via Notion MCP `notion-create-database` (parent = the OS Customer Success page) with the four properties above, **or** create it manually in the Notion UI. Title it **OS Accounts**.
- [ ] **Step 2:** Fetch it back (`notion-fetch` on the new URL) and confirm the property names/types match the table exactly. Record the page URL and `collection://` data-source URL at the top of this task.
- [ ] **Step 3:** No commit (Notion-side). Note the URLs in the PR description for Task 3.

---

### Task 2: Add the intake fields to the Bug Tracker

**Deliverable:** the Bug Tracker captures accounts + the "Not actually a bug" severity, and the ticket template prompts for them. **Depends on Task 1** (relation needs the Accounts DB to exist).

- [ ] **Step 1: Add the relation.** On the Bug Tracker (`collection://29d24bca-36d7-80ef-b574-000b739e37a8`), add a **Relation** property named **`Affected/Reported Accounts`** pointing at the **OS Accounts** database from Task 1; allow **multiple** related pages (Notion relations are multi by default — do not restrict to one). Recommended: do this in the Notion UI (relation creation is the most reliable there); MCP `notion-update-data-source` is the alternative if it exposes relation config.
- [ ] **Step 2: Add the severity option.** Add **`Not actually a bug`** as a new option on the existing `Priority Level` select (keep High / Moderate / Low). Suggested color: purple (matches the retiring Health tracker's convention).
- [ ] **Step 3: Update the Bug Ticket Template** (`page_templates` → "Bug Ticket Template", `https://app.notion.com/p/32124bca36d7805a87edfc9269639535`): ensure a new ticket surfaces, as blank-to-fill, **`Affected/Reported Accounts`**, **`Shortcut URL`**, and **`Priority Level`** — and add a short template note reminding the closer to set **`Date Completed`** when Status → Done. (Shortcut URL, Date Completed, Date Created, and the `Days before closed/fixed` formula already exist — this step only makes them prompted, not created.)
- [ ] **Step 4:** Fetch the tracker back (`notion-fetch` on the data source) and confirm `Affected/Reported Accounts` (relation) and the `Not actually a bug` option are present.

---

### Task 3: Expose the synced account list at `GET /api/accounts`

**Files:**
- Modify: `dashboard/main.py` (add a GET endpoint)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: the `accounts` table (Phase 1A), `DB_PATH`, `get_conn`.
- Produces: `GET /api/accounts` → `{"accounts": [{"account_name": str, "join_date": str|null, "status": str|null}], "count": int}`, ordered by `account_name`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api.py`:

```python
def test_get_accounts_returns_synced_list(client, db_path):
    from dashboard.db import get_conn
    conn = get_conn(db_path)
    conn.execute("INSERT INTO accounts (account_name, join_date, status, updated_at) "
                 "VALUES ('Buan', '12/4/2025', 'Active', '2026-09-04T00:00:00')")
    conn.execute("INSERT INTO accounts (account_name, join_date, status, updated_at) "
                 "VALUES ('410 Fitness', '11/20/2025', 'Active', '2026-09-04T00:00:00')")
    conn.commit()
    conn.close()

    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    # ordered by account_name
    assert [a["account_name"] for a in body["accounts"]] == ["410 Fitness", "Buan"]
    assert body["accounts"][0]["join_date"] == "11/20/2025"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_api.py::test_get_accounts_returns_synced_list -v`
Expected: FAIL — 404 (endpoint not defined).

- [ ] **Step 3: Write minimal implementation**

In `dashboard/main.py`, add (near the other read endpoints):

```python
@app.get("/api/accounts")
def get_accounts():
    conn = get_conn(DB_PATH)
    rows = conn.execute(
        "SELECT account_name, join_date, status FROM accounts ORDER BY account_name"
    ).fetchall()
    conn.close()
    accounts = [
        {"account_name": r["account_name"], "join_date": r["join_date"], "status": r["status"]}
        for r in rows
    ]
    return {"accounts": accounts, "count": len(accounts)}
```

(Confirm `get_conn` and `DB_PATH` are already imported in `main.py`; they are used by existing endpoints. If `get_conn` isn't imported, add it to the `from dashboard.db import ...` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync && python3 -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync
git add dashboard/main.py tests/test_api.py
git commit -m "feat: GET /api/accounts exposes synced account list for the Notion mirror"
```

- [ ] **Step 6: Deploy** so the scheduled task can reach it: push and let Railway redeploy; confirm `GET https://<os-metric-sync-railway-host>/api/accounts` returns JSON.

---

### Task 4: Seed the Notion Accounts DB (one-time)

**Deliverable:** the OS Accounts DB is populated with every current active account, so the intake dropdown works from day one.

- [ ] **Step 1:** `GET /api/accounts` (live Railway host) to get the full list.
- [ ] **Step 2:** For each account, create a page in the OS Accounts DB via Notion MCP `notion-create-pages` with `Account Name`, `Join Date`, `Status`, and the `Source` note. Batch in reasonable chunks.
- [ ] **Step 3:** `notion-fetch` the DB and confirm the page count matches `body["count"]`. Spot-check 3–5 Join Dates against the Sheet.

*(This one-time seed can be run supervised by Claude Code now; the recurring task in Task 5 keeps it current thereafter.)*

---

### Task 5: Create the daily Sheet→Notion mirror scheduled task

**Deliverable:** a Claude scheduled task (via `mcp__scheduled-tasks__create_scheduled_task`) that runs daily and add/upserts new accounts into the OS Accounts DB.

- [ ] **Step 1:** Create the scheduled task with schedule **daily, 08:15 CT** (before the 08:31 CT window used by other CS routines, so the dropdown is fresh for the day) and this prompt:

> **OS Accounts Notion mirror.** Keep the Notion "OS Accounts" database (data source `<collection:// from Task 1>`) in sync with the account list in OS-Metric-Sync. Steps:
> 1. `POST https://<os-metric-sync-railway-host>/api/refresh/accounts` to re-sync the store from the Client List sheet (ignore a transient failure; continue with current data).
> 2. `GET https://<os-metric-sync-railway-host>/api/accounts` to get the authoritative list.
> 3. Query the OS Accounts Notion DB for existing `Account Name` values.
> 4. For each account in the API list **not** already in Notion, create a page (`Account Name`, `Join Date`, `Status`, Source = "Synced from Client List sheet"). For accounts already present whose `Join Date` differs, update the Join Date. **Never delete** Notion pages that are absent from the API list — report them instead.
> 5. Report a one-line summary: created N, updated M, unmatched-in-Notion K.

- [ ] **Step 2:** Fill the actual Railway host and the Task 1 `collection://` URL into the prompt before creating the task.

---

### Task 6: Supervised first run + enable the schedule

**Deliverable:** the mirror is proven end-to-end and running unattended.

- [ ] **Step 1:** Trigger the task once **supervised** ("Run now"). On this first run, approve the tool prompts (Notion query/create/update, WebFetch/Bash for the HTTP calls) — this persists the approvals so future unattended runs don't stall. (Known gotcha per the Cowork Notion-sync precedent.)
- [ ] **Step 2:** Verify: add a throwaway test account to the Client List sheet → `POST /api/refresh/accounts` → run the task → confirm the new account appears in the OS Accounts DB and then in the Bug Tracker's `Affected/Reported Accounts` dropdown. Remove the test account afterward.
- [ ] **Step 3:** Confirm the daily schedule is enabled. Record the task id.

---

## After Phase 1B: what's unblocked and what's next

With 1A + 1B done: the Bug Tracker captures structured accounts at intake; the dropdown stays current; the store has the accounts dimension with go-live dates. **Phase 2** (bug fan-out ingest into `tickets` + `ticket_accounts`, the 60-day onboarding flag, and the CSM surface) can then read the Bug Tracker's `Affected/Reported Accounts` relation and fan tickets out per account. The manual Account Health Metrics DB is **not** retired until the fan-out + CSM surface (Phase 2–3) are live and validated.

## Self-Review

**Coverage of the deferred 1B scope from the 1A plan:**
- Bug Tracker structural changes (relation, "Not actually a bug", template) → Task 2. ✅
- Canonical Notion Accounts DB → Task 1. ✅
- Sheet→Notion mirror via **scheduled MCP task** (chosen transport) → Tasks 3–6 (read endpoint → seed → scheduled task → supervised enable). ✅

**Placeholder scan:** Concrete Notion schema, exact endpoint code + test, and the full scheduled-task prompt are all present. The two runtime unknowns are intentionally parameterized, not vague: the Railway host and the Task 1 `collection://` URL — both are recorded/filled during execution (Task 1 Step 2, Task 5 Step 2). ✅

**Consistency:** `GET /api/accounts` returns `{account_name, join_date, status}`, which the mirror prompt (Task 5) and seed (Task 4) consume; `Account Name` is the join key across Sheet, store, and Notion. Bug Tracker data-source id matches the live schema fetched 2026-09-04. ✅
