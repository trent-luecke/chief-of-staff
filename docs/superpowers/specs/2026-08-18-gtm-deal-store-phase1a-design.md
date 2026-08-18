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
  - `stage` (derived, human) = `demoed → in_trial → won | lost`.
  - `contact_emails` = all prospect emails seen for this deal.
  - `provenance` = per-field source flags (e.g. `trial_start:gmail-proxy`).
  - `review` = `{needs, kind, reason, proposed, check_back}` — set when the deal
    is ambiguous (identity) or hits the 45-day mark unresolved. Drives the
    review surface (§3.10, §5). Human decisions are themselves events, so a
    resolved deal clears its flag on the next fold and never re-prompts.
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
  `last_contacted` = latest event timestamp, `stale` = deal is in the 45-day
  review (`review.kind == "stale_check"`). This is the **projection seam**.
  **Phase 1a writes this to a SEPARATE `deal_pipeline_cache.json`, NOT the live
  `pipeline_cache.json`.** The live cache is Notion-populated (a superset of the
  demo-only deal store until backfill lands), so overwriting it in 1a would
  delete real pipeline data that the brief and meeting-prep read. The side file
  is inspectable for validation and exercises the projection path in production;
  the live-cache seam-swap — pointing every consumer at the deal store — happens
  in the backfill phase (t-0867b7), once the deal store is a true superset. Only
  then are "existing consumers stay untouched" guarantees real.

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
- A read view over `build_deals()` output: deals by stage/rep, counts, review
  flags — Trent's reporting surface replacing the Notion pipeline DB. Design
  detailed in its own task; this spec only guarantees the data is available.

### 3.10 Deal review layer — the human-in-the-loop (Phase 1b)
Two review queues over the fold's `review` flags, one surface (Today tab, in a
`deals_to_review` block rendered directly under `meetings`). Every decision is
written back as a DealEvent, so the fold stays the single source of truth.

**Queue A — Identity review** (`kind=ambiguous`). Fold reason codes: `multi_domain`
(external attendees span >1 domain in one demo), `no_email` (name-only attendee,
or the only external addresses were automated senders — see below),
`generic_inbox` (only `info@`/`sales@`/`office@`), `free_email` (prospect is on a
personal domain like gmail.com — a valid key but no derivable account name),
`account_conflict` (new demo email matches an existing deal with a different
account). **Automated / non-prospect senders** (`no-reply@…`, and meeting-platform
domains like `zoom.us`, `calendly.com`) are dropped before keying, so they never
become phantom deals. Each card shows CoS's
best-guess primary (email + account + rep), the reason in plain language, and the
full attendee evidence. Actions → a `manual` DealEvent: **confirm guess** ·
**choose primary** · **split into N deals** · **merge into existing** ·
**not a deal**.

**Queue B — 45-day review** (`kind=stale_check`). Fold flags a deal when
`outcome=open` AND `cycle_start + 45d` reached AND not currently snoozed
(`check_back` unset or ≤ today). **Never auto-Lost.** Actions → a `status`
DealEvent:
- **Lost** (+ optional one-tap reason) → `outcome=lost`.
- **On hold** → prompts for a **check-back date**; sets `review.check_back` to it,
  dropping the deal off review until that date, then it re-surfaces. Stays
  `outcome=open` (still in the pipeline for conversion cohorts).
- **Still active** → deal is progressing; resets the 45-day clock (re-review in
  another ~45 days). Distinct from On hold: "moving" vs "paused."

**Mechanics.** New endpoints `POST /api/deals/<deal_id>/review` (identity
resolution) and `POST /api/deals/<deal_id>/status` (lost / on-hold / active) →
`_write_main` appends the DealEvent to `deal_events.jsonl` on `origin/main`, same
pattern as `/api/tasks`. `registry_ui.html` renders the block + quick actions and
the on-hold date picker. If the email brief still sends, it shows a **read-only
summary + link** ("N deals need review → open Today") — email can't carry working
actions. Idempotent: a resolved flag clears on the next fold.

## 4. Data flow (demo spine, end to end)

