# GTM Sale Event — Sales Tracker → `won` deals (design)

**Date:** 2026-08-20
**Project:** GTM Producer — Deal Data Foundation (`gtm-producer-deal-data-foundation`)
**Task:** `t-3be14a` (Phase 2 unblock: email column on Sales Tracker + wire the sale event)
**Status:** Design (approved) — implementation plan to follow
**Related:** `2026-08-18-gtm-deal-store-phase1a-design.md` (deal store + fold), `2026-08-20-oms-deals-ingest-contract.md` (OMS already carries `close_date`/`outcome`/`deal_value`/`review`), the `normalize_demo_events` → fold → push pipeline this mirrors.

## 1. Purpose

Populate the **won side** of the deal funnel. Today `close_date`, `outcome=won`, and
`deal_value` are effectively never set because no sale feed exists — so conversion rate and
sales-cycle velocity can't compute for closed deals. This wires the **Sales Tracker sheet**
(now carrying a per-sale email column) into the existing event-sourced deal store as a new
`sale` DealEvent kind, folded into `won` deals, flowing to OMS unchanged.

This rides the **exact same rails as demos**: `read sheet → normalize into DealEvents →
append to deal_events.jsonl → deal_fold → push to OMS`. No new transport, no OMS reshape.

## 2. Source: the Sales Tracker sheet

- **Spreadsheet:** `config → <deals block>.sheets.sales_spreadsheet_id`
  (`1pOUxLMX2H48miMvEbgqOXq1C0VHkGm-XXW2VCodQfU0`) — the per-sale tracker, **not** the
  aggregate KPI sheet (`sheets.kpi_spreadsheet_id`) that `gtm_metrics.fetch_sales_mtd` reads.
  (Verify this id is the tracker before wiring — see §9.)
- **Tab:** one tab per month, named `"{Month} {Year}"` (e.g. `August 2026`). The nightly run
  reads **only the current-month tab**. `August 2026` is the earliest tab with the email
  column; earlier months are out of scope until backfilled.
- **Columns (by header, row 1):** `Date` (A, close date) · `Total Sale` (D, dollar amount) ·
  `Customer Name` (E, account) · `Customer Email` (F, **join key**) · `Salesperson` (G, rep).
  Columns are resolved **by header name**, not by letter, so inserted/reordered columns don't
  break the reader.
- **Two in-scope sections, one ignored, delimited by label rows:**
  - Rows 2 → the `Bundle Sales` header: **OS-only** sales (`source="os_only"`).
  - `Bundle Sales` header → the `Trent TB Sales` header: **bundle** sales, OS + Strength
    (`source="bundle"`).
  - `Trent TB Sales` header and everything below: **ignored** (separate tracking).
  - One row = one closed sale. Blank rows within a section are skipped.

## 3. Architecture & components

### 3.1 `lib/sales_sheet.py` (new) — the reader
`fetch_sale_rows(config, today) -> list[dict]`

