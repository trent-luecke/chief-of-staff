# Account Health — Historical Baseline (Phase 2C) Design Spec

**Date:** 2026-09-09
**Author:** Trent Luecke (brainstormed with Claude)
**Status:** Design approved → implementation plan next
**Target repo:** `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync` (FastAPI + sqlite3 + pytest, Railway)
**Predecessor:** Phase 2B (CSM surface) shipped + deployed + proven end-to-end 2026-09-09. See `docs/superpowers/plans/2026-09-09-csm-surface-phase2b.md` and the rework spec `docs/superpowers/specs/2026-09-04-account-health-metrics-rework-design.md` ("Migration & retirement").

---

## Problem

The Account Health surface (2B) is live but starts empty: the store's `ticket_accounts` only fills as new bugs get tagged with `Affected/Reported Accounts` at intake (2B), and no bugs are tagged yet. Meanwhile ~1.5 years of health history sits in the old manual **Account Health Metrics** Notion DB(s). We want that history to seed the new store so the CSM opens the surface to real per-account context — **without touching the old DB**, which the team is still actively using.

This reshapes the original 2C ("migrate + retire") into an **additive, one-time, read-only import**. Retirement is explicitly dropped.

## The old data — reality (verified 2026-09-09)

Two Notion databases under *OS Customer Success*:
- **Account Health Metrics** — `collection://31224bca-36d7-80e7-999d-000b1202ec9b` (~90 rows)
- **Account Health Metrics Continued** — the overflow DB (data source URL to be fetched at build time from database page `32124bca-36d7-80a7-99e0-d696231266ea`)

Shared schema (both are free-text, hand-maintained):
| Property | Type | Notes |
|---|---|---|
| `Name` | title | mostly blank/ignore |
| `Account` | **text** | the grouping key — free text, NOT canonical; the whole matching problem |
| `Ticket Name` | text | |
| `Shortcut URL` | url | **story id embedded** — the reliable identity/dedup key |
| `Date Created` | date | ticket open date |
| `Date Ticket Closed` | date | **the per-account "fixed-for-customer" date** (what Quinn hand-maintained) |
| `How long before resolved` | formula | derived; ignore (recompute downstream) |
| `Severity of Ticket` | multi-select | `High` / `Moderate` / `Low` / `Not Actually a bug` (may be blank) |
| `Who reported it` | text | ignore (2B decided: no person-level attribution) |
| `How many times…` / `Average time to resolve` | text | hand-typed rollups; ignore (computed downstream) |

**Data-quality facts that drive the design:**
1. **Free-text `Account` rarely matches canonical names.** Observed mismatches: `ZenithX`→"Zenith X", `Built. Strength and Conditioning`→"BUILT. Strength and Conditioning", `ExcessaFit`→"Excessafit", `Columbus Sports Performance Center (1018)`→drop the id, `Henny Jurriens`→"Henny Jurriens Studio", `St Mary's Turkeys`→"St. Mary's Turkeys", `TXT (Talented Tenth Athletics) (21)`→"Talented Tenth Athletics", `The Gym in the Armoury`→"The Gym In the Armoury", `New Era Coaching`/`New Era Coaching Ltd.`→"New Era Coaching Ltd", `Youthlete Academy`→exact match.
2. **~12 rows are internal `Demo`/`Staging`/`OS Demo` accounts**, plus junk (`your mom`, the template row, blank-`Account` rows).
3. **Many accounts are churned / not in the active book** (Alpine Performance Labs, Off-Field, PitFit, Phoenix Athletic Performance, Prime Fitness LLC, Body Effect Sport, Hooptech, Batti Performance, American Made Performance, Evolve, Resolve Fitness Ballard, The Sports Lab, Mi Yoga…).
4. **Duplicate rows exist** (e.g. "SPR Conditioning / Mobile app showing empty schedule" ×2; "Lake Oswego / Glitch in Scheduled times" ×2; "The Gym in the Armoury / Miscommunications" ×2).
5. **Only ~2 true "Frankenstein" comma-combined rows** (`Mi Yoga, SPR Conditioning`; `ZenithX, Alpine Performance Labs`).
6. **No `Technical Area` at all** — the old DB never captured it. Imported history therefore **cannot** feed recurrence-by-area (Panel 2).
7. **Shortcut URL is well-populated** — a reliable identity + dedup key.