1. Nightly Avoma fetch produces `AvomaTranscript`s carrying `attendees` (Phase 0).
2. `normalize_demo_events` → demo `DealEvent`s (email-keyed).
3. `append_events` adds unseen events to `deal_events.jsonl`.
4. `build_deals` folds all events → current deals.
5. Projection writes `pipeline_cache.json`; `push_deals` sends to OMS.
6. Brief / meeting-prep / Registry UI read as before; OMS reports funnel metrics.

## 5. Heuristics and the review loop that backstops them

CoS makes a best-effort automatic call, and **anything uncertain routes to the
review loop (§3.10) rather than being guessed silently.** The heuristics:

- **Multi-email demo policy.** Real demos carry several prospect emails (e.g.
  Estacada ×5, same domain = one account). **Phase 1a auto path (within a single
  demo only):** collapse same-domain attendees to one deal keyed by a
  deterministic primary email (organizer/booker if identifiable, else first
  external), retaining the rest as `contact_emails`. **Cross-demo merge (two
  separate demos that share a contact email → one deal) is deferred to Phase 1b**,
  where it pairs naturally with the Identity-review queue's merge action (Queue A
  handles `account_conflict`). Until then the fold groups strictly by primary
  email, so two demos for one account under different primaries produce two deals
  — acceptable in 1a because nothing live consumes the counts yet (OMS push is
  inert until its endpoint exists; the projection writes a side file). Anything
  the within-demo auto path can't do confidently — mixed domains, name-only
  attendees, generic inboxes — is flagged for **Identity review** (Queue A). This
  is the highest-risk heuristic; validate the auto path against a sample of real
  demos, and treat the review queue as the safety net while it's tuned.
- **45-day stale rule — human-confirmed, never automatic.** `outcome=open` +
  `cycle_start + 45d` reached → the deal enters the **45-day review** (Queue B),
  which asks Trent to mark it **Lost**, **On hold** (with a check-back date), or
  **Still active**. A deal only becomes `lost` when Trent says so — the system
  never silently kills a deal, and "open forever" is prevented by the deal always
  being either progressing, snoozed to a date, or explicitly lost. The 45-day
  figure comes from the ~45-day observed cycle (OMS foundation doc) and is
  configurable.

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

## 8. Scope & phasing
**Phase 1a — the demo spine:** event store, `normalize_email`, demo normalizer
(within-demo multi-email collapse), `build_deals` (incl. `review` flag
computation), crosswalk (derived + override), projection to a **side file**
(`deal_pipeline_cache.json`, not the live cache — see §3.6), `push_deals`,
orchestration. Proves the spine end-to-end with the one fully accessible feed,
without touching live consumer data.

**Phase 1b — the review loop (§3.10) + cross-demo merge:** the `deals_to_review`
block in the Today tab, the identity + 45-day queues, the
`/api/deals/<id>/review` and `/status` endpoints, and **cross-demo account merge
on shared contact emails** (pairs with Queue A's merge action). Identity review
is useful the moment demos flow; the 45-day queue activates as deals age (or
immediately after backfill).

**Follow-on (tracked tasks, later phases):** trial normalizer (Gmail proxy →
HubSpot), sale normalizer (needs sheet email column, t-3be14a), Registry UI
pipeline view (t-a43140), data-health/reconciliation layer, backfill of the 111
Notion records (t-0867b7), migrating consumers off `pipeline_cache.json` (the
deferred seam-removal, t-d0d636).

## 9. Open questions
- Multi-email auto-path accuracy (§5) — validate against real demos before
  trusting conversion counts; the review queue (§3.10) is the backstop meanwhile.
- Exact `/api/deals/ingest` request/response shape — co-design with OMS (t-78bb8e).
- Does `deal_sync` run as its own job or fold into `avoma_sync.py`? (Ordering vs
  separation-of-concerns; lean toward a separate job for a clean failure boundary.)
- New registry files (`deal_events.jsonl`, `deal_crosswalk.json`) must be added to
  the `.gitignore` un-ignore allow-list and the sync job's commit-back `git add`
  (per CLAUDE.md Data Persistence); `deal_events.jsonl` should get the
  `merge=union` driver like `tasks.jsonl`.
