# Metric Sync Overseer — Design

**Date:** 2026-06-16
**Status:** Approved (design); pending implementation plan
**Spans two repos:** `OS-Metric-Sync` (engine) and `chief-of-staff` (overseer)

## Problem

Metrics are currently computed in two places that have drifted into competing
definitions of the same numbers:

- **OS-Metric-Sync** — a FastAPI + SQLite + Chart.js dashboard (Railway), with
  ARR/revenue/retention/pipeline/bugs sections and projection math. Refresh is
  manual (button clicks); it has no cron.
- **chief-of-staff** — a lighter GTM layer (`lib/gtm_metrics.py`) with 6 metrics
  and breach detection that feeds the 7am brief. Runs automatically via GitHub
  Actions.

Concrete drift today:
- Both repos read the **same** cancellations sheet (`1BYMMVKw...`) and recompute
  churn differently.
- Demos was defined two ways (calendar events vs. sheet rows).
- Targets disagree and live in two places (CoS config vs. OS-Metric-Sync
  hardcoded values).
- `leads_mtd` in chief-of-staff is dead — no source ever populated it.
- `scripts/gtm_dashboard.py` reads a `gtm_snapshot.json` that nothing writes.

"Dial in the metrics" cannot be done twice independently — that duplication is
what created the drift. We need **one canonical definition per metric, in one
place**, and a clean contract between the two systems.

## Decision

**OS-Metric-Sync is the metric engine; chief-of-staff is the overseer.**
(Direction chosen for elegance and to avoid bloating chief-of-staff into a
"Frankenstein repo"; a full merge was explicitly ruled out.)

- **OS-Metric-Sync** owns metric computation, storage (SQLite), targets, and the
  dashboard UI. It is the single place a metric is defined.
- **chief-of-staff** stops computing metrics from raw sources. It **drives** the
  sync, **monitors** freshness/failures, **consumes** the computed numbers, and
  **narrates/alerts** in the brief + Telegram. This is the literal "overseer"
  role.

Computation lives in exactly one place. chief-of-staff never re-derives a metric
from raw sheets again — it only consumes, judges, and narrates.

## Architecture & data flow

```
  EXTERNAL SOURCES                OS-METRIC-SYNC (Railway)            CHIEF-OF-STAFF (GitHub Actions)
  ┌──────────────┐               ┌────────────────────────┐         ┌──────────────────────────────┐
  │ Google Sheets │──fetch_*.py──▶│ SQLite (canonical store)│         │  metrics_client.py            │
  │ (sales/demos/ │               │  ↑ math: ARR, churn,    │         │   1. POST /api/sync-all  ─────┼──┐
  │  cancels)      │              │    pace, projections    │◀────────┼───(overseer drives refresh)   │  │
  │ Notion (bugs/  │──fetch_*.py──▶│                         │         │   2. GET /api/metrics/snapshot│  │
  │  onboarding)   │              │ GET /api/metrics/snapshot│────────▶│   3. cache last-good (git/R2) │  │
  └──────────────┘               │ POST /api/sync-all       │         │   4. breach/narration brain   │  │
                                  │ + existing dashboard UI  │         │   5. → brief + Telegram alerts│  │
                                  └────────────────────────┘         └──────────────────────────────┘  │
                                            ▲___________________________________________________________┘
```

**Connection mechanism: live HTTP contract with cached fallback** (chosen over a
shared R2/git snapshot file — a cross-repo R2 bridge would re-introduce the
silent no-op failure mode already documented in the R2-vs-git split).

**Daily flow:** chief-of-staff's existing pre-brief GitHub Action (~6:45am CDT)
calls `POST /api/sync-all` → OS-Metric-Sync re-pulls all sources into SQLite and
returns a sync report → chief-of-staff calls `GET /api/metrics/snapshot` →
caches it to git/R2 as last-good → runs its own breach/pace logic on the
canonical numbers → injects flags into the 7am brief. If Railway is unreachable,
it reads the cached snapshot and prepends a staleness warning. OS-Metric-Sync's
dashboard is unchanged — the charts are now also automatically fresh because
something finally drives the sync.

