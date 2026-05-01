# P15 — KPI Logging & Raw Data Vector Layer

**Date:** 2026-05-01
**Status:** Design approved, pending implementation
**Prerequisite for:** P16 — Autonomous Vector Wanderer

## Purpose

The vector DB currently holds `observations` (daily signals: pipeline staleness, top priorities, email loops) and `memories` (synthesized `.md` files). Neither contains raw KPI records — individual sales, bugs, cancellations, or pipeline leads as discrete embeddable units.

This is the gap that limits the future wanderer: it can only reason about summaries, not individual records. This feature closes that gap by adding two new data streams on every daily run:

1. **Daily KPI snapshot** — one aggregate observation written to `observations.jsonl` per day
2. **Raw individual records** — each pipeline lead, bug ticket, cancellation row, and sale entry embedded into a new `raw_data` Pinecone namespace

The morning brief retriever is **not modified** — it only queries `observations` + `memories`, so nothing from `raw_data` bleeds into the brief.

---

## Data Sources

### Existing (already collected, not yet logged to vectors)
- **Pipeline leads** — loaded from `data/pipeline_cache.json` (Notion-synced manually)
- **Sales MTD** — `collectors/sheets.py::fetch_sales_mtd()`, Dept Heads KPI sheet
- **Demos MTD** — `collectors/sheets.py::fetch_demos_mtd()`, Dept Heads KPI sheet

### New
- **Bug tickets** — Notion bug tracker DB (`29d24bca-36d7-80ef-b574-000b739e37a8`). Fields: `Ticket Name`, `Status` (Not started / In progress / Done), `Priority Level` (High / Moderate / Low), `Technical Area of Issue` (multi-select), `Date Created`, `Last Update`, `Date Completed`, `Shortcut URL`.
- **Cancellations** — Google Sheets, spreadsheet `1BYMMVKw19Y9pwp7oFYMvUC4Webk-NI-Y-kevj7CX6D4`, tab `MONTHLY Cancellations`. Columns (verified 2026-05-01): Date (M/D, no year), Account Name and #, # of Months paid before Cancelation, Reason for Cancelation, Base Plan Type, Base Plan, Additions, Monetary Value, Answer (customer note), Customer Returned, Number of Months until Customer Returned, Lifetime Value.

No new GitHub Secrets required. Uses existing `NOTION_TOKEN`, `GOOGLE_OAUTH_JSON`, `PINECONE_API_KEY`, `VOYAGE_API_KEY`.

---

## Architecture

```
main.py
  ├── collectors/notion_bugs.py         → List[BugTicket]          (new)
  ├── collectors/sheets.py              → CancellationData          (extended)
  ├── processors/memory_observer.py     → kpi_snapshot observation  (extended)
  └── processors/vector_ingest.py       → raw_data namespace        (extended)
```

### Pinecone Namespaces (after this feature)

| Namespace | Contents | Queried by brief | Queried by wanderer |
|---|---|---|---|
| `observations` | Daily signals + kpi_snapshot | Yes | Yes |
| `memories` | Synthesized `.md` files | Yes | Yes |
| `raw_data` | Individual records | **No** | Yes |

---

## Daily KPI Snapshot (observations namespace)

One `kpi_snapshot` observation written to `observations.jsonl` per day. Deduplicated by date — re-runs do not double-write.

**Text format:**
```
KPI snapshot 2026-05-01: Sales MTD $18,400 (12 deals). Demos MTD: 8. Pipeline: 6 In-Trial / Post Demo, 3 Demo Scheduled, 2 New Lead. Open bugs: 14 (3 High, 8 Moderate, 3 Low). Cancellations MTD: 2.
```

**JSONL record:**
```json
{
  "date": "2026-05-01",
  "type": "kpi_snapshot",
  "entity": "daily",
  "content": "<text above>",
  "source": "kpi",
  "context": "sales_revenue=18400 sales_count=12 demos=8 pipeline_in_trial=6 open_bugs=14 bugs_high=3 cancellations_mtd=2"
}
```

The `context` field carries structured key=value pairs to support future regex/filter queries alongside semantic search.

---

## Raw Record Formats (raw_data namespace)

Each record is embedded as its own vector. Re-embedded only when the record changes.

### Pipeline Lead
```
ID:   lead:{page_id}
Text: Pipeline lead: Tyler Landeck — ALA | status: In-Trial / Post Demo | source: Other | priority: High | 49 days since contact | stale
Meta: name, status, source, priority, days_since_contact, stale, email
Fingerprint: "{status}:{days_since_contact}:{priority}"
```

