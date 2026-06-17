# GTM Data Contract (Doc 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish one clean, named data source for each of the six GTM metrics — leads, demos, sales, late-stage count, churn count, churn reasons — so future metric functions (docs 1–2) have no ambiguity about where to read.

**Architecture:** Three additions to existing systems: (1) `fetch_leads_mtd()` in `collectors/sheets.py` reading from the Dept Heads KPI sheet via existing Google OAuth — zero new dependencies; (2) `count_late_stage()` in `collectors/pipeline.py` applying a pinned `late_stage_statuses` list from config; (3) config additions for KPI sheet coordinates and the status list. Churn count requires no new code — `fetch_cancellations_mtd()["count"]` is already the contract. No wiring into `main.py`, `brief`, or dashboard — that is docs 1–2.

**Tech Stack:** Python 3.11+, Google Sheets API v4 (existing Google OAuth, no new auth), pytest

---

## Resolved: HubSpot API vs. Maintained Sheet Column

**Decision: Sheet column.** Rationale:

- `requirements.txt` has no `hubspot-api-client` — adding HubSpot means a new PyPI dependency, a new `HUBSPOT_ACCESS_TOKEN` GitHub Secret, and a new auth pattern, all to read a single count.
- Google OAuth is already authenticated for Sheets; `collectors/sheets.py` already has the collector pattern. Zero new plumbing.
- The spec's own canonical source table lists "Dept Heads KPI sheet" as the source for all four count metrics — the sheet is the contract, not the CRM.
- If you later want HubSpot as the write-side that populates the sheet, that's a separate concern. The read contract stays the same.

**Prerequisites (manual, before running these tasks):**

1. Add `sheets.kpi_spreadsheet_id` in `config.json` — the spreadsheet ID of the Dept Heads KPI sheet.
2. Add `sheets.kpi_leads_tab_name` — the exact tab name containing new-lead rows (e.g. `"New Leads"` or `"GTM Leads"`).
3. Confirm the tab has: col A = date (`M/D` or `M/D/YYYY` format), col B = lead name, col C = source. If column layout differs, only the index references in `fetch_leads_mtd()` need updating — the function signature and return shape are fixed.

---

## Late-Stage Status Values — Analysis

Enumerated from live `data/pipeline_cache.json` (fetched 2026-06-03). All five status strings in the cache:

| Status | Verdict | Rationale |
|--------|---------|-----------|
| `"Demo Scheduled"` | **excluded** | Pre-demo; hasn't cleared the demo gate yet |
| `"In-Trial / Post Demo"` | **included** | Actively trialing — clearest late-stage signal |
| `"No Trial / Post Demo"` | **included** | Post-demo, went direct without a trial; still a live deal |
| `"On-Hold"` | **excluded** | Paused; not actively progressing toward close |
| `"Out of Demo / Need Upate"` | **excluded** | Stale/needs update — "Need Update" label signals cold; note: typo is intentional, matches the Notion DB string exactly |

**Pinned:** `late_stage_statuses = ["In-Trial / Post Demo", "No Trial / Post Demo"]`

If you want `"Out of Demo / Need Upate"` included, add it to the config list — the code reads from config, not hard-coded.

Note: `collectors/pipeline.py` already defines `_TRIAL_STATUS = "In-Trial / Post Demo"` and `_ATTENTION_STATUSES` as module constants. `count_late_stage()` reads from the passed-in list (from config), not from those private constants, so it stays decoupled from the trial-followup logic.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `collectors/pipeline.py` | Add `count_late_stage(leads, statuses)` |
| Modify | `collectors/sheets.py` | Add `fetch_leads_mtd()` |
| Modify | `config.json` | Add `pipeline.late_stage_statuses`; expand `sheets` block with KPI sheet keys |
| Create | `tests/test_pipeline_collector.py` | Tests for `count_late_stage()` |
| Create | `tests/test_leads_collector.py` | Tests for `fetch_leads_mtd()` |

---

## Task 1: Pin `late_stage_statuses` in config and add `count_late_stage()` to `collectors/pipeline.py`

**Files:**
- Modify: `collectors/pipeline.py`
- Modify: `config.json`
- Create: `tests/test_pipeline_collector.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# tests/test_pipeline_collector.py
import pytest
from collectors.pipeline import count_late_stage, PipelineLead


def _lead(status: str) -> PipelineLead:
    return PipelineLead(
        name="Test", contact="", email="",
        status=status, priority="",
        last_contacted=None, days_since_contact=None,
        estimated_value=None, source="", stale=False,
    )


LATE_STAGE = ["In-Trial / Post Demo", "No Trial / Post Demo"]


def test_count_late_stage_counts_matching_statuses():
    leads = [
        _lead("In-Trial / Post Demo"),
        _lead("In-Trial / Post Demo"),
        _lead("No Trial / Post Demo"),
        _lead("Demo Scheduled"),
        _lead("On-Hold"),
    ]
    assert count_late_stage(leads, LATE_STAGE) == 3


def test_count_late_stage_returns_zero_when_none_match():
    leads = [_lead("Demo Scheduled"), _lead("On-Hold")]
    assert count_late_stage(leads, LATE_STAGE) == 0


def test_count_late_stage_handles_empty_leads():
    assert count_late_stage([], LATE_STAGE) == 0


def test_count_late_stage_handles_empty_statuses():
    leads = [_lead("In-Trial / Post Demo")]
    assert count_late_stage(leads, []) == 0
```

