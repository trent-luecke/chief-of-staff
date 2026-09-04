# Account Health Metrics Rework — Design Spec

**Date:** 2026-09-04
**Author:** Trent Luecke (brainstormed with Claude)
**Status:** Design approved, pending spec review → implementation plan

---

## Problem

Bug tickets flow through two Notion surfaces:

1. **TeamBuildr OS 🪲 Tracker** (in the Dev Sync Notes page) — the working bug list. Live schema: `Ticket Name` (title), `Status`, `Priority Level` (High/Moderate/Low), `Technical Area of Issue` (multi-select, 13 options), `Shortcut URL` (url), `Date Created` (auto created_time), `Date Completed` (manual date), `Days before closed/fixed` (formula), `Ticket Owner` (created_by), `Last Update`, `Needs Updating?` (checkbox). It already has the Shortcut link, both dates, and a resolve-duration formula — but **no account field**, and the workflow doesn't actually *use* the date/formula fields it has.
2. **Account Health Metrics** — a second Notion DB fed by an automation off the tracker. It carries `Account` (plain text, doubles as the grouping key), `Ticket Name`, `Shortcut URL`, `Date Created`, `Date Ticket Closed`, `How long before resolved` (formula), `Severity`, `Who reported it`, plus two **hand-typed** text fields: `How many times did each account have a ticket` and `Average time to resolve`.