## Confirmed decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Import goal | **Clean historical baseline.** Import only rows that normalize to a currently-active account; skip demo/junk/churned/unmatched; report the skips. |
| Cadence | **One-time snapshot.** Run once for the baseline; not a recurring sync. Going-forward capture is the 2B intake path. |
| Old Notion DB | **Read-only input. Never written, archived, or retired.** Team keeps using it. |
| Store home for history | Synthetic `bugs` rows with a new **`source='history'`** flag, fanned into `ticket_accounts`. Reuses 2A/2B machinery. |
| Dashboard/recurrence exposure | History **excluded** from `/api/bugs`, bug stats/snapshot, and Panel-2 recurrence (no area data; must not inflate the live backlog). It **does** feed the account list, drill-down, and onboarding counts. |
| `Date Ticket Closed` maps to | **`ticket_accounts.resolved_for_customer_date`** (it was the per-account fixed date — exactly what 2B captures). |
| Identity / dedup key | **Shortcut story id** (`sc-<storyid>`). |

## Architecture

One-time, MCP-driven, run locally (no `NOTION_TOKEN` on Railway — same constraint as `fetch-bugs`). Three units with clean boundaries:

```
 Old Notion DBs (read-only, MCP)
      │  Flow C (one-time)
      ▼
 [1] fetch+normalize+match  ──► history_health_data.json  +  history_import_report.md
      │                              (matched rows)            (skipped rows, grouped by reason)
      ▼
 [2] ingest_historical(dashboard.db, json)
      │   synthetic bugs (source='history', keyed sc-<storyid>) + ticket_accounts (add-only)
      ▼
 dashboard.db  ──►  [3] source-aware reads
                     • /api/account-health, /api/account-tickets  → include history
                     • /api/bugs, bug stats, /api/bug-recurrence  → exclude source='history'
```

### Unit 1 — Fetch, normalize, match (runbook/skill step)
- Query both old data sources via `notion-query-data-sources` (rows or SQL mode; no writes).
- Load the active-account set from the store's `accounts` table (canonical `account_name`, the sheet-derived truth).
- **Normalizer** (pure, unit-tested): lowercase; strip a trailing parenthetical id like `(1018)`/`(21)`; strip `.`/`,` used as punctuation; collapse whitespace. Plus a **curated alias map** (module constant, seeded from the mismatches in "reality" above; extendable).
- **Frankenstein splitter** (pure, unit-tested): split `Account` on commas; match each part independently; a part that matches an active account imports, a part that doesn't is reported.
- **Match**: a row's account matches iff its normalized (or aliased) name equals the normalized name of an active account. Non-matches, `Demo`/`Staging`/`OS Demo`/blank, and rows with no usable Shortcut id → **skipped and reported** (never imported).
- **Output**: `history_health_data.json` (matched, normalized rows: `{story_id, ticket_name, account_name (canonical), priority, created_at, date_completed}`) and `history_import_report.md` (skipped rows grouped by reason: unknown/churned name, demo/junk, Frankenstein-unsplittable, missing Shortcut id).

### Unit 2 — Ingest (`ingest_historical`, TDD)
- Migration: add nullable `bugs.source TEXT` (existing rows treated as `'notion'` via `COALESCE`). Idempotent `ALTER TABLE` guard like the existing `demos`/`date_completed` migrations.
- For each matched row: upsert a `bugs` row with `id = 'sc-' + story_id`, `source='history'`, `status='Done'`, `priority` ← Severity (first value; blank → NULL), `created_at` ← Date Created, `date_completed` ← Date Ticket Closed, `tags='[]'`, `title` ← Ticket Name, `url` ← Shortcut URL.
- Fan out one `ticket_accounts` row per matched canonical account: `resolved_for_customer_date` ← Date Ticket Closed. **Add-only** (`ON CONFLICT(bug_id, account_name) DO NOTHING`) — never clobbers a CSM-set date, safe to re-run, dedups the known duplicate rows by `(sc-<storyid>, account_name)`.
- Returns `(bugs_upserted, pairs_upserted)`.