- [ ] **Step 1.2: Run to verify it fails**

```
pytest tests/test_pipeline_collector.py -v
```
Expected: `ImportError: cannot import name 'count_late_stage' from 'collectors.pipeline'`

- [ ] **Step 1.3: Add `count_late_stage()` to `collectors/pipeline.py`**

Insert after the `_ATTENTION_STATUSES` block (after line 28), before `load_activity_overrides`:

```python
def count_late_stage(leads: list[PipelineLead], statuses: list[str]) -> int:
    """Count leads whose status is in the late-stage list from config."""
    status_set = set(statuses)
    return sum(1 for lead in leads if lead.status in status_set)
```

- [ ] **Step 1.4: Run to verify it passes**

```
pytest tests/test_pipeline_collector.py -v
```
Expected: 4 tests PASS

- [ ] **Step 1.5: Add `late_stage_statuses` to `config.json`**

Inside the `"pipeline"` block (after `"cache_stale_warn_days": 7`), add:

```json
"late_stage_statuses": ["In-Trial / Post Demo", "No Trial / Post Demo"]
```

Full `"pipeline"` block after edit:
```json
"pipeline": {
  "enabled": true,
  "cache_path": "data/pipeline_cache.json",
  "trial_followup_after_days": 5,
  "stale_after_days": 14,
  "cache_stale_warn_days": 7,
  "late_stage_statuses": ["In-Trial / Post Demo", "No Trial / Post Demo"]
}
```

- [ ] **Step 1.6: Commit**

```bash
git add collectors/pipeline.py config.json tests/test_pipeline_collector.py
git commit -m "feat: add count_late_stage() and pin late_stage_statuses in config"
```

---

## Task 2: Add `fetch_leads_mtd()` to `collectors/sheets.py`

Modeled after `fetch_cancellations_mtd()`: reads a single named tab, filters by the date column's month, returns `{"count": int, "entries": [...]}`. Uses `month: int | None = -1` parameter convention so callers can request all-months the same way as cancellations.

**Files:**
- Modify: `collectors/sheets.py`
- Create: `tests/test_leads_collector.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/test_leads_collector.py
from datetime import date
from unittest.mock import MagicMock

import pytest

from collectors.sheets import fetch_leads_mtd


def _mock_service(rows):
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.return_value = {"values": rows}
    return svc


HEADER = ["Date", "Lead Name", "Source"]
CURRENT_MONTH = date.today().month


def test_fetch_leads_mtd_returns_current_month_only():
    rows = [
        HEADER,
        [f"{CURRENT_MONTH}/3", "Acme Strength", "Inbound"],
        [f"{CURRENT_MONTH}/12", "Peak Performance", "Referral"],
        ["1/5", "Old Lead", "Cold outreach"],
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    if CURRENT_MONTH == 1:
        assert result["count"] == 3
    else:
        assert result["count"] == 2
        assert result["entries"][0]["name"] == "Acme Strength"
        assert result["entries"][0]["source"] == "Inbound"


def test_fetch_leads_mtd_returns_empty_on_api_error():
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.side_effect = Exception("API error")
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    assert result == {"count": 0, "entries": []}


def test_fetch_leads_mtd_handles_partial_rows():
    rows = [
        HEADER,
        [f"{CURRENT_MONTH}/10", "Sparse Lead"],  # no source column
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    assert result["count"] == 1
    assert result["entries"][0]["source"] == ""


def test_fetch_leads_mtd_skips_rows_with_no_date():
    rows = [
        HEADER,
        ["", "No Date Lead", "Web"],
        [f"{CURRENT_MONTH}/15", "Has Date Lead", "Inbound"],
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    assert result["count"] == 1
    assert result["entries"][0]["name"] == "Has Date Lead"


def test_fetch_leads_mtd_all_months_when_month_none():
    rows = [
        HEADER,
        ["1/5", "Jan Lead", "Inbound"],
        ["3/12", "Mar Lead", "Referral"],
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads", month=None)
    assert result["count"] == 2
```

- [ ] **Step 2.2: Run to verify it fails**

```
pytest tests/test_leads_collector.py -v
```
Expected: `ImportError: cannot import name 'fetch_leads_mtd' from 'collectors.sheets'`

