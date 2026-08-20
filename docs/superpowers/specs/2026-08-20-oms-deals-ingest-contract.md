# OMS `/api/deals/ingest` — Producer/Consumer Contract

**Date:** 2026-08-20
**Producer:** chief-of-staff (`lib/metrics_client.push_deals`, driven by `lib/deal_sync.refresh_deal_store`)
**Consumer:** OS-Metric-Sync (the Railway metric engine) — endpoint to be built there (task t-78bb8e)
**Status:** Contract (authoritative on the producer side; the OMS spine + endpoint are designed/built in the metric-sync repo against this)
**Related:** `2026-08-18-gtm-deal-store-phase1a-design.md` §3.7 (resolves its open question #2), `2026-06-17-avoma-demo-detection-design.md` (the `/api/demos/ingest` precedent this mirrors)

## 1. Purpose

CoS resolves deal facts into a clean, event-sourced, deal-keyed record and pushes the
**complete current deal set** to the metric engine on every sync run, so OMS can compute
funnel/pipeline metrics (counts by stage, conversion, cycle time) over the whole pipeline.
This is the deal-grain analogue of the live `/api/demos/ingest` push (which is call-grain).

**This document is authoritative for the producer side** — the shapes below are exactly
what `push_deals` already sends today (the push is wired and inert only because CoS has no
`base_url` configured for it yet; see §7). The OMS session designs the deals table/spine and
implements the endpoint to accept this; it must not require the producer to change shape
without updating this contract.

## 2. Transport

- **Method / path:** `POST {base_url}/api/deals/ingest`
- **Auth:** HTTP Basic, username empty, password = the shared engine password
  (`auth=("", password)`) — the **same secret** already used for `/api/demos/ingest`.
- **Request body:** `application/json`, exactly:
  ```json
  { "deals": [ <deal>, <deal>, ... ] }
  ```
- **Idempotent, non-fatal, snapshot-style:** every run sends the **entire current deal
  set** (all `build_deals(...)` values), not a delta. CoS treats any non-2xx or transport
  error as non-fatal (logs, moves on) and re-sends the full set next run, so a missed push
  self-heals. OMS must therefore be safe to receive the same deal repeatedly.

## 3. The `<deal>` object (exact producer shape)

Each element is the `lib/deal_fold.Deal` dataclass serialized with `dataclasses.asdict`.
Fields, types, and semantics:

| Field | Type | Semantics |
|---|---|---|
| `email` | string | **PRIMARY KEY — treat as an opaque unique deal key, not necessarily an email.** Usually a normalized prospect email; may be a synthetic `notion:<page_id>` (name-only backfilled record) or `unresolved:<uuid>` (name-only demo attendee). Upsert on this. |
| `account_name` | string | Derived account/company name; may be `""` for `unresolved:` keys. |
| `rep` | string | Owning rep (e.g. "Luke Martin"); may be `""`. |
| `demo_date` | string \| null | ISO 8601; earliest demo event timestamp. |
| `trial_start_date` | string \| null | ISO 8601; earliest trial (not populated until the trial feed lands). |
| `cycle_start` | string \| null | ISO 8601; `min(trial_start_date, demo_date)` — the funnel-entry date. |
| `close_date` | string \| null | ISO 8601; set from a sale event (not populated until the sale feed lands). |
| `outcome` | string | One of `open` \| `won` \| `lost`. The authoritative win/loss state. |
| `stage` | string | Derived human stage: one of `demoed` \| `in_trial` \| `won` \| `lost`. |
| `contact_emails` | array<string> | All prospect emails seen for this deal (the account's contacts). |
| `source` | string | Provenance source tag; may be `""`. |
| `deal_value` | number \| null | Estimated/closed value in dollars; usually `null` today. |
| `lost_reason` | string | Free text; set only when `outcome == "lost"`. |
| `provenance` | object | Per-field source flags (CoS-internal). OMS may store or ignore. |
| `review` | object | CoS-internal review state `{needs, kind, reason, ...}`. OMS may ignore. |
| `last_event_at` | string \| null | ISO 8601; timestamp of the most recent event on this deal ("last activity"). |

**Minimal set OMS needs for metrics:** `email` (key), `account_name`, `rep`, `stage`,
`outcome`, `cycle_start`, `close_date`, `deal_value`, `last_event_at`. The rest are
carried for completeness/provenance and may be stored opaquely or dropped.

**Enum stability:** `outcome ∈ {open, won, lost}` and `stage ∈ {demoed, in_trial, won,
lost}` are the only values today. New stages (e.g. a future `scheduled`) may appear when
upstream feeds land — OMS should treat an unknown `stage`/`outcome` as pass-through
(store the string, don't crash), not reject the row.

## 4. Upsert semantics (what OMS must do)

Mirror the `/api/demos/ingest` contract:
- **Upsert by `email` (the deal key).** Insert if new, update in place if the key exists.
- **Never clobber a manually-edited OMS row's human fields.** As with demos, if an OMS
  operator has hand-annotated a deal, the ingest must not overwrite those annotations —
  only the CoS-derived fields. (OMS decides which columns are "CoS-owned" vs
  "human-owned"; CoS-owned fields are the ones in §3.)
- **Idempotent:** re-ingesting an unchanged deal is a no-op (same key, same derived
  values → no change).

### Open decision for the OMS side — deletions/disappearance
CoS sends the full current set each run but **sends no explicit delete signal**. A deal
that CoS drops (e.g. resolved as `not_a_deal`, so it vanishes from `build_deals`) simply
stops appearing in the payload. Two options for OMS (pick one, document it there):
- **(a) Upsert-only (simplest, matches demos):** vanished deals linger in OMS until
  manually cleaned. Acceptable for v1.
- **(b) Snapshot reconcile:** because the payload is the *complete* current set, OMS may
  mark any CoS-owned deal absent from a run as removed/stale. More correct, more work.
Recommend (a) for v1; note (b) as a follow-up. CoS does not need to change either way.

## 5. Response shape (what CoS expects back)

CoS calls `resp.raise_for_status()` then `resp.json()` and returns the parsed object
(logged for observability). Any 2xx JSON body is accepted. **Recommended** (mirror demos):
```json
{ "status": "ok", "received": 113, "created": 5, "updated": 108, "skipped": 0 }
```
- Non-2xx → CoS logs `⚠️ Deal push failed (non-fatal)` and retries next run. Return a
  clear error body on failure, e.g. `{ "status": "error", "error": "<reason>" }` with a
  4xx/5xx code.
- Auth failure → `401`. Malformed body (no `deals` array) → `400`.

## 6. Volume & cadence

- **Volume:** ~113 deals today (111 Notion-backfilled + live demos), growing slowly
  (a few demos/day). Payloads are small (single-digit KB to low tens of KB). No pagination
  needed; a single POST per run is fine.
- **Cadence:** once per CoS deal-sync run (currently the nightly `avoma_sync` footprint,
  ~03:00). Not high-frequency.

## 7. Activating the push (CoS side — already built)

`push_deals` and `refresh_deal_store` exist and are tested. The push fires only when a
`base_url` is passed (`if base_url:` in `refresh_deal_store`); today it's unset, so the
push is inert. **To activate once the endpoint is live:** pass the engine `base_url`
(the same Railway URL used for demos) and the existing password into the deal-sync call
site. No new CoS code — just wiring the config value. Coordinate go-live so CoS starts
pushing only after the endpoint accepts the shape in §2–§3.

## 8. Test fixture (shared shape)

A representative payload element for OMS's ingest tests (a backfilled seed-derived deal
and a live demo-derived deal):
```json
{
  "deals": [
    {
      "email": "notion:38a24bca36d78128a418f65bc79d6a86",
      "account_name": "Kim Johnston", "rep": "",
      "demo_date": null, "trial_start_date": null, "cycle_start": null,
      "close_date": null, "outcome": "open", "stage": "in_trial",
      "contact_emails": [], "source": "", "deal_value": null, "lost_reason": "",
      "provenance": {}, "review": {"needs": false}, "last_event_at": "2026-06-24"
    },
    {
      "email": "jcook.tpa@gmail.com",
      "account_name": "", "rep": "Luke Martin",
      "demo_date": "2026-08-18T17:15:00Z", "trial_start_date": null,
      "cycle_start": "2026-08-18T17:15:00Z", "close_date": null,
      "outcome": "open", "stage": "demoed",
      "contact_emails": ["jcook.tpa@gmail.com"], "source": "", "deal_value": null,
      "lost_reason": "", "provenance": {}, "review": {"needs": true, "kind": "ambiguous", "reason": "free_email"},
      "last_event_at": "2026-08-18T17:15:00Z"
    }
  ]
}
```

## 9. Out of scope (for the OMS session's awareness)

- The OMS **deals spine (table/store) does not exist yet** — building it is the bulk of the
  work, not the route. Expect a real sub-project (schema, ingest, metric surfacing, deploy),
  not a one-liner. This contract only fixes the wire boundary.
- CoS-side consumer seam-swap (brief/meeting-prep off `pipeline_cache.json`) is a separate
  CoS task; unrelated to this endpoint.
- No booking-time feed; `trial`/`sale` feeds not yet built — so `trial_start_date`/
  `close_date`/`deal_value` are mostly null today. The contract already carries them so no
  reshape is needed when those feeds land.
