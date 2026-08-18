# GTM Producer — Deal Store & Resolution (Phase 1a) — Design

**Date:** 2026-08-18
**Project:** chief-of-staff
**Status:** Design (ready for implementation plan)
**Parent outline:** `2026-08-17-gtm-producer-side-outline.md`
**Consumer contract:** OS-Metric-Sync `2026-08-17-gtm-data-foundation-direction.md`
**Tracked:** Registry project `gtm-producer-deal-data-foundation`

## 1. What this is

The producer-side deal data layer for Chief of Staff. CoS collects deal facts
from feeds, resolves them into a clean **email-keyed deal record** (deduped,
event-sourced), and hands the clean result to two consumers: the CoS runtime
(via the existing `pipeline_cache.json`) and OS-Metric-Sync (via a direct push).

**Key decision (Phase 1a brainstorm, 2026-08-18): Notion is retired from the
deal data path.** It was the only fragile component (manual, rate-limited, a weak
resolution store) with exactly one user (Trent) for exactly one purpose (status
reports). Its role splits into two things CoS already owns well: a git-anchored
Registry store for the data, and the Registry UI for the human view.

Three confirmed choices this design rests on:
1. **Event-sourced storage** — append-only event log, deals derived by folding.
2. **Clean derived status vocabulary** — computed from events, never hand-set.
3. **Direct push to OMS** — `push_deals()` → `/api/deals/ingest`, like demos.

## 2. Architecture

```
Feeds                          Resolution (CoS-owned)               Consumers
─────                          ──────────────────────               ─────────
Avoma demos (emails ✅)  ─┐
Gmail trial proxy        ─┼─► normalize ─► data/deal_events.jsonl
Sales sheet (+email col) ─┘   (DealEvents)   (append-only,
                                              merge=union)
                                                   │
                                                   ▼  fold per normalized email
                                              build_deals()  ◄─ data/deal_crosswalk.json
                                                   │            (manual email↔account fixes)
                                                   ├─► project ─► data/pipeline_cache.json ─► brief / meeting-prep /
                                                   │              (today's exact shape)        query-tools / … (unchanged)
                                                   ├─► Registry UI pipeline view (human/reporting surface)
                                                   └─► push_deals() ─► OMS /api/deals/ingest ─► OMS deals spine
```

**Why event-sourced.** Folding events per normalized email makes the outline's
three hard requirements fall out for free: dedup-by-email (the group key),
event-sourced dates (min/first of the relevant event kind), and order-independent
upsert (the fold is commutative — trial-then-demo and demo-then-trial converge).
It also keeps provenance (every derived field traces to the event that set it),
which a mutable store loses. It matches the existing `tasks.jsonl` pattern.

## 3. Components (each independently testable)

### 3.1 `lib/deal_events.py` — the event store
- `DealEvent` dataclass: `event_id, email, email_raw, kind, timestamp,
  account_name, rep, source, payload`. `kind ∈ {demo, trial, sale, status, manual}`.
- `event_id` = deterministic hash of `(kind, source-native id, email)` so
  re-runs are idempotent (re-appending the same fact is a no-op on fold).
- `append_events(storage, events)` — append new (unseen `event_id`) rows to
  `data/deal_events.jsonl` via `registry_storage`. Depends on: storage only.

### 3.2 `lib/email_norm.py` — normalization (pure)
- `normalize_email(raw) -> str | None`: lowercase, trim, strip `+tags`, drop
  `@teambuildr.com` (internal), return `None` for empty/internal. No deps.

### 3.3 Feed normalizers — raw → `list[DealEvent]` (one per feed, pure)
- `normalize_demo_events(transcripts)` — from `AvomaTranscript.attendees`
  (Phase 0 landed the emails). **Multi-email policy (see §5).** kind=`demo`,
  `timestamp = start_at`, rep from `resolve_demo_rep`.
- `normalize_trial_events(gmail_threads)` — Gmail intro-email proxy → kind=`trial`,
  `source="gmail-proxy"` (flagged so HubSpot can supersede later). *(Follow-on.)*
- `normalize_sale_events(sheet_rows)` — Sales Tracker **after the email column
  exists** → kind=`sale`, carries `close_date`. *(Follow-on — task t-3be14a.)*

### 3.4 `lib/deal_fold.py` — build_deals (pure, the heart)
- `build_deals(events, crosswalk) -> dict[email, Deal]`. Groups by normalized
  email, folds each group into a `Deal`:
  - `demo_date` = min timestamp of demo events; `trial_start_date` = min trial;
    `cycle_start` = `min(trial_start_date, demo_date)`.
  - `close_date`/`outcome` from sale events; `outcome ∈ {open, won, lost}`.
  - `account_name`/`rep` = most recent non-empty; crosswalk overrides account.
  - `stage` (derived, human) = `demoed → in_trial → won | lost`; `stale=true`
    when `outcome=open` and aged past threshold (§5).
  - `contact_emails` = all prospect emails seen for this deal.
  - `provenance` = per-field source flags (e.g. `trial_start:gmail-proxy`).
- Depends on: nothing (pure over its inputs).

