# Avoma-Based OS Demo Detection — Design

**Date:** 2026-06-17
**Status:** ✅ Implemented and LIVE in production (as of 2026-08). Nightly
`avoma_sync.yml` (cron `0 3 * * *`) runs `detect_demos` → `metrics_client.push_demos`
→ OMS `POST /api/demos/ingest`. (2026-08-18: Phase 0 of the GTM producer outline
fixed the prospect-email drop so pushed `invitee_emails` is now populated —
see `2026-08-17-gtm-producer-side-outline.md`.)
**Spans two repos:** `chief-of-staff` (detector) and `OS-Metric-Sync` (store + UI)
**Builds on:** `2026-06-16-metric-sync-overseer-design.md` (engine = metric store; chief-of-staff = overseer)

## Problem

Demos are a core funnel metric (Demos → Closes → Net-new MRR → ARR), but the
current collection mechanism is broken and obsolete:

- `OS-Metric-Sync/sync.py` scrapes 5 reps' Google Calendars for events whose
  title/description contain "demo" + "OS", and writes them to a sheet.
- This no longer reflects reality: Calendly links were **consolidated** into one
  intake where a prospect selects which platforms they want to demo, so there's
  no longer a separate "OS demo" calendar event to match on.
- The collector and the dashboard's reader were also disconnected, so demos went
  stale (~April 2026) and the brief shows 0.

## Decision

**Detect OS demos from Avoma call transcripts instead of calendars.** A call
counts as an OS demo when `call_type == "demo"` AND `os_interested == True` (the
Claude analysis in `collectors/avoma.py` sets `os_interested` true only when the
prospect genuinely engaged with OS, not just checked a box).

Detection runs in **chief-of-staff** (where the Avoma + Claude logic and the
nightly Avoma sync already live); the **OS-Metric-Sync engine stays the single
store**. chief-of-staff pushes detected demos to a new engine ingest endpoint
over the authenticated channel it already uses (`METRICS_BASE_URL` +
`METRICS_PASSWORD`). The **engine database is the one source** feeding the
dashboard, the brief, and meeting-prep — they cannot drift.

**Connection mechanism: engine ingest endpoint (push).** Chosen over writing to
a Google Sheet so the engine never has to read a sheet, and over porting the
Avoma logic into the engine (which would re-create the cross-repo duplication the
overseer design eliminated).

**Human-facing surface: an editable Demos table in the dashboard** (not a Google
Sheet). Edits write straight to the engine DB — the same store the count/charts/
brief read — so there's no sync gap, and it's all in one system.

## Locked parameters

- **Demo definition:** `call_type == "demo"` AND `os_interested == True`. Per
  call, deduped by Avoma UUID.
- **Reps counted (5):** Ryan Allwein (`ryan@`), Luke Martin (`lmartin@`), Chris
  Reynolds (`chris@`), Jeff Davidson (`jeff@`), Trent Luecke (`trent@`).
  **Excludes Quinn** (`quinn@`).
- **Rep identification:** fuzzy **name** match (not email). Primary: transcript
  speaker with `is_rep == True` (carries a clean full name); fallback: attendee
  names; email corroborates when present, never required. No confident match →
  rep stored as `Unassigned` (still counted; correctable in the UI).

## Architecture & data flow

```
  Avoma (5 reps' transcripts)
        │  nightly (existing avoma_sync.py fetch — reused; one Avoma+Claude pass)
        ▼
  chief-of-staff: fetch_recent_meetings → Claude sets os_interested + call_type
        │  filter: call_type=='demo' AND os_interested AND rep ∈ the 5
        │  map each → {avoma_uuid, rep, start_at, title, invitee_names, invitee_emails}
        ▼  POST /api/demos/ingest   (METRICS_BASE_URL + METRICS_PASSWORD, non-fatal)
  OS-Metric-Sync engine: demos table (SINGLE SOURCE)
        ├─► dashboard: editable Demos table  ← human manages rows (reassign / exclude / add / edit)
        ├─► /api/pipeline → dashboard demo charts (per rep / per month)
        ├─► /api/metrics/snapshot → demos_data → chief-of-staff 7am brief (demos_mtd)
        └─► meeting-prep "Demos MTD" line (via snapshot)
```

Detection rides the existing nightly Avoma fetch — no second Avoma/Claude cost.

## Engine changes (OS-Metric-Sync)

**Schema — `demos` table gains three columns:**
- `avoma_uuid` TEXT (nullable, unique index) — dedup key for transcript-sourced
  demos. Manual rows and legacy calendar rows have `avoma_uuid = NULL`.
- `excluded` INTEGER DEFAULT 0 — soft-delete (false positives).
- `manually_edited` INTEGER DEFAULT 0 — set when a human edits a row's fields.

