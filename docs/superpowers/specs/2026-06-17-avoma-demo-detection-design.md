# Avoma-Based OS Demo Detection — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan
**Spans two repos:** `chief-of-staff` (detector) and `OS-Metric-Sync` (store)
**Builds on:** `2026-06-16-metric-sync-overseer-design.md` (engine = metric store; chief-of-staff = overseer)

## Problem

Demos are a core funnel metric (Demos → Closes → Net-new MRR → ARR), but the
current collection mechanism is broken and obsolete:

- `OS-Metric-Sync/sync.py` scrapes 5 reps' Google Calendars for events whose
  title/description contain "demo" + "OS", and writes them to a sheet.
- This no longer reflects reality: Calendly links were **consolidated** into one
  intake where a prospect selects which platforms they want to demo, so there's
  no longer a separate "OS demo" calendar event to match on.
- The collector and the dashboard's reader were also disconnected: `sync.py`
  wrote to the "Monthly Analytics" tab + a separate Conversions workbook, while
  `fetch_demos.py` read per-month tabs that nothing fed — so demos went stale
  (~April 2026) and the brief shows 0.

## Decision

**Detect OS demos from Avoma call transcripts instead of calendars.** The signal
is the Claude analysis already produced by `collectors/avoma.py`: a call counts
as an OS demo when `call_type == "demo"` AND `os_interested == True` (Claude sets
`os_interested` true only when the prospect genuinely engaged with OS, not just
checked a box).

Detection runs in **chief-of-staff** (where the Avoma + Claude logic and the
nightly Avoma sync already live); the **OS-Metric-Sync engine stays the single
store** so the dashboard charts and the brief snapshot both read one source and
cannot drift. chief-of-staff pushes detected demos to a new engine ingest
endpoint over the authenticated channel it already uses (`METRICS_BASE_URL` +
`METRICS_PASSWORD`).

Connection mechanism chosen: **engine ingest endpoint** (push), over the
sheet-write alternative — it reuses the existing engine auth (no Google Sheets
write scope needed), keeps the engine as the store, and dedups in the DB.
Porting the Avoma logic into the engine was rejected (re-creates the cross-repo
duplication the overseer design just eliminated, and bolts an LLM dependency
onto the engine).

## Locked parameters

- **Demo definition:** `call_type == "demo"` AND `os_interested == True`. Per
  call (a prospect with two demo calls = two demos), deduped by Avoma UUID.
- **Reps counted (5):** Ryan Allwein (`ryan@`), Luke Martin (`lmartin@`), Chris
  Reynolds (`chris@`), Jeff Davidson (`jeff@`), Trent Luecke (`trent@`).
  **Excludes Quinn** (`quinn@`), who is in `sales_rep_emails` but not counted.
- **Rep identification:** fuzzy **name** match (not email — Avoma doesn't
  reliably carry the rep email). Primary signal: transcript speaker with
  `is_rep == True` (carries a clean full name, e.g. "Ryan Allwein"); fallback:
  attendee names; email corroborates when present, never required.

## Architecture & data flow

```
  Avoma (5 reps' call transcripts)
        │  nightly (existing avoma_sync.py fetch — reused; one Avoma+Claude pass)
        ▼
  chief-of-staff: fetch_recent_meetings → Claude sets os_interested + call_type
        │  filter: call_type=='demo' AND os_interested AND rep ∈ the 5
        │  map each → {avoma_uuid, rep, start_at, title, invitee_names, invitee_emails}
        ▼  POST /api/demos/ingest   (METRICS_BASE_URL + METRICS_PASSWORD, non-fatal)
  OS-Metric-Sync engine: upsert into demos table (dedup by avoma_uuid)
        │
        ├─► /api/pipeline           → dashboard demo charts (per rep / per month)
        └─► /api/metrics/snapshot   → demos_data → chief-of-staff 7am brief (demos_mtd)
```

Detection rides the existing nightly Avoma fetch, so there is no second
Avoma/Claude cost.

## Engine changes (OS-Metric-Sync)

1. **`demos` table gains `avoma_uuid`** (nullable TEXT, unique index). Existing
   calendar-sourced rows keep `avoma_uuid = NULL`, untouched.