### Unit 3 — Source-aware reads (TDD)
- `GET /api/bugs`, its stats, and the bugs block of `/api/metrics/snapshot`: filter to `COALESCE(source,'notion') = 'notion'` — history never appears in Trent's live bug backlog or counts.
- `compute_bug_recurrence` (Panel 2): same filter — history (no Technical Area) is excluded so it can't swamp the ranking as "Uncategorized".
- `compute_account_health` and `account_ticket_history` (account list, drill-down, onboarding counts): **unchanged** — they join `ticket_accounts`→`bugs` regardless of `source`, so history correctly contributes to per-account count, severity mix, avg-resolve, and onboarding-bug counts.

## Data flow: identity, dedup, and overlap with 2B

- **Identity** is the Shortcut story id. A historical ticket affecting two accounts → two `ticket_accounts` rows under one `sc-<storyid>` bug. The DB's duplicate rows collapse via the `(bug_id, account_name)` PK.
- **Overlap with going-forward tagging (2B):** a `source='history'` bug (`sc-<storyid>`) and a future `source='notion'` tracker bug (Notion page id) for the *same* Shortcut story are distinct rows. If someone later tags that tracker bug to the same account, the account counts both — treated as an accepted, small, one-time limitation (the issue genuinely recurred/was re-reported at different times). Not reconciled, because this is a one-time snapshot and the overlap set is tiny today (0 tracker bugs tagged).

## Error handling & honesty

- A row with a blank/unusable Shortcut URL (e.g. junk `as;dlijoeijbaeori`) has no stable id → skipped + reported, never a synthetic `sc-` row.
- Unparseable dates → the field is left NULL (reuse 2A's `_parse_iso`); the row still imports if the account matched.
- The report is a first-class deliverable: every skipped row is accounted for by reason. No silent drops, no silent truncation.
- Churned accounts are *intentionally* excluded (they're not in the active `accounts` dimension); if history for a churned account is ever wanted, it's a deliberate follow-up, not a gap.

## Testing

- **Unit 1 (pure):** normalizer (parens-id strip, punctuation, case, alias map), Frankenstein splitter (both-match, one-match, none-match), and the match/skip classifier (active-match, demo/junk, churned, missing-id).
- **Unit 2 (TDD):** the `source` migration; `ingest_historical` — one row → one bug + one pair with `source='history'` and `resolved_for_customer_date` = Date Ticket Closed; multi-account fan-out; add-only re-run preserves a pre-set resolved date and dedups; blank/no-id skipped.
- **Unit 3 (TDD):** `/api/bugs` and `/api/bug-recurrence` exclude `source='history'`; `/api/account-health` **includes** it (a history-only account appears with the right count/avg/onboarding count).
- **Runbook validation:** run the one-time import against the real DBs; eyeball `history_import_report.md`; confirm `/api/account-health` populates and the CSM surface renders historical accounts.

## Explicitly out of scope

- Any write to the old Notion DB(s); archiving or retiring them.
- Recurring/scheduled sync (one-time snapshot only).
- Back-filling Technical Area onto historical tickets (no source data).
- Going-forward capture (that's the 2B intake path, already live).
- Reconciling the small history-vs-future-tag overlap.

## Open integration point (resolve during planning, not design)

Confirm exactly how a locally-produced import reaches Railway's production `dashboard.db` — trace how the existing MCP-driven bug ingest (`fetch-bugs` → `bugs_data.json` → store) currently lands on Railway (committed data file, a POST ingest endpoint, or a local run against a shared volume) and mirror that path for the historical import. This is a delivery-mechanism detail, not a design change.
</content>