## Canonical metric contract

One definition, one source, one target per metric — owned by OS-Metric-Sync,
serialized in the snapshot. There is **no separate leads metric**: demos is the
top-of-funnel number (the user does no separate lead counting). The funnel is
**Demos → Closes → Net-new MRR → ARR**, with churn/onboarding/bugs as health
signals.

| Metric | Canonical source | Definition | Target | Freshness |
|---|---|---|---|---|
| **Demos MTD** *(top of funnel)* | KPI/analytics **sheet** (calendar = optional feeder) | Count of demo rows this month | 30/mo | warn >3d |
| **Sales MTD (Closes)** | Sales sheet | Count of closed-deal rows this month | 15/mo | warn >3d |
| **ACV** | Sales sheet | AVG(price) of closes | $200 | with sales |
| **Net-new MRR MTD** | Sales − Cancellations | new_mrr − churn_mrr | $2,000/mo | with sales |
| **MRR / ARR** | Manual entry (`mrr_history`) | latest MRR; ARR = MRR×12 | $1M ARR goal | warn if month unlogged |
| **Monthly churn rate** | Cancellations + active-accounts (read once) | (avg monthly cancels) / total_active × 100 | 1.0% | warn >7d |
| **Churn count MTD** | Cancellations sheet | count this month | red-flag if >2 | warn >7d |
| **Churn reason cluster** | Cancellations sheet | same reason ≥2× in 30d | red-flag on cluster | warn >7d |
| **Onboarding coverage** | Notion onboarding (read by engine) | active records (In Progress + Awaiting + Ready) | red-flag if <5 | warn >2d |
| **Open / high-pri / in-progress bugs** | Notion bug tracker | status counts | display only | warn >2d |

Notes:
- The cancellations sheet (currently read by **both** repos) is read in exactly
  one place — OS-Metric-Sync — and chief-of-staff consumes the computed result.
- Breach **targets/thresholds** live in OS-Metric-Sync config and travel inside
  the snapshot. chief-of-staff drops its own `gtm` target block — single home,
  no two-places-to-edit.
- Demos source of truth is the **sheet**, not the calendar. `sync.py`'s
  calendar→sheet sync becomes an optional feeder into that sheet, not the metric
  source.
- The Demos→Closes conversion rate falls out for free (15/30 = 50% target) — a
  more honest leading indicator than a phantom lead count.

## OS-Metric-Sync changes (the engine)

Mostly additive; dashboard and existing endpoints stay untouched.

1. **New `GET /api/metrics/snapshot`** — one consolidated, versioned read
   endpoint returning the full canonical contract: each metric's `value`,
   `target`/`threshold`, the raw inputs chief-of-staff needs for pace math
   (current count + business-days elapsed), and a per-source `freshness` block
   (`last_synced_at`, `source`, `ok`). Composes math already in `/api/arr`,
   `/api/revenue`, `/api/retention`, `/api/pipeline` — does not reinvent it.
2. **New `POST /api/sync-all`** — runs every `fetch_*` + ingest in sequence,
   writes to `scrape_log`, returns a structured report
   (`{source, status, rows, error}` per source). Same work as the per-section
   refresh buttons, orchestrated and reported.
3. **Targets/thresholds → config.** Values hardcoded in `/api/arr` move into one
   config block (e.g. `gtm_targets`) that the snapshot serializes.
4. **Auth.** Both new endpoints accept the same token chief-of-staff holds as a
   GitHub Secret (reuse existing `DASHBOARD_PASSWORD`/bearer mechanism).
5. **Onboarding read moves here.** OS-Metric-Sync becomes the single onboarding
   reader (it already reads onboarding from Notion).

## chief-of-staff changes (the overseer)

1. **New `lib/metrics_client.py`** — the only thing that talks to
   OS-Metric-Sync: `trigger_sync()` → `POST /api/sync-all`; `fetch_snapshot()`
   → `GET /api/metrics/snapshot`; caches last-good to git/R2; on failure returns
   cached + `stale=True`. Mirrors the existing Pinecone "auto" fallback pattern.