2. **New `POST /api/demos/ingest`** (behind existing basic auth). Body:
   `{"demos": [{avoma_uuid, rep, start_at, title, invitee_names, invitee_emails}]}`.
   For each record: derive `month` from `start_at` (`"%B %Y"`), upsert keyed on
   `avoma_uuid` (insert new / update existing — idempotent). Validate each record;
   skip malformed. Returns `{inserted, updated, skipped}`.
3. **`sync-all` stops fetching demos from the sheet.** The pipeline step keeps
   its onboarding ingest but drops the `fetch_demos.py` call. The demos table is
   now fed only by `/api/demos/ingest`.

The 230 historical demos already in the engine DB are preserved (past months);
Avoma covers the cutover month forward — no overlap/double-count.

## chief-of-staff changes (detector)

1. **Generalize the shared Avoma fetch to match reps by name.** Add an optional
   name-roster path to `fetch_recent_meetings` (or a thin wrapper) so reps are
   matched by fuzzy name, not just email. Opt-in; default (email-only) behavior
   unchanged for callers that don't pass a roster. `avoma_sync.py` opts in,
   which also hardens its Slack reporting against missing rep emails.
2. **`resolve_demo_rep(speakers, attendees, roster) -> canonical_name | None`** —
   fuzzy name resolver. `is_rep` speaker name primary, attendee name fallback,
   normalized full-name / last-name token match. No confident match → `None`
   (caller buckets as `Unassigned` so the total stays correct).
3. **Demo detection + push** hooks into the nightly `scripts/avoma_sync.py`:
   after fetching/analyzing, filter to `call_type=='demo'` AND `os_interested`
   AND rep ∈ the 5, map to demo records, and push via a new
   `metrics_client.push_demos(base_url, password, demos)` (non-fatal — on failure
   log and move on; next night re-pushes idempotently).
4. **Config:** a `demos.rep_emails` (the 5) / roster block so the demo-counting
   set is explicit and separate from the 6-rep `sales_rep_emails`.

## Dedup, cadence & resilience

- **Dedup by `avoma_uuid`** at the engine (upsert) — re-pushing a call is a no-op.
- **Cadence:** nightly, on the existing Avoma cron. The demo detection uses a
  **rolling lookback wider than the interval** (e.g., 72h) so a missed night
  self-heals; overlap is harmless via UUID dedup.
- **One-time backfill:** a script runs a ~35-day lookback once at ship time to
  populate the current month (~44 analyses, one-time).

## Error handling

Every failure mode is non-fatal and self-healing:
- Engine unreachable on push → demos detected but not stored; next night
  re-pushes (idempotent).
- Avoma/Claude failure on a call → that call is skipped (existing behavior).
- Rep unmatched → bucketed `Unassigned`; count preserved.
- Ingest validates each record and skips malformed ones, reporting `skipped`.

## Testing

- **chief-of-staff:** unit-test `resolve_demo_rep` (is_rep speaker match,
  attendee fallback, name variants, no-match→None), the demo filter
  (call_type/os_interested/rep ∈ 5, Quinn excluded), the transcript→record
  mapping, and `metrics_client.push_demos` (happy + engine-down non-fatal).
- **engine:** unit-test `POST /api/demos/ingest` (insert, upsert-dedup by uuid,
  month derivation, malformed-record skip) and that `/api/pipeline` +
  `/api/metrics/snapshot` reflect ingested demos.
- **contract:** one shared fixture so the record shape chief-of-staff sends
  matches what the engine ingest expects (guardrail against drift).

## Out of scope (noted follow-ups)

- **meeting-prep demo KPI:** chief-of-staff's `processors/meeting_prep.py` reads
  the same `1iaM` sheet for a "demos this month" line. That line is already stale
  and will remain so (new demos go to the engine DB, not the sheet). Follow-up:
  point meeting-prep at the engine snapshot's demo count.
- Backfilling demo history for months between the calendar feed stopping (~April)
  and the Avoma cutover — left as gaps; not reconstructed.
- Deleting the legacy `1iaM` / Conversions spreadsheets — kept as historical
  artifacts.