- Resolve the tab name from `today` (`"%B %Y"` → `August 2026`).
- Read a generous range (`A1:G200`) via the existing Google auth path (`lib/google_auth.py`,
  same credentials `gtm_metrics`'s collector uses).
- Build a column map from row 1 headers.
- Walk rows, tracking section by the last label row seen:
  - before `Bundle Sales` → `os_only`; between `Bundle Sales` and `Trent TB Sales` →
    `bundle`; at/after `Trent TB Sales` → stop.
- Emit one dict per data row: `{date, total_sale, customer_name, customer_email, salesperson,
  source}` (raw strings + section tag). Blank rows skipped.
- **Missing tab** (e.g. first days of a month before it's created) → return `[]` (non-fatal).

Pure of the fold — returns raw rows so it's unit-testable without Sheets.

### 3.2 `normalize_sale_events(rows) -> list[DealEvent]` in `lib/deal_normalize.py`
(beside `normalize_demo_events`)

Per row:
- `email = normalize_email(customer_email)`. If `None` (blank, malformed, or `@teambuildr.com`
  internal) → **skip the row and log** — a sale with no valid external email can't key a deal.
- `timestamp = parse_close_date(date)` → ISO date. Unparseable/blank → **skip** (a close needs
  a date).
- `deal_value = parse_money(total_sale)` → float (strip `$`, commas, whitespace); blank/
  non-numeric → `None`.
- Build `DealEvent(kind="sale", email=email, email_raw=customer_email, timestamp=timestamp,
  account_name=customer_name, rep=salesperson, source=source,
  payload={"deal_value": deal_value})`.
- `event_id = make_event_id("sale", native_id, email)` with
  **`native_id = f"{timestamp}|{email}|{total_sale}"`** — content-based, so re-reading the same
  sheet nightly is a no-op.

### 3.3 `lib/deal_fold.py` — the sale branch (the real gap)
`sale` is already counted in `has_real` but never folded. Add handling in the per-deal fold:

- On a `sale` event: `outcome = "won"`, `close_date = event.timestamp`,
  `deal_value = payload.deal_value` (when present), and record `source`.
- **Multiple sale events for one deal:** apply in log order; the **later-appended wins**
  (`close_date`/`deal_value` overwrite). This lets a corrected sheet row self-heal after
  re-ingest.
- **Precedence:** a terminal `status=lost` event still beats a sale (unchanged — lost is
  terminal). Order of resolution: `lost` > `sale`(won) > open.
- **Unmatched sale flag:** after folding a deal, if its real events are **sale-only** (no
  `demo`/`trial`/`seed`), set
  `review = {"needs": True, "kind": "unmatched_sale", "reason": "sale email matched no demo"}`.
  This catches the email-mismatch case (demo under `john@`, sale under `billing@`) that would
  otherwise silently double-count an account. The deal is still recorded as `won`.
- `cycle_start` is unchanged (`min(trial, demo)`); an unmatched sale-only deal has `cycle_start
  = None`, so it counts toward **won totals** but is correctly excluded from **cycle-velocity**.

### 3.4 `refresh_deal_store` in `lib/deal_sync.py` — wiring
After the existing demo-event append, add a **non-fatal** block mirroring it:
```
try:
    rows = fetch_sale_rows(config, today)
    appended += append_events(storage, normalize_sale_events(rows))
except Exception as e:
    log("⚠️  Sale sync error (non-fatal)", e)
```
Runs in the same nightly `avoma_sync` footprint. No OMS change — the pushed deals already
carry `close_date`/`outcome`/`deal_value`/`review`.

## 4. Data flow

```
Sales Tracker (current-month tab)
  └─ fetch_sale_rows()            → raw row dicts (os_only | bundle)
      └─ normalize_sale_events()  → DealEvent(kind="sale", email-keyed)
          └─ append_events()      → deal_events.jsonl (dedup by event_id)
              └─ deal_fold        → Deal(outcome="won", close_date, deal_value, [review])
                  ├─ deals_to_pipeline_cache → shadow cache (unchanged)
                  └─ push_deals    → OMS /api/deals/ingest (unchanged shape)
```

## 5. Error handling

- Missing/renamed tab → `[]`, logged, non-fatal (self-heals next run once the tab exists).
- Row with no valid email or no parseable date → skipped + logged; never crashes the run.
- Sheet/auth failure → caught in the `refresh_deal_store` block; the rest of the deal refresh
  (demos, projection, push) still completes.
- Idempotent: content-based `event_id` + `append_events` dedup means re-runs are no-ops.

## 6. Testing

- **Reader (`sales_sheet`):** section splitting via the `Bundle Sales`/`Trent TB Sales` labels;
  sections that have grown; blank rows inside a section; ignored rows below `Trent TB Sales`;
  header-based column mapping; missing tab → `[]`.
- **Normalizer:** currency parsing (`$1,200` → `1200.0`, blank → `None`); date parsing to ISO;
  `os_only` vs `bundle` tagging; internal/blank/malformed email → row skipped.
- **Fold:** matched sale → `won` + `close_date`; unmatched sale → `won` + `needs_review`
  (`unmatched_sale`); `sale` then `status=lost` → `lost`; two sale events → later wins;
  sale-only deal → `cycle_start=None` (excluded from velocity, included in won count).
- **Wiring:** a fetched row lands as a `won` deal end-to-end through `refresh_deal_store`
  (Sheets mocked).

## 7. Idempotency & the edit trade-off

`native_id = "{close_date}|{email}|{total_sale}"` makes nightly re-reads no-ops.

**Edit behavior (self-heal).** Editing a sale row *after* ingest yields a *new*
`event_id`, so both the old and corrected sale events live in the log. The fold
resolves them by **append order**: for a given deal, the **last-appended sale
wins** (`build_deals` builds an `ingest_index` from the position of each event in
the append-only `deal_events.jsonl`, and the winning sale is the one with the
highest index). Because a corrected row is always appended *after* the stale one,
the correction self-heals — regardless of whether the close date moved forward,
backward, or not at all (an amount-only fix):
- Correct the **close date** (either direction) → the last-appended event wins,
  its date applies. ✓
- Correct only the **amount** (same close date) → the last-appended event wins,
  its value applies. ✓

The stale sale event remains in the log (harmless); the deal reflects the latest
values. **Order note:** sale-value resolution therefore depends on append order,
which is well-defined for the append-only log (production always folds events in
file order via `load_events`). This is a deliberate, narrow exception to the
fold's otherwise order-independent grouping — append order *is* the authoritative
"latest" signal for an event-sourced store.

## 8. Out of scope

- **Historical months** (pre-`August 2026`): no email column yet; ingest starts at
  `August 2026`. A one-time backfill is a separate task if wanted.
- **`trial` events** (`trial_start_date`): still unbuilt; comes with the HubSpot connector
  (`t-c6b441`), independent of this.
- **Splitting bundle revenue** into OS vs Strength: `deal_value` on bundle rows is the combined
  `Total Sale`, tagged `source="bundle"` so blended revenue is separable downstream. No split
  logic in v1.
- **Consumer seam-swap** (`t-d0d636`): unrelated.

## 9. Open items to verify during implementation

1. **Spreadsheet id:** confirm nested `sales_spreadsheet_id` (`1pOUxLM…`) is this Sales Tracker
   (open the sheet / check a header row), not another sales artifact.
2. **Date format:** confirm column A's actual format (`8/18/2026` vs `2026-08-18` vs a Sheets
   serial) and make `parse_close_date` tolerant of it.
3. **Config key path:** confirm the exact parent key of the nested `sheets.sales_spreadsheet_id`
   block for the reader to read it.