2. **Repoint `lib/gtm_metrics.py`.** Keep the brain — `pace_breach`,
   `redflag_breach`, `evaluate_metrics`, the narration framing ("pipeline is the
   lever"). Change only the input: it receives canonical values from the
   snapshot instead of calling sheets. Targets come from the snapshot.
3. **Delete the duplicate pulls.** Remove the demos/sales/cancellations reads in
   `collectors/sheets.py`, the dead `leads_mtd` path, the orphaned
   `scripts/gtm_dashboard.py` + phantom `gtm_snapshot.json`, and the
   chief-of-staff onboarding collector (engine reads it now).
4. **Wire into `pipeline.py`.** Where it calls `evaluate_metrics` today, it
   instead does: `trigger_sync()` → `fetch_snapshot()` →
   `evaluate_metrics(snapshot)` → flags into the brief. Net fewer moving parts.

## Error handling, freshness & failure alerting

- **Sync failure surfacing.** `sync-all`'s per-source report is consumed by
  chief-of-staff; any source with `status=error` becomes a brief line and a
  Telegram alert ("⚠️ revenue sync failed: <error>"). Today a failed sync is
  silent — this is a real upgrade.
- **Staleness.** Each metric carries source freshness; chief-of-staff warns (not
  errors) when a source exceeds its threshold (3d/7d/2d per the contract),
  reusing the >7d pipeline-cache warning pattern.
- **Graceful degradation.** Railway unreachable → brief uses cached snapshot +
  "metrics as of <timestamp>" banner. Never a hard fail.
- **No phantom zeros.** Empty source → "no data," distinct from a real 0 (the
  existing leads-source principle, applied across the board).

## Testing

- **OS-Metric-Sync:** unit-test the `/api/metrics/snapshot` shape (every metric
  present, freshness block well-formed) and `/api/sync-all`'s report structure
  incl. a failing-source case. Extend the existing pytest suite; math is already
  covered by `test_arr.py` et al.
- **chief-of-staff:** `metrics_client` tests for three paths — happy fetch,
  Railway-down → cached fallback with `stale=True`, malformed snapshot →
  degrade not crash. Repoint `test_gtm_metrics.py` fixtures from raw-sheet
  inputs to snapshot inputs (breach logic unchanged, assertions largely carry
  over).
- **Contract test:** one shared canonical-snapshot JSON fixture both repos test
  against, so the interface can't drift silently. This is the guardrail that
  prevents re-creating today's problem.

## Phasing

Sequenced so each phase is independently shippable and nothing breaks mid-flight.

1. **Phase 1 — Engine surface.** Add `/api/metrics/snapshot`, `/api/sync-all`,
   move targets to config in OS-Metric-Sync. Old chief-of-staff path still runs
   untouched. Ship + verify endpoints in isolation.
2. **Phase 2 — Consumer.** Add `lib/metrics_client.py` + cached fallback,
   repoint `evaluate_metrics` to the snapshot, wire `pipeline.py`. Run both old
   and new paths in parallel for a few days; diff the numbers to prove the
   contract matches reality.
3. **Phase 3 — Cutover & delete.** Once parallel-run agrees: delete duplicate
   sheet/onboarding collectors, dead `leads_mtd`, orphaned `gtm_dashboard.py`,
   and chief-of-staff's `gtm` target config. Move onboarding read to the engine.
4. **Phase 4 — Overseer polish.** Sync-failure Telegram alerts, staleness
   banners, freshness thresholds.

The Phase-2 parallel-run is the safety net: the new pipe isn't trusted until it
produces the same numbers as the old one.

## Out of scope

- Re-styling or restructuring the OS-Metric-Sync dashboard UI.
- StoryBuildr (separate aspirational feature in OS-Metric-Sync).
- Multi-user / team-scale concerns (chief-of-staff BACKLOG M1/M2).
- Automating manual MRR entry (stays a manual form for now).