The tracker's own dates and resolve formula sit unused; the workflow **re-derives all of it by hand in the Health tracker instead**, and the account (which the tracker can't hold) forces a Shortcut lookup. So for every closed ticket the CSM (Quinn): opens Shortcut → reads the account name → reads the created date → **digs through ticket comments** to find the real "fixed-for-this-customer" date → hand-tags severity → types the account name (which relocates the row into that gym's group) → eyeballs and re-edits neighboring rows.

### The five concrete pain points

1. **Account name** reconstructed from Shortcut (should be captured at source).
2. **Dates** reconstructed from Shortcut — worst of all, the "fixed-for-customer" date buried in comments (short-term fix shipped to one account before the ticket globally closed).
3. **Severity** hand-tagged.
4. **Multi-account tickets** — the automation concatenates every affected account into one bogus "gym," fragmenting the data. A **text** `Account` field literally *cannot* fan one ticket out to many accounts; this is a structural defect, not a discipline problem.
5. **Manual rollups** — count and avg-resolve are hand-typed text; and Notion's grouped view can't sort groups by ticket-count (Quinn's explicit ask).

### Why now

Quinn is moving to a new role; a new hire takes this over. The design must minimize tribal knowledge and manual judgment — favor structure and automation over "train the new person on Quinn's process."

---

## The two purposes this data serves

1. **Light churn-risk signal.** Not a 1:1 rule, but it matters when an account takes several major tickets in a short window — and *especially* when an account hits a cluster of bugs during its onboarding phase.
2. **Inform development priorities.** Recurring bugs/requests point at something OS should fix or add. In particular, the *same 3–4 issues* recurring across accounts *during onboarding* is the trigger to audit the in-platform onboarding tools.

---

## Confirmed decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Account known at ticket creation? | **Yes, almost always** — capture as structured data up front. |
| Resolved-date precision | **Capture "fixed-for-customer" in the moment**, per account — never reconstruct from comments. |
| Where the health view lives | **Downstream, standalone CSM surface** (Approach B) — Notion stays capture/collab; analytics move out; CSM-scoped for focus, not secrecy. |
| Accounts dimension | **Small Notion Accounts DB as a derived mirror of the Google Sheet** — Trent never maintains it by hand; the Sheet stays the single source of truth. |
| Severity vs Priority | **One field** — reuse the tracker's `Priority Level`, add a "Not actually a bug" option. |
| Go-live date source | **`Join Date`** column, Active Customers tab, [TeamBuildr OS Clients sheet](https://docs.google.com/spreadsheets/d/1pOUxLMX2H48miMvEbgqOXq1C0VHkGm-XXW2VCodQfU0/edit?gid=1945118132). Read-only (tab is ARRAYFORMULA-driven). |
| Onboarding window | **60 days** from Join Date. Single config value, retunable without code change. |
| Panel-2 grouping axis | **Existing `Technical Area of Issue`** as-is; refine into a finer feature/workflow taxonomy only if it proves too coarse. |
| Feedback delivery | **None** — no digest/notification. The surface *is* the artifact reviewed together as a team on a cadence. |

---

## Architecture overview

**Split intake from health-ops.** Two people, two surfaces, one shared store.

```
  Google Sheet (canonical, hand-maintained)
        │  Flow A (one-way, daily, Sheet wins)
        ▼
  Notion Accounts DB (dropdown target) ─┐
                                        │
  Notion Bug Tracker (intake + weekly   │
   dev sync) ──── Flow B (fan-out) ─────┤
                                        ▼
                            dashboard.db (shared store, OS-Metric-Sync)
                              accounts · tickets · ticket_accounts
                                        │
                     ┌──────────────────┴───────────────────┐
                     ▼                                       ▼
        CSM Health surface (scoped login)        OS-Metric-Sync dashboard
        - account list, drill-downs              - Trent's deeper analysis,
        - onboarding & recurrence view             no permission constraints
        - writes resolved-for-customer date
```

### Division of labor

**Notion Bug Tracker = intake + weekly dev sync** (whoever logs the bug — support / CSM / Trent):
- Ticket name, **Accounts Affected** (relation to the Accounts DB, many allowed), Shortcut URL, Priority/Severity, Technical Area, Status. Created date is automatic.
- The *only* place a bug is logged. No health-metric work happens here anymore.

**Standalone CSM Health surface = the new hire's world:**
- Sees tickets already **fanned out per account**, sortable by count.
- Her one recurring write action: **mark "resolved for this customer"** — per account, in the moment she tells the customer. This is the "capture cheaply" decision realized in the surface she already lives in. Because it's per-account, a fix shipping to Gym A Monday and Gym B Wednesday records *correctly* — impossible with a single ticket-level Notion date.
- Everything else is computed: per-account ticket count, avg resolve, response time, severity mix, onboarding-risk flag.

**A sync ties them together** and **never clobbers** CSM-entered resolved dates.

---

## Bug Tracker field enhancements (gap analysis)

Rooted in the **live** tracker schema (verified 2026-09-04). Most of what the ingest needs already exists in the tracker — it just isn't being *used*; the workflow re-derives it by hand in the Health tracker. The only field that must be **created** is the accounts relation. Goal: **Flow B sources 100% of its data from the Bug Tracker**, nothing stranded in the retired Health DB. Gating part of Phase 1.

| Health Tracker field | Bug Tracker reality | Action |
|---|---|---|
| `Account` (text) | ❌ **Missing** | **CREATE `Affected/Reported Accounts`** (relation → Accounts DB, many). The one true gap; replaces the text field, enables per-account fan-out. One relation covers "reported by" + "affected" at account grain. |
| `Shortcut URL` (url) | ✅ Exists (`Shortcut URL`) | **Reuse.** Make it a filled-at-intake field (bake into the Bug Ticket Template). |
| `Date Ticket Closed` (date) | ✅ Exists (`Date Completed`, manual) | **Reuse as the global close date.** Enforce it's set on close (template + `Needs Updating?` checkbox already exist to support this). |
| `Date Created` (date) | ✅ Exists (auto `created_time`) | **Reuse.** Fidelity note: `created_time` ≈ report date only if tickets are logged promptly; add an optional `Date Reported` override only if that gap proves material. |
| `How long before resolved` (formula) | ✅ Exists (`Days before closed/fixed`) | **Reuse** as the global per-ticket resolve. Per-account response time is still computed downstream (uses the CSM's resolved-for-customer date). |
| `Severity of Ticket` (multi-select) | ⚠️ Partial (`Priority Level`: High/Moderate/Low) | **ADD "Not actually a bug" option** to `Priority Level`. One field, no duplicate. |
| `Who reported it` (text) | ⚠️ `Ticket Owner` = internal logger, not the customer | **Decided: no new field.** `Ticket Owner` + the Accounts relation suffice; account-level attribution is enough, person-level complainer not tracked. |
| `Average time to resolve` (text) | — | **Computed downstream.** Never hand-typed again. |
| `How many times per account` (text) | — | **Computed downstream.** |
| `Name` (title) | tracker `Ticket Name` | **Drop** — redundant. |
| *Resolved-for-customer (per account)* | — | **Lives in CSM surface / `ticket_accounts`**, NOT the tracker. Per-account value a ticket-level Notion field can't hold. |

**Net Notion changes shrink to:** (1) **create** `Affected/Reported Accounts` relation; (2) **add** "Not actually a bug" to `Priority Level`. Everything else already exists — the work is making `Shortcut URL` + `Date Completed` reliably filled at intake/close (via the existing **Bug Ticket Template** and `Needs Updating?` checkbox). No customer-reporter field (`Ticket Owner` + Accounts relation suffice).

---

## Data model (shared store: OS-Metric-Sync `dashboard.db`)

**`accounts`** — the account dimension (didn't exist before):
| column | source | notes |
|---|---|---|
| `account_name` | Sheet | natural key |
| `join_date` | Sheet `Join Date` | powers onboarding window |
| `status` | derived | `onboarding` if `today − join_date ≤ 60d`, else `live`; `churned` if flagged in Sheet |

**`tickets`** — one row per Notion bug:
| column | source |
|---|---|
| `ticket_id` | Notion page id (natural key) |
| `ticket_name`, `shortcut_url`, `priority`, `technical_area[]`, `status` | Notion tracker |
| `created_date` | Bug Tracker `Date Created` (auto; or optional `Date Reported`) |
| `global_closed_date` | Bug Tracker `Date Completed` field |
| `notion_last_edited` | Bug Tracker `Last Update` — for change detection |

**`ticket_accounts`** — the fan-out fact (replaces the text `Account` field):
| column | source |
|---|---|
| `ticket_id` (FK), `account_name` (FK) | fan-out of the relation |
| `resolved_for_customer_date` | **CSM-set in the surface**, nullable — preserved across syncs |
| `response_time` | derived: `(resolved_for_customer_date ∥ global_closed_date) − created_date` |
| `is_onboarding_bug` | derived: `created_date ∈ [join_date, join_date + 60d]` |

Computed metrics (query-time, never stored by hand): per-account `ticket_count`, `severity_mix`, `avg_resolve`, `open_count`, `onboarding_risk_flag`.

---

## Sync flows

**Flow A — Accounts (Sheet → everywhere).** One-way, Sheet wins. `Google Sheet Active Customers` → Notion Accounts DB (the dropdown target) + `accounts` table. Daily cadence. Upsert by `account_name`; add-only so it never fights manual Sheet edits. Reads `Join Date`; never writes to the ARRAYFORMULA tab. Google auth via chief-of-staff's existing OAuth (already has Sheets scope). Notion write via API/MCP.

**Flow B — Bugs (Notion → store).** `Notion Bug Tracker` → resolve Accounts relation → fan out to one `ticket_accounts` row per gym → upsert `tickets` + `ticket_accounts`. Extends the existing `fetch-bugs` ingest. **Upsert preserves `resolved_for_customer_date`.** Cadence: scheduled (nightly) + on-demand.

---

## The CSM surface

A small web app in the **OS-Metric-Sync Railway project**, reading the same `dashboard.db` — a *view on the shared store*, not a second engine. Its own simple login for the CSM, scoped to account-health routes only (lightweight auth; focus, not secrecy).

**Views:**
- **Account list** — sortable by ticket count desc; severity mix; 🔴 onboarding-risk flag.
- **Per-account drill-down** — ticket history, avg resolve, response time, the "several majors in a short window" cluster.
- **Write action** — mark *resolved-for-customer* per ticket×account.

Trent's OS-Metric-Sync dashboard reads the same tables for deeper analysis, unconstrained by CSM scoping.

---

## Onboarding & Recurrence view

A dedicated tab (in the CSM surface, mirrored to Trent), reviewed together as a team on a cadence. Two panels:

**Panel 1 — Bugs during onboarding.** Scope: every account inside its first **60 days** from Join Date. Which onboarding accounts are hitting bugs, how many, severity, and which areas — so a new account drowning in issues is visible *while onboarding*, not at churn.

**Panel 2 — Frequent bugs by feature/workflow.** Clusters tickets by `Technical Area of Issue`, ranked by frequency, with a **separate onboarding-only cut** — "the same 3–4 issues keep hitting accounts in their first 60 days" surfaces on its own. This is the audit-the-onboarding-tools trigger.

---

## Migration & retirement

- One-time import of existing Account Health Metrics rows into the store (preserve history). Combined-name "Frankenstein" rows are split best-effort into multiple `ticket_accounts`; unsplittable rows flagged for manual cleanup.
- Retire the manual Notion Health Metrics DB — **archive read-only**, nothing lost.
- Bug Tracker gains the new fields; the weekly dev sync is unchanged in feel.

---

## Open items to validate at build time

1. **Sheet structure** — confirm `Active Customers` exposes a readable `Join Date` per account (the tab is ARRAYFORMULA-driven; verify the column resolves per row) and that a churn/inactive signal exists if `status = churned` is wanted.
2. **Account-name matching** — the canonical key is `account_name` across Sheet, Notion relation, and historical rows. Going forward, the Sheet-derived dropdown eliminates typos at capture; historical import needs a matching/normalization pass.
3. **Sheet → Notion writer** — `fetch-bugs` reads Notion via MCP; Flow A must *write* accounts into Notion (API or MCP). Confirm the write path and idempotency.
4. **Auth** — pick the lightest login that gives the CSM a scoped view (single-user password / magic link) without a full role system.

---

## Rough phase breakdown (for the implementation plan)

1. **Accounts dimension + Bug Tracker enhancements** — Flow A (Sheet → `accounts` + Notion Accounts DB); apply the **gap analysis**: create the `Affected/Reported Accounts` relation, add "Not actually a bug" to `Priority Level`, and make the already-existing `Shortcut URL` + `Date Completed` reliably filled at intake/close (bake into the Bug Ticket Template). Gating requirement: the tracker must hold everything the ingest needs before Health Metrics is retired.
2. **Bug ingest fan-out** — extend `fetch-bugs` into `tickets` + `ticket_accounts` with resolved-date preservation.
3. **CSM surface** — read views + resolved-date write + scoped auth.
4. **Onboarding & Recurrence view** — the two panels.
5. **Migration & retirement** — import history, archive the old Notion DB.