### 3.5 `lib/deal_crosswalk.py` — email↔account_name
- Built from events; `data/deal_crosswalk.json` holds manual corrections that win
  over derived values. Bridges email-keyed deals to name-keyed MRR/churn sheets.

### 3.6 `lib/deal_projection.py` — deals → pipeline_cache.json
- `deals_to_pipeline_cache(deals) -> dict` emitting **today's exact cache shape**
  (`{fetched_at, leads:[{page_id, name, contact, email, status, priority,
  last_contacted, days_since_contact, estimated_value, source, stale}]}`).
  Field mapping: `page_id` = synthetic `deal:{email}`, `name` = account_name,
  `email` = key, `status` = derived stage, `estimated_value` = deal_value,
  `last_contacted` = latest event timestamp, `stale` = derived. This is the
  **projection seam** — every existing consumer stays untouched.

### 3.7 `lib/metrics_client.push_deals()` — OMS transport
- `push_deals(base_url, password, deals)` → `POST /api/deals/ingest`. Non-fatal,
  idempotent (OMS upserts by email; never clobbers manually-edited rows — same
  contract as `/api/demos/ingest`). OMS endpoint = task t-78bb8e (their side).

### 3.8 Orchestration — `scripts/deal_sync.py` (or fold into `avoma_sync.py`)
- Run order: normalize feeds → `append_events` → `build_deals` → write
  `pipeline_cache.json` (projection) → `push_deals`. Commits `deal_events.jsonl`
  + `pipeline_cache.json` back per the Data-Persistence rules. Scheduled daily on
  the existing cron footprint (after Avoma fetch).

### 3.9 Registry UI pipeline view — task t-a43140
- A read view over `build_deals()` output: deals by stage/rep, counts, stale
  flags — Trent's reporting surface replacing the Notion pipeline DB. Design
  detailed in its own task; this spec only guarantees the data is available.

## 4. Data flow (demo spine, end to end)

1. Nightly Avoma fetch produces `AvomaTranscript`s carrying `attendees` (Phase 0).
2. `normalize_demo_events` → demo `DealEvent`s (email-keyed).
3. `append_events` adds unseen events to `deal_events.jsonl`.
4. `build_deals` folds all events → current deals.
5. Projection writes `pipeline_cache.json`; `push_deals` sends to OMS.
6. Brief / meeting-prep / Registry UI read as before; OMS reports funnel metrics.

## 5. Decisions that need validation against real data

- **Multi-email demo policy.** Real demos carry several prospect emails (e.g.
  Estacada ×5, same domain = one account). Proposed: within a single demo,
  **collapse same-domain attendees to one deal** keyed by a deterministic primary
  email (organizer/booker if identifiable, else first external), retaining the
  rest as `contact_emails`; **cross-demo merge on any shared contact email**;
  flag ambiguous cases (mixed domains, generic inboxes) for review rather than
  guessing. This is the highest-risk heuristic — validate against a sample of
  real demos before trusting the conversion counts.
- **Stale/lost thresholds.** Proposed: `outcome=open` + `cycle_start` aged
  > N days → `stale=true`; trial-expired or aged > M days with no close →
  `outcome=lost`. N/M to be set from observed cycle length (~45-day cycle per
  OMS foundation doc). Document the rule; never let "open forever" pollute cohorts.

## 6. Error handling
- Every stage non-fatal/self-healing: feed failure → skipped (existing behavior);
  fold is pure and total; projection failure leaves the prior `pipeline_cache.json`
  in place; `push_deals` engine-unreachable → next run re-pushes (idempotent).
- Normalization drops (no resolvable email) are counted and surfaced, never
  silently swallowed — a deal with no email violates the contract and must be
  visible, not discarded.

## 7. Testing
- `normalize_email` — tagging, casing, internal-domain drop, empties.
- `normalize_demo_events` — multi-email collapse, rep resolution, timestamp.
- `build_deals` — dedup by email, order-independence (shuffle events → same
  result), cycle_start = min, outcome/stage derivation, stale flag, crosswalk
  override.
- `deals_to_pipeline_cache` — output matches the current cache schema exactly
  (guard against consumer breakage).
- `push_deals` — happy path + engine-down non-fatal.
- One shared fixture for the record shape CoS sends vs what OMS ingest expects.

## 8. Scope
**In (Phase 1a implementation):** event store, `normalize_email`, demo
normalizer, `build_deals`, crosswalk (derived + override), projection to
pipeline_cache, `push_deals`, orchestration for the **demo spine**.

**Follow-on (tracked tasks, not this build):** trial normalizer (Gmail proxy →
HubSpot), sale normalizer (needs sheet email column), Registry UI pipeline view,
data-health/reconciliation layer, backfill of the 111 Notion records, migrating
consumers off `pipeline_cache.json` (the deferred seam-removal, t-d0d636).

## 9. Open questions
- Multi-email policy and stale/lost thresholds (§5) — validate before trusting metrics.
- Exact `/api/deals/ingest` request/response shape — co-design with OMS (t-78bb8e).
- Does `deal_sync` run as its own job or fold into `avoma_sync.py`? (Ordering vs
  separation-of-concerns; lean toward a separate job for a clean failure boundary.)
