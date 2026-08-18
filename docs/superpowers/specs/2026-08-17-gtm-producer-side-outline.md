# GTM Producer Side — Construction Outline (Chief of Staff)

**Date:** 2026-08-17
**Project:** chief-of-staff
**Status:** Scoping outline (NOT a build-ready plan — needs its own brainstorm)

> This outline is derived from the consumer-side contract defined in
> OS-Metric-Sync (`docs/superpowers/specs/2026-08-17-gtm-data-foundation-direction.md`).
> Chief of Staff is the **producer**: it makes the GTM data *true* — collected,
> resolved, deduped, current — so OS-Metric-Sync can ingest and report it.
> Parts that depend on systems not yet accessible (HubSpot, Stripe/Zoho) are
> marked; those need their own design pass once connectors are live.

## 1. The job in one sentence

Keep a **clean, current, email-keyed deal record** for every OS prospect —
sourced from *events at their origin*, not manual entry — and project it into
the Notion pipeline (the shared handoff surface OS-Metric-Sync ingests).

## 2. The contract to satisfy (from OMS)

Grain: one deal. Key: **email**.

| Field | Required for v1? | Source CoS pulls from |
|---|---|---|
| `email` | Required | demo feed / HubSpot |
| `account_name` | Required | pipeline / demo / sale |
| `rep` | Required | demo feed (Avoma rep resolution) / pipeline |
| `status` | Required | derived from events |
| `demo_date` | Required (demo-first) | Avoma/Calendly |
| `trial_start_date` | Deferred → HubSpot | HubSpot (Gmail proxy meanwhile) |
| `close_date` | Required for velocity | Sales Tracker sheet (Stripe/Zoho later) |
| `outcome` | Required | derived (won/lost/open) |
| `source` | Deferred → HubSpot | HubSpot |
| `deal_value`/`mrr` | Deferred | sheet / Stripe |
| `lost_reason` | Optional | pipeline / transcript |

**Cleanliness guarantees CoS must uphold:** (1) every deal has an email;
(2) one deal per email (deduped); (3) dates are event-sourced, never derived
from manual Notion card movement.

## 3. What already exists in CoS (build on these)

- `collectors/avoma.py` — `fetch_recent_meetings`, `resolve_demo_rep`,
  transcript fetch + Claude analysis. **The demo feed.**
- `collectors/sheets.py` — `fetch_sales_mtd`, `fetch_demos_mtd`,
  `fetch_cancellations_mtd`. **Sale + sheet feeds.**
- `collectors/gmail.py` — `fetch_threads_for_attendee`. **Trial intro-email
  proxy.**
- `collectors/notion_pipeline.py` — `sync()` (read-only pull → cache),
  `inspect()`. **Pipeline read.**
- **`notion-os-pipeline-updater` skill** — already looks up a lead, infers
  status from a call outcome, updates Last Contacted/Status, and creates a
  record if missing. **The write mechanism to build on.**
- GTM Data Contract Doc 0 — canonical source definitions for leads/demos/
  sales/late-stage/churn.

The gap is **not** feeds or write access — it's the systematic resolution,
upsert, write-back, and health layer that ties them together reliably.

## 4. Components to construct

### 4.1 Feed normalizers (event ingestion → typed events)
Wrap each existing collector to emit a uniform `DealEvent {email, name,
account, rep, kind, timestamp, payload}`:
- **Demo event** — from Avoma/Calendly. Filter the rep's own `@teambuildr.com`
  address off invitee lists. Earliest demo per email = `demo_date`.
- **Trial event** — HubSpot when live; until then, Gmail intro-email proxy
  (detect Trent's intro emails to new trial accounts → email + date). Mark
  proxy-sourced so it can be upgraded later.
- **Sale event** — Sales Tracker sheet. **Requires the new email column** on the
  sheet to key the sale to a deal. Stripe/Zoho later for authoritative dates.
- **Status signal** — read current Notion state to reconcile against.

### 4.2 Identity / entity-resolution layer (the heart of robustness)
- Email normalization (lowercase, strip `+tags`, drop internal domains).
- **Dedup: one deal per normalized email.** Merge events onto the same deal.
- **email ↔ account_name crosswalk** — so email-keyed deals bridge to the
  name-keyed MRR/Cancellations sheets. Maintain and persist it.
- Fuzzy fallback (name/company) only when email is absent — flag these for
  review rather than silently guessing.

### 4.3 Deal upsert / state machine
- Upsert **by email**, idempotent and **order-independent** (trial-then-demo and
  demo-then-trial converge on one deal).
- Stamp `demo_date`, `trial_start_date` as their events arrive; derive
  **cycle-start = min(trial_start, demo_date)**.
- On sale event → `outcome=won`, stamp `close_date` **from the sale** (not a
  Notion drag), advance status to Closed.
- Stale/lost rules (e.g., no close + aged beyond threshold, or trial expired) →
  `outcome=lost`. Document the rule; don't let "open forever" pollute cohorts.

### 4.4 Notion write-back (the human surface)
- **Schema additions to the pipeline DB:** add `Demo Date` and `Trial Start
  Date` date properties (today it has Added / Expected Close / Date Closed /
  Last Contacted but no demo or trial-start date).
- One-way **CoS → Notion**: create cards at "Demo Scheduled" when a demo is
  booked (fixes the empty early-funnel stages), advance status, stamp dates.
- Persist a **Notion page-id ↔ email** map for idempotent updates; handle Notion
  rate limits.
- Write structured fields only; **don't clobber human free-text notes.**
- Reuse/extend the `notion-os-pipeline-updater` skill as the write primitive.

### 4.5 Canonical CoS state + projection
- CoS keeps its own resolution state (dedup index, crosswalk, event log) as the
  source of resolution truth; **projects the clean result into Notion**, which
  is the handoff surface OMS ingests. (Notion is a weak store for the resolution
  logic itself — keep that logic in CoS state.)

### 4.6 Data-health / reconciliation (don't assume cleanliness — measure it)
- A recurring validator that reports contract violations: deals missing email,
  duplicate emails, dates that look manually entered, stale opens.
- A fill-rate / health report (like the pipeline audit that kicked this off) so
  regressions are visible.
- Surface violations to Trent (brief/Slack) for the handful that need a human.

### 4.7 Scheduling
- Add a pipeline-sync routine to the existing cron footprint. Run **daily**
  (ideally near-real-time on demo booking) so deals enter "as close to the
  cycle-start date as possible" — the original goal.

## 5. Backfill
Reconstruct historical deals best-effort from: existing Notion pipeline (111
records), the conversion sheet (~456 demo rows with outcomes), and the demos
feed. Flag as approximate; needed so cohort-conversion has history.

## 6. Suggested phasing
1. **Demo-first path, end to end:** demo event → resolve → upsert → write-back →
   OMS ingest. Proves the spine with the fully-accessible feed.
2. **Sale close:** add sheet email column → sale event → close_date + won.
3. **Health layer + backfill.**
4. **Trial path:** Gmail proxy now; swap to HubSpot when the connector lands.
5. **Enrichment:** source, deal value (HubSpot/Stripe).

## 7. Open questions for a CoS-side brainstorm
- How is a HubSpot trial event actually shaped/accessed once connected? (Drives
  4.1 trial + 4.5 enrichment.)
- Exact stale/lost rule thresholds.
- Does CoS's resolution state live in a new SQLite DB, JSON state (existing
  `data/state/` pattern), or elsewhere?
- Reliability of the email→account_name crosswalk for the MRR/churn bridge.
- How much historical backfill is worth the effort vs. starting clean.