### Bug Ticket
```
ID:   bug:{notion_page_id}
Text: Bug: Payment widget crashes on iOS | status: In progress | priority: High | areas: OS Mobile App, Payment Processing Error | 12 days open
Meta: title, status, priority_level, technical_areas (list), date_created, days_open, shortcut_url
Fingerprint: last_update ISO timestamp
```

### Cancellation
```
ID:   cancel:{month_day_slug}:{account_slug}
Text: Cancellation: Fast Break SP on 3/16 | reason: Business Changes | base plan: 180/mo | monetary value: $900 | customer note: business needs something that can integrate with their sales and marketing funnels
Meta: date, account_name, months_paid, reason, base_plan, monetary_value, customer_returned
Fingerprint: hash of all non-empty columns
```

### Sale Entry
```
ID:   sale:{date}:{customer_slug}
Text: Sale: Crossfit Meridian on 4/22 | $150 | type: New | salesperson: Trent
Meta: date, total, customer, salesperson, sale_type
Fingerprint: hash of all columns
```

---

## State Tracking

`IngestState` (in `processors/vector_ingest.py`) gains a `raw_record_ids: dict` field:

```python
@dataclass
class IngestState:
    last_obs_line: int = 0
    memory_mtimes: dict = field(default_factory=dict)
    raw_record_ids: dict = field(default_factory=dict)  # new
```

Maps `record_id → fingerprint`. A record is skipped on re-embed if its fingerprint is unchanged. Deleted records are not removed from Pinecone — closed bugs and resolved leads remain as historical data, which is desirable for the wanderer.

---

## Files Changed

### New
- `collectors/notion_bugs.py` — Notion API client (same `requests` pattern as `notion_pipeline.py`). Returns `List[BugTicket]`. Fetches all tickets; the observer and ingest layer decide what to embed. `BugTicket` dataclass fields: `id`, `title`, `status`, `priority_level`, `technical_areas`, `date_created`, `last_updated`, `date_completed`, `shortcut_url`, `days_open`.
- `scripts/backfill_raw_vectors.py` — one-time script. Loads `pipeline_cache.json`, queries bug tracker, reads full cancellations sheet, embeds everything into `raw_data`. Same non-fatal pattern as `scripts/backfill_vectors.py`.

### Modified
- `collectors/sheets.py` — add `fetch_cancellations_mtd(service, spreadsheet_id, tab_name)`. Reads tab `MONTHLY Cancellations`, parses all rows with a non-empty date, filters to current month by matching the month number in the `M/D` date field. Returns `{"count": int, "entries": List[dict]}` where each entry has: `date`, `account_name`, `months_paid`, `reason`, `base_plan`, `monetary_value`, `customer_note`, `customer_returned`, `lifetime_value`. Rows with an empty date column are skipped. Year is not inferred — MTD filtering compares only the month number from the `M/D` date string against `date.today().month`.
- `processors/memory_observer.py` — add `sales_data`, `demos_data`, `bugs`, `cancellations` params to `observe()`. Writes one `kpi_snapshot` per day (checks existing observations for today's date before writing). Existing observation types unchanged.
- `processors/vector_ingest.py` — extend `IngestState` with `raw_record_ids`. Add `prepare_raw_records(pipeline_leads, bugs, cancellations, sales_entries, previous_ids) -> (records, new_ids)`. Add `raw_namespace` param to `ingest()`. Brief retriever namespace params unchanged.
- `main.py` — import and call `collectors/notion_bugs.py` after pipeline load (guarded by `NOTION_TOKEN` check, non-fatal on error). Call `fetch_cancellations_mtd()` alongside existing sheets calls. Pass new data through to `observe()` and `vector_ingest()`.
- `config.json` — add `"raw_data_namespace": "raw_data"` under the `vector` block. Add cancellation sheet config: `"cancellations_spreadsheet_id"` and `"cancellations_tab_name"` under a new `"sheets"` block.

---

## Error Handling

All new collectors are non-fatal — same pattern as the existing pipeline cache and vector ingest:
- Bug collector failure → log warning, pass empty list to observer/ingest, run continues
- Cancellations fetch failure → log warning, pass empty dict, run continues
- `raw_data` ingest failure → log warning, does not block `observations`/`memories` ingest

---

## One-Time Backfill

Run `scripts/backfill_raw_vectors.py` once after deployment. This populates `raw_data` with all historical pipeline leads, all existing bug tickets, and all cancellation rows. After that, the daily run handles incremental updates.

---

## Out of Scope

- Brief retriever changes (explicitly excluded — `memory_retriever.py` untouched)
- Notion write access for pipeline leads (existing blocker, not resolved here)
- The wanderer itself (P16, built on top of this feature)