**`POST /api/demos/ingest`** (basic auth). Body
`{"demos": [{avoma_uuid, rep, start_at, title, invitee_names, invitee_emails}]}`.
Per record: derive `month` from `start_at` (`"%B %Y"`); **upsert keyed on
`avoma_uuid`**, but the conflict update runs **only when the existing row has
`manually_edited = 0` AND `excluded = 0`** — so human corrections and exclusions
are never clobbered or resurrected. Validate/skip malformed. Returns
`{inserted, updated, skipped}`.

**Editable demo endpoints** (basic auth), backing the dashboard UI:
- `GET /api/demos` — list demo rows (id, date, rep, prospect, title, excluded,
  source) for management; current-month default with an all-time option.
- `POST /api/demos/{id}/update` — set rep and/or prospect/date/title; sets
  `manually_edited = 1`.
- `POST /api/demos/{id}/exclude` — toggle `excluded` (soft-delete/restore).
- `POST /api/demos` — manual add (date, rep, prospect, title); stored with
  `avoma_uuid = NULL`, `manually_edited = 1`.

**Counts/charts exclude soft-deleted rows:** the demo queries in `/api/pipeline`
and `/api/metrics/snapshot` add `WHERE COALESCE(excluded,0) = 0`.

**`sync-all` stops fetching demos from the sheet:** keep the onboarding ingest in
the pipeline step, drop the `fetch_demos.py` call. Demos come only from
`/api/demos/ingest` and manual adds. The 230 historical demos already in the DB
are preserved; Avoma covers the cutover month forward (no overlap).

## Dashboard UI (OS-Metric-Sync)

Add a **Demos** table to the dashboard (Pipeline section or its own): one row per
demo — date, rep, prospect, title — with inline controls for the four edits:
reassign/set rep (dropdown of the 5 + Unassigned), exclude/restore (toggle, shows
excluded rows greyed), edit details (date/prospect/title), and an "Add demo" form.
Each control calls the matching endpoint above; the table refreshes from
`GET /api/demos`. Excluded rows are visible but visually marked and not counted.

## chief-of-staff changes (detector)

1. **Generalize the shared Avoma fetch to match reps by name.** Add an optional
   name-roster path to `fetch_recent_meetings` (opt-in; email-only default
   unchanged). `avoma_sync.py` opts in — also hardening its Slack reporting
   against missing rep emails.
2. **`resolve_demo_rep(speakers, attendees, roster) -> canonical_name | None`** —
   `is_rep` speaker name primary, attendee fallback, normalized full-name /
   last-name token match; no match → `None` (→ `Unassigned`).
3. **Demo detection + push** hooks into nightly `scripts/avoma_sync.py`: filter
   to `call_type=='demo'` AND `os_interested` AND rep ∈ the 5, map to records,
   push via `metrics_client.push_demos(base_url, password, demos)` (non-fatal;
   next night re-pushes idempotently).
4. **Config:** a `demos.rep_roster` block (the 5, name + variants) so the
   demo-counting set is explicit and separate from the 6-rep `sales_rep_emails`.
5. **meeting-prep folded in:** `processors/meeting_prep.py`'s "Demos MTD" line
   sources the count from the engine snapshot (`metrics_client`), replacing the
   dead-sheet `fetch_demos_mtd` read. Sales MTD line is untouched.

## Dedup, cadence & resilience

- **Dedup by `avoma_uuid`** (engine upsert) — re-pushing a call is a no-op.
- **Cadence:** nightly on the existing Avoma cron; a **72h rolling lookback** so
  a missed night self-heals (overlap harmless via UUID dedup).
- **One-time backfill:** a script runs a ~35-day lookback once at ship time to
  populate the current month.

## Error handling

All failure modes non-fatal/self-healing: engine unreachable on push → next
night re-pushes; Avoma/Claude failure on a call → skipped (existing behavior);
rep unmatched → `Unassigned`; ingest validates/skips malformed records; edit
endpoints validate the demo id and return 404 on miss.

## Testing

- **chief-of-staff:** unit-test `resolve_demo_rep` (is_rep match, attendee
  fallback, name variants, no-match→None), the demo filter (call_type /
  os_interested / rep ∈ 5, Quinn excluded), the transcript→record mapping,
  `metrics_client.push_demos` (happy + engine-down non-fatal), and the
  meeting-prep demo line sourcing from the snapshot.
- **engine:** unit-test `POST /api/demos/ingest` (insert, upsert-dedup by uuid,
  **upsert skips rows where manually_edited or excluded**, month derivation,
  malformed skip); the edit endpoints (update sets manually_edited; exclude
  toggles + drops from count; manual add with uuid NULL); and that
  `/api/pipeline` + `/api/metrics/snapshot` exclude `excluded` rows.
- **contract:** one shared fixture so the record shape chief-of-staff sends
  matches what the engine ingest expects.

## Out of scope (noted follow-ups)

- Backfilling demo history for the gap between the calendar feed stopping (~April)
  and the Avoma cutover — left as gaps.
- Deleting the legacy `1iaM` / Conversions spreadsheets — kept as historical
  artifacts.