- [ ] **Step 2.3: Add `fetch_leads_mtd()` to `collectors/sheets.py`**

Append to the end of the file:

```python
def fetch_leads_mtd(
    service, spreadsheet_id: str, tab_name: str, month: int | None = -1
) -> dict:
    """Fetch new-lead entries from the Dept Heads KPI sheet.

    Args:
        month: Filter to this month number (1-12). Pass None to return all rows.
               Defaults to -1 which resolves to the current month.

    Tab structure: col A = date (M/D format), col B = lead name, col C = source.
    """
    if month == -1:
        month = date.today().month

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1:C200",
        ).execute()
    except Exception:
        return {"count": 0, "entries": []}

    rows = result.get("values", [])
    entries = []

    for row in rows[1:]:  # skip header
        date_str = row[0].strip() if row else ""
        if not date_str or "/" not in date_str:
            continue
        try:
            row_month = int(date_str.split("/")[0])
        except (ValueError, IndexError):
            continue
        if month is not None and row_month != month:
            continue
        entries.append({
            "date": date_str,
            "name": row[1] if len(row) > 1 else "",
            "source": row[2] if len(row) > 2 else "",
        })

    return {"count": len(entries), "entries": entries}
```

- [ ] **Step 2.4: Run to verify it passes**

```
pytest tests/test_leads_collector.py -v
```
Expected: 5 tests PASS

- [ ] **Step 2.5: Add KPI sheet config keys to `config.json`**

Expand the `"sheets"` block:

```json
"sheets": {
  "cancellations_spreadsheet_id": "1BYMMVKw19Y9pwp7oFYMvUC4Webk-NI-Y-kevj7CX6D4",
  "cancellations_tab_name": "MONTHLY Cancellations",
  "kpi_spreadsheet_id": "",
  "kpi_leads_tab_name": ""
}
```

`kpi_spreadsheet_id` and `kpi_leads_tab_name` are intentionally blank. The user fills these in from the actual Dept Heads KPI sheet before any live call.

- [ ] **Step 2.6: Commit**

```bash
git add collectors/sheets.py config.json tests/test_leads_collector.py
git commit -m "feat: add fetch_leads_mtd() and KPI sheet config placeholders"
```

---

## Task 3: Full test suite verification

- [ ] **Step 3.1: Run the full test suite**

```
pytest tests/ -v --tb=short 2>&1 | tail -40
```
Expected: no new failures. All pre-existing tests still pass.

- [ ] **Step 3.2: If failures appear, fix before closing**

No new failures are expected — the two new functions are additive. If something fails, investigate and fix it; do not skip.

---

## Canonical Source Table (the contract after this plan)

| Metric | Kind | Source | Function | Config keys |
|--------|------|--------|----------|-------------|
| Leads MTD count | fetch | Dept Heads KPI sheet | `fetch_leads_mtd(svc, cfg["sheets"]["kpi_spreadsheet_id"], cfg["sheets"]["kpi_leads_tab_name"])` | `sheets.kpi_spreadsheet_id`, `sheets.kpi_leads_tab_name` |
| Demos MTD | fetch | Dept Heads KPI sheet (monthly tab) | `fetch_demos_mtd(svc, cfg["meeting_prep"]["sheets"]["demos_spreadsheet_id"], month_label())` | `meeting_prep.sheets.demos_spreadsheet_id` |
| Sales MTD | fetch | Dept Heads KPI sheet (monthly tab) | `fetch_sales_mtd(svc, cfg["meeting_prep"]["sheets"]["sales_spreadsheet_id"], month_label())` | `meeting_prep.sheets.sales_spreadsheet_id` |
| Late-stage count | derived | Notion pipeline cache | `count_late_stage(leads, cfg["pipeline"]["late_stage_statuses"])` | `pipeline.late_stage_statuses`, `pipeline.cache_path` |
| Churn count MTD | derived | MONTHLY Cancellations sheet | `fetch_cancellations_mtd(svc, ...)[" count"]` | `sheets.cancellations_spreadsheet_id` |
| Churn reasons | fetch | MONTHLY Cancellations sheet | `fetch_cancellations_mtd(svc, ...)[" entries"][i]["reason"]` | same |

**Note on `fetch_pipeline_leads` vs raw leads:** `fetch_pipeline_leads()` returns `(trial_leads, attention_leads)` — pre-filtered lists for the brief. For `count_late_stage()`, callers need all leads. The raw list is `json.load(open(cfg["pipeline"]["cache_path"]))["leads"]` mapped to `PipelineLead` objects, or call `fetch_pipeline_leads()` with a very high `stale_after_days` to avoid filtering, then union the two lists. Doc 1 should pin exactly which call pattern to use. For now, the contract is: pipeline cache → `count_late_stage()`.
