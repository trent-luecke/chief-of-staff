# P15 — KPI Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add daily KPI snapshots and raw individual records (pipeline leads, bug tickets, cancellations, sales entries) to Pinecone so the future autonomous wanderer has rich historical data to reason over.

**Architecture:** Two new collectors (Notion bugs, cancellation sheet) feed into extended versions of `memory_observer.py` (daily aggregate snapshot → `observations` namespace) and `vector_ingest.py` (raw per-record embedding → new `raw_data` namespace). The morning brief retriever is untouched. All new collectors are non-fatal.

**Tech Stack:** Python 3.11+, Pinecone serverless, Voyage AI (`voyage-3-lite`), Notion API v1 (requests), Google Sheets API v4, pytest, python-frontmatter

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `collectors/notion_bugs.py` | Fetch bug tickets from Notion; `BugTicket` dataclass |
| Modify | `collectors/sheets.py` | Add `fetch_cancellations_mtd()` |
| Modify | `processors/memory_observer.py` | Add `kpi_snapshot` observation type; accept new data params |
| Modify | `processors/vector_ingest.py` | Add `raw_data` namespace; extend `IngestState`; `prepare_raw_records()` |
| Modify | `main.py` | Call new collectors; pass data to observer + ingest |
| Modify | `config.json` | Add `raw_data_namespace` + cancellation sheet config |
| Create | `scripts/backfill_raw_vectors.py` | One-time historical backfill for raw_data namespace |
| Create | `tests/test_notion_bugs.py` | Unit tests for bug collector |
| Modify | `tests/test_vector_ingest.py` | Tests for raw_data ingest |

---

## Task 1: `collectors/notion_bugs.py` — Bug Ticket Collector

**Files:**
- Create: `collectors/notion_bugs.py`
- Create: `tests/test_notion_bugs.py`

- [ ] **Step 1.1: Write failing tests**

```python
# tests/test_notion_bugs.py
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from collectors.notion_bugs import BugTicket, fetch_bugs, _parse_bug_row, DATABASE_ID


MOCK_ROW = {
    "id": "abc-123",
    "properties": {
        "Ticket Name": {
            "type": "title",
            "title": [{"plain_text": "Payment widget crashes on iOS"}],
        },
        "Status": {
            "type": "status",
            "status": {"name": "In progress"},
        },
        "Priority Level": {
            "type": "select",
            "select": {"name": "High"},
        },
        "Technical Area of Issue": {
            "type": "multi_select",
            "multi_select": [
                {"name": "OS Mobile App"},
                {"name": "Payment Processing Error"},
            ],
        },
        "Date Created": {
            "type": "created_time",
            "created_time": "2026-04-19T12:00:00.000Z",
        },
        "Last Update": {
            "type": "last_edited_time",
            "last_edited_time": "2026-04-28T09:00:00.000Z",
        },
        "Date Completed": {
            "type": "date",
            "date": None,
        },
        "Shortcut URL": {
            "type": "url",
            "url": "https://app.shortcut.com/teambuildr/story/123",
        },
    },
}


def test_parse_bug_row_populates_all_fields():
    ticket = _parse_bug_row(MOCK_ROW)
    assert ticket.id == "abc-123"
    assert ticket.title == "Payment widget crashes on iOS"
    assert ticket.status == "In progress"
    assert ticket.priority_level == "High"
    assert ticket.technical_areas == ["OS Mobile App", "Payment Processing Error"]
    assert ticket.date_created == "2026-04-19"
    assert ticket.last_updated == "2026-04-28"
    assert ticket.date_completed is None
    assert ticket.shortcut_url == "https://app.shortcut.com/teambuildr/story/123"
    assert ticket.days_open >= 0


def test_parse_bug_row_handles_missing_optional_fields():
    row = {
        "id": "xyz-999",
        "properties": {
            "Ticket Name": {"type": "title", "title": []},
            "Status": {"type": "status", "status": None},
            "Priority Level": {"type": "select", "select": None},
            "Technical Area of Issue": {"type": "multi_select", "multi_select": []},
            "Date Created": {"type": "created_time", "created_time": "2026-04-01T00:00:00.000Z"},
            "Last Update": {"type": "last_edited_time", "last_edited_time": "2026-04-01T00:00:00.000Z"},
            "Date Completed": {"type": "date", "date": None},
            "Shortcut URL": {"type": "url", "url": None},
        },
    }
    ticket = _parse_bug_row(row)
    assert ticket.title == ""
    assert ticket.status is None
    assert ticket.priority_level is None
    assert ticket.technical_areas == []
    assert ticket.shortcut_url is None


def test_fetch_bugs_returns_bug_tickets():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [MOCK_ROW],
        "has_more": False,
    }
    with patch("collectors.notion_bugs.requests.post", return_value=mock_response):
        tickets = fetch_bugs("fake-token")
    assert len(tickets) == 1
    assert isinstance(tickets[0], BugTicket)
    assert tickets[0].title == "Payment widget crashes on iOS"


def test_fetch_bugs_returns_empty_list_on_api_error():
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    with patch("collectors.notion_bugs.requests.post", return_value=mock_response):
        tickets = fetch_bugs("bad-token")
    assert tickets == []
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_notion_bugs.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'collectors.notion_bugs'`

- [ ] **Step 1.3: Implement `collectors/notion_bugs.py`**

```python
# collectors/notion_bugs.py
"""Notion bug tracker collector — fetches TeamBuildr OS bug tickets."""

import sys
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

DATABASE_ID = "29d24bca36d78065b255cbb693a776da"

_HEADERS = lambda token: {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


@dataclass
class BugTicket:
    id: str
    title: str
    status: Optional[str]
    priority_level: Optional[str]
    technical_areas: list
    date_created: str
    last_updated: str
    date_completed: Optional[str]
    shortcut_url: Optional[str]
    days_open: int


def _get(props: dict, key: str, kind: str, fallback=None):
    block = props.get(key, {})
    if kind == "title":
        parts = block.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts) or fallback
    if kind == "select":
        return (block.get("select") or {}).get("name", fallback)
    if kind == "status":
        return (block.get("status") or {}).get("name", fallback)
    if kind == "multi_select":
        return [opt["name"] for opt in block.get("multi_select", [])]
    if kind == "created_time":
        ts = block.get("created_time", "")
        return ts[:10] if ts else fallback
    if kind == "last_edited_time":
        ts = block.get("last_edited_time", "")
        return ts[:10] if ts else fallback
    if kind == "date":
        return (block.get("date") or {}).get("start", fallback)
    if kind == "url":
        return block.get("url", fallback)
    return fallback


def _query_all(token: str, database_id: str) -> list:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    results = []
    cursor = None
    while True:
        body = {}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(url, headers=_HEADERS(token), json=body)
        if resp.status_code != 200:
            print(f"Notion bug tracker API error {resp.status_code}: {resp.text}", file=sys.stderr)
            return []
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _parse_bug_row(row: dict) -> BugTicket:
    props = row.get("properties", {})
    date_created_str = _get(props, "Date Created", "created_time", "")
    date_completed_str = _get(props, "Date Completed", "date")

    today = date.today()
    days_open = 0
    if date_created_str:
        try:
            created = date.fromisoformat(date_created_str[:10])
            if date_completed_str:
                end = date.fromisoformat(date_completed_str[:10])
            else:
                end = today
            days_open = max(0, (end - created).days)
        except (ValueError, TypeError):
            pass

    return BugTicket(
        id=row["id"],
        title=_get(props, "Ticket Name", "title", ""),
        status=_get(props, "Status", "status"),
        priority_level=_get(props, "Priority Level", "select"),
        technical_areas=_get(props, "Technical Area of Issue", "multi_select") or [],
        date_created=date_created_str,
        last_updated=_get(props, "Last Update", "last_edited_time", ""),
        date_completed=date_completed_str,
        shortcut_url=_get(props, "Shortcut URL", "url"),
        days_open=days_open,
    )


def fetch_bugs(token: str) -> list:
    """Fetch all bug tickets from the Notion bug tracker. Returns empty list on error."""
    rows = _query_all(token, DATABASE_ID)
    return [_parse_bug_row(row) for row in rows]
```

- [ ] **Step 1.4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_notion_bugs.py -v
```

Expected: `4 passed`

- [ ] **Step 1.5: Commit**

```bash
git add collectors/notion_bugs.py tests/test_notion_bugs.py
git commit -m "feat: add notion_bugs collector with BugTicket dataclass"
```

---

## Task 2: `collectors/sheets.py` — Cancellations Collector

**Files:**
- Modify: `collectors/sheets.py`
- Create: `tests/test_cancellations_collector.py`

**Confirmed column layout** (verified against live sheet 2026-05-01):
Row 1 = header. Data rows: col 0 = nav (skip), col 1 = Date (M/D), col 2 = Account Name, col 3 = # Months Paid, col 4 = Reason, col 5 = Base Plan Type, col 6 = Base Plan, col 7 = Additions, col 8 = Monetary Value, col 9 = Customer Note, col 10 = Customer Returned, col 11 = Months Until Returned, col 12 = Lifetime Value.

Spreadsheet ID: `1BYMMVKw19Y9pwp7oFYMvUC4Webk-NI-Y-kevj7CX6D4`
Tab name: `MONTHLY Cancellations`

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_cancellations_collector.py
from unittest.mock import MagicMock
from datetime import date

import pytest

from collectors.sheets import fetch_cancellations_mtd


def _mock_service(rows):
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.return_value = {"values": rows}
    return svc


HEADER = [
    "Jump to Bottom", "Date", "Account Name and #", "# of Months paid before Cancelation",
    "Reason for Cancelation", "Base Plan Type", "Base Plan", "Additions",
    "Monetary Value", "Answer", "Customer Returned", "Number of Months until Customer Returned",
    "Lifetime Value",
]

CURRENT_MONTH = date.today().month


def test_fetch_cancellations_mtd_returns_current_month_only():
    rows = [
        HEADER,
        ["", f"{CURRENT_MONTH}/14", "Acme Gym", "12", "App Complaints", "", "$150/mo", "", "$1,800", "had issues", "", "", "$1,800"],
        ["", "1/5", "Old Customer", "6", "Business Changes", "", "$100/mo", "", "$600", "old", "", "", "$600"],
    ]
    # Only the second row should match (other row is month 1, which won't match if current month != 1)
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    if CURRENT_MONTH == 1:
        # Both rows match in January
        assert result["count"] == 2
    else:
        assert result["count"] == 1
        assert result["entries"][0]["account_name"] == "Acme Gym"
        assert result["entries"][0]["reason"] == "App Complaints"
        assert result["entries"][0]["monetary_value"] == "$1,800"
        assert result["entries"][0]["customer_note"] == "had issues"


def test_fetch_cancellations_mtd_skips_rows_with_no_date():
    rows = [
        HEADER,
        ["", "", "No Date Row", "3", "reason", "", "$100", "", "$300", "", "", "", ""],
        ["", f"{CURRENT_MONTH}/20", "Has Date", "5", "Price", "", "$150", "", "$750", "", "", "", ""],
    ]
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    assert result["count"] == 1
    assert result["entries"][0]["account_name"] == "Has Date"


def test_fetch_cancellations_mtd_handles_partial_rows():
    rows = [
        HEADER,
        ["", f"{CURRENT_MONTH}/14", "Sparse Row"],  # only 3 columns
    ]
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    assert result["count"] == 1
    assert result["entries"][0]["account_name"] == "Sparse Row"
    assert result["entries"][0]["reason"] == ""


def test_fetch_cancellations_mtd_returns_empty_on_api_error():
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.side_effect = Exception("API error")
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    assert result == {"count": 0, "entries": []}


def test_fetch_cancellations_mtd_all_months_when_month_none():
    rows = [
        HEADER,
        ["", "1/5", "Jan Customer", "6", "App", "", "$150", "", "$900", "", "", "", ""],
        ["", "3/12", "Mar Customer", "4", "Price", "", "$100", "", "$400", "", "", "", ""],
    ]
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations", month=None)
    assert result["count"] == 2
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_cancellations_collector.py -v 2>&1 | head -20
```

Expected: `ImportError` or `TypeError` — `fetch_cancellations_mtd` doesn't exist yet.

- [ ] **Step 2.3: Add `fetch_cancellations_mtd` to `collectors/sheets.py`**

Append this function after the existing `fetch_demos_mtd` function:

```python
def fetch_cancellations_mtd(
    service, spreadsheet_id: str, tab_name: str, month: int | None = -1
) -> dict:
    """Fetch cancellation entries from the MONTHLY Cancellations tab.

    Args:
        month: Filter to this month number (1-12). Pass None to return all rows.
               Defaults to -1 which resolves to the current month.
    """
    from datetime import date as _date
    if month == -1:
        month = _date.today().month

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1:N300",
        ).execute()
    except Exception:
        return {"count": 0, "entries": []}

    rows = result.get("values", [])
    entries = []

    for row in rows[1:]:  # skip header
        date_str = row[1].strip() if len(row) > 1 else ""
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
            "account_name": row[2] if len(row) > 2 else "",
            "months_paid": row[3] if len(row) > 3 else "",
            "reason": row[4] if len(row) > 4 else "",
            "base_plan_type": row[5] if len(row) > 5 else "",
            "base_plan": row[6] if len(row) > 6 else "",
            "monetary_value": row[8] if len(row) > 8 else "",
            "customer_note": row[9] if len(row) > 9 else "",
            "customer_returned": row[10] if len(row) > 10 else "",
            "lifetime_value": row[12] if len(row) > 12 else "",
        })

    return {"count": len(entries), "entries": entries}
```

- [ ] **Step 2.4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_cancellations_collector.py -v
```

Expected: `5 passed`

- [ ] **Step 2.5: Commit**

```bash
git add collectors/sheets.py tests/test_cancellations_collector.py
git commit -m "feat: add fetch_cancellations_mtd to sheets collector"
```

---

## Task 3: `processors/memory_observer.py` — KPI Snapshot Observation

**Files:**
- Modify: `processors/memory_observer.py`
- Modify: `tests/test_vector_ingest.py` (add kpi_snapshot tests in a new file)
- Create: `tests/test_memory_observer_kpi.py`

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_memory_observer_kpi.py
import json
import tempfile
import os
from datetime import date

import pytest

from processors.memory_observer import observe, _kpi_snapshot_exists_today


def _make_obs_file(tmp_path, lines=None):
    path = tmp_path / "observations.jsonl"
    if lines:
        with open(path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
    else:
        path.touch()
    return str(path)


def _make_decisions_file(tmp_path):
    path = tmp_path / "decisions.md"
    path.touch()
    return str(path)


def test_kpi_snapshot_written_when_sales_data_provided(tmp_path):
    obs_file = _make_obs_file(tmp_path)
    decisions_file = _make_decisions_file(tmp_path)

    from collectors.gmail import EmailThread
    from collectors.pipeline import PipelineLead
    from processors.brief import BriefContent
    from processors.issues import Issue

    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(executive_summary="test", top_3_priorities=[]),
        issues=[],
        sales_data={"count": 8, "revenue": 1200.0, "entries": []},
        demos_data={"count": 3, "entries": []},
        bugs=[],
        cancellations={"count": 1, "entries": []},
    )

    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 1
    assert "Sales MTD" in snapshots[0]["content"]
    assert "1200" in snapshots[0]["content"] or "1,200" in snapshots[0]["content"]
    assert "Demos MTD: 3" in snapshots[0]["content"]
    assert "Cancellations MTD: 1" in snapshots[0]["content"]
    assert snapshots[0]["date"] == date.today().isoformat()


def test_kpi_snapshot_not_duplicated_on_rerun(tmp_path):
    today = date.today().isoformat()
    existing = {"date": today, "type": "kpi_snapshot", "entity": "daily",
                "content": "KPI snapshot already written", "source": "kpi"}
    obs_file = _make_obs_file(tmp_path, lines=[existing])
    decisions_file = _make_decisions_file(tmp_path)

    from collectors.gmail import EmailThread
    from processors.brief import BriefContent

    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(executive_summary="test", top_3_priorities=[]),
        issues=[],
        sales_data={"count": 5, "revenue": 800.0, "entries": []},
        demos_data={"count": 2, "entries": []},
        bugs=[],
        cancellations={"count": 0, "entries": []},
    )

    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 1  # still only one


def test_kpi_snapshot_not_written_when_no_kpi_data(tmp_path):
    obs_file = _make_obs_file(tmp_path)
    decisions_file = _make_decisions_file(tmp_path)

    from processors.brief import BriefContent

    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={},
        pipeline_leads=[],
        brief=BriefContent(executive_summary="test", top_3_priorities=[]),
        issues=[],
    )

    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]

    snapshots = [l for l in lines if l["type"] == "kpi_snapshot"]
    assert len(snapshots) == 0


def test_kpi_snapshot_exists_today_detects_existing(tmp_path):
    today = date.today().isoformat()
    obs_file = _make_obs_file(tmp_path, lines=[
        {"date": today, "type": "kpi_snapshot", "entity": "daily", "content": "x", "source": "kpi"},
    ])
    assert _kpi_snapshot_exists_today(obs_file) is True


def test_kpi_snapshot_exists_today_returns_false_when_absent(tmp_path):
    obs_file = _make_obs_file(tmp_path)
    assert _kpi_snapshot_exists_today(obs_file) is False
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_memory_observer_kpi.py -v 2>&1 | head -20
```

Expected: `ImportError` — `_kpi_snapshot_exists_today` not found.

- [ ] **Step 3.3: Extend `processors/memory_observer.py`**

Add these imports at the top of the file (after the existing imports):

```python
from datetime import date
```

(Note: `date` may already be imported — check first. If `from datetime import date` is already present, skip this.)

Add these two functions before the `observe()` function:

```python
def _kpi_snapshot_exists_today(obs_file: str) -> bool:
    """Return True if a kpi_snapshot for today already exists in obs_file."""
    today = date.today().isoformat()
    try:
        with open(obs_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    if obs.get("type") == "kpi_snapshot" and obs.get("date") == today:
                        return True
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return False


def _build_kpi_snapshot(
    pipeline_leads,
    sales_data: dict,
    demos_data: dict,
    bugs: list,
    cancellations: dict,
) -> dict:
    """Build a kpi_snapshot observation dict from collected KPI data."""
    today = date.today().isoformat()

    sales_revenue = sales_data.get("revenue", 0.0) if sales_data else 0.0
    sales_count = sales_data.get("count", 0) if sales_data else 0
    demo_count = demos_data.get("count", 0) if demos_data else 0
    cancel_count = cancellations.get("count", 0) if cancellations else 0

    # Pipeline breakdown by status
    pipeline_by_status: dict[str, int] = {}
    for lead in (pipeline_leads or []):
        status = getattr(lead, "status", None) or lead.get("status", "Unknown") if isinstance(lead, dict) else getattr(lead, "status", "Unknown")
        pipeline_by_status[status] = pipeline_by_status.get(status, 0) + 1

    pipeline_str = ", ".join(f"{count} {status}" for status, count in pipeline_by_status.items())
    if not pipeline_str:
        pipeline_str = "0 leads"

    # Bug breakdown by priority
    open_bugs = [b for b in (bugs or []) if getattr(b, "status", "") != "Done"]
    bug_count = len(open_bugs)
    high = sum(1 for b in open_bugs if getattr(b, "priority_level", "") == "High")
    moderate = sum(1 for b in open_bugs if getattr(b, "priority_level", "") == "Moderate")
    low = sum(1 for b in open_bugs if getattr(b, "priority_level", "") == "Low")

    content = (
        f"KPI snapshot {today}: "
        f"Sales MTD ${sales_revenue:,.0f} ({sales_count} deals). "
        f"Demos MTD: {demo_count}. "
        f"Pipeline: {pipeline_str}. "
        f"Open bugs: {bug_count} ({high} High, {moderate} Moderate, {low} Low). "
        f"Cancellations MTD: {cancel_count}."
    )

    context = (
        f"sales_revenue={int(sales_revenue)} sales_count={sales_count} "
        f"demos={demo_count} open_bugs={bug_count} bugs_high={high} "
        f"cancellations_mtd={cancel_count}"
    )

    return {
        "date": today,
        "type": "kpi_snapshot",
        "entity": "daily",
        "content": content,
        "source": "kpi",
        "context": context,
    }
```

Update the `observe()` function signature to accept new optional params (add after `issues: list[Issue]`):

```python
def observe(
    obs_file: str,
    decisions_file: str,
    email_threads: list[EmailThread],
    still_open_ids: dict,
    pipeline_leads: list[PipelineLead],
    brief: BriefContent,
    issues: list[Issue],
    sales_data: dict | None = None,
    demos_data: dict | None = None,
    bugs: list | None = None,
    cancellations: dict | None = None,
) -> None:
```

At the end of `observe()`, before the final file write, add:

```python
    # kpi_snapshot — written once per day
    has_kpi = any(p is not None for p in [sales_data, demos_data, bugs, cancellations])
    if has_kpi and not _kpi_snapshot_exists_today(obs_file):
        observations.append(_build_kpi_snapshot(
            pipeline_leads=pipeline_leads,
            sales_data=sales_data or {},
            demos_data=demos_data or {},
            bugs=bugs or [],
            cancellations=cancellations or {},
        ))
```

- [ ] **Step 3.4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_memory_observer_kpi.py -v
```

Expected: `5 passed`

- [ ] **Step 3.5: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -v --ignore=tests/test_vector_ingest_integration.py 2>&1 | tail -20
```

Expected: all existing tests still pass.

- [ ] **Step 3.6: Commit**

```bash
git add processors/memory_observer.py tests/test_memory_observer_kpi.py
git commit -m "feat: add kpi_snapshot observation type to memory_observer"
```

---

## Task 4: `processors/vector_ingest.py` — raw_data Namespace

**Files:**
- Modify: `processors/vector_ingest.py`
- Modify: `tests/test_vector_ingest.py`

- [ ] **Step 4.1: Write failing tests**

Append these tests to the end of `tests/test_vector_ingest.py`:

```python
# --- raw_data namespace tests ---

from processors.vector_ingest import prepare_raw_records


MOCK_LEAD = {
    "page_id": "page-abc-123",
    "name": "Tyler Landeck — ALA",
    "status": "In-Trial / Post Demo",
    "source": "Other",
    "priority": "High",
    "days_since_contact": 49,
    "stale": True,
    "email": "tyler@ala.com",
    "estimated_value": None,
}

MOCK_BUG = {
    "id": "bug-xyz-456",
    "title": "Payment widget crashes on iOS",
    "status": "In progress",
    "priority_level": "High",
    "technical_areas": ["OS Mobile App", "Payment Processing Error"],
    "date_created": "2026-04-19",
    "last_updated": "2026-04-28",
    "date_completed": None,
    "shortcut_url": "https://app.shortcut.com/story/123",
    "days_open": 12,
}

MOCK_CANCELLATION_ENTRY = {
    "date": "4/14",
    "account_name": "Activ8 Performance Training",
    "months_paid": "8",
    "reason": "App Complaints",
    "base_plan": "$150/mo",
    "monetary_value": "$1,200",
    "customer_note": "issues with scheduling and notifications",
    "customer_returned": "",
    "lifetime_value": "$1,200",
}

MOCK_SALE_ENTRY = {
    "date": "4/22",
    "total": 150.0,
    "customer": "Crossfit Meridian",
    "salesperson": "Trent",
    "sale_type": "New",
}


def test_prepare_raw_records_builds_lead_record():
    records, new_ids = prepare_raw_records(
        pipeline_leads=[MOCK_LEAD],
        bugs=[],
        cancellations={"count": 0, "entries": []},
        sales_entries=[],
        previous_ids={},
    )
    lead_records = [r for r in records if r["id"].startswith("lead:")]
    assert len(lead_records) == 1
    r = lead_records[0]
    assert "Tyler Landeck" in r["text"]
    assert "In-Trial / Post Demo" in r["text"]
    assert r["metadata"]["stale"] is True
    assert "lead:page-abc-123" in new_ids


def test_prepare_raw_records_builds_bug_record():
    records, new_ids = prepare_raw_records(
        pipeline_leads=[],
        bugs=[MOCK_BUG],
        cancellations={"count": 0, "entries": []},
        sales_entries=[],
        previous_ids={},
    )
    bug_records = [r for r in records if r["id"].startswith("bug:")]
    assert len(bug_records) == 1
    r = bug_records[0]
    assert "Payment widget crashes on iOS" in r["text"]
    assert "High" in r["text"]
    assert "OS Mobile App" in r["text"]
    assert r["metadata"]["days_open"] == 12


def test_prepare_raw_records_builds_cancellation_record():
    records, new_ids = prepare_raw_records(
        pipeline_leads=[],
        bugs=[],
        cancellations={"count": 1, "entries": [MOCK_CANCELLATION_ENTRY]},
        sales_entries=[],
        previous_ids={},
    )
    cancel_records = [r for r in records if r["id"].startswith("cancel:")]
    assert len(cancel_records) == 1
    r = cancel_records[0]
    assert "Activ8 Performance Training" in r["text"]
    assert "App Complaints" in r["text"]
    assert "issues with scheduling" in r["text"]


def test_prepare_raw_records_builds_sale_record():
    records, new_ids = prepare_raw_records(
        pipeline_leads=[],
        bugs=[],
        cancellations={"count": 0, "entries": []},
        sales_entries=[MOCK_SALE_ENTRY],
        previous_ids={},
    )
    sale_records = [r for r in records if r["id"].startswith("sale:")]
    assert len(sale_records) == 1
    r = sale_records[0]
    assert "Crossfit Meridian" in r["text"]
    assert "150" in r["text"]
    assert "New" in r["text"]


def test_prepare_raw_records_skips_unchanged_records():
    # Put the lead's fingerprint in previous_ids so it should be skipped
    _, first_ids = prepare_raw_records(
        pipeline_leads=[MOCK_LEAD],
        bugs=[],
        cancellations={"count": 0, "entries": []},
        sales_entries=[],
        previous_ids={},
    )
    # Second call with same lead and the IDs from first call — should be empty
    records, _ = prepare_raw_records(
        pipeline_leads=[MOCK_LEAD],
        bugs=[],
        cancellations={"count": 0, "entries": []},
        sales_entries=[],
        previous_ids=first_ids,
    )
    lead_records = [r for r in records if r["id"].startswith("lead:")]
    assert len(lead_records) == 0


def test_ingest_state_round_trips_raw_record_ids(tmp_path):
    from processors.vector_ingest import IngestState, save_ingest_state, load_ingest_state
    path = str(tmp_path / "state.json")
    state = IngestState(
        last_obs_line=10,
        memory_mtimes={"apex.md": 123.0},
        raw_record_ids={"lead:page-abc": "In-Trial:5:High", "bug:xyz": "2026-04-28"},
    )
    save_ingest_state(state, path)
    loaded = load_ingest_state(path)
    assert loaded.raw_record_ids["lead:page-abc"] == "In-Trial:5:High"
    assert loaded.raw_record_ids["bug:xyz"] == "2026-04-28"
```

- [ ] **Step 4.2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_vector_ingest.py -k "raw" -v 2>&1 | head -20
```

Expected: `ImportError` — `prepare_raw_records` not found.

- [ ] **Step 4.3: Extend `IngestState` in `processors/vector_ingest.py`**

Replace the `IngestState` dataclass:

```python
@dataclass
class IngestState:
    last_obs_line: int = 0
    memory_mtimes: dict = field(default_factory=dict)
    raw_record_ids: dict = field(default_factory=dict)
```

Update `load_ingest_state` to load the new field:

```python
def load_ingest_state(path: str) -> IngestState:
    try:
        with open(path) as f:
            data = json.load(f)
        return IngestState(
            last_obs_line=data.get("last_obs_line", 0),
            memory_mtimes=data.get("memory_mtimes", {}),
            raw_record_ids=data.get("raw_record_ids", {}),
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return IngestState()
```

(`save_ingest_state` uses `asdict()` and requires no change.)

- [ ] **Step 4.4: Add `prepare_raw_records` and helper functions**

Add these functions to `processors/vector_ingest.py` after `prepare_memory_records`:

```python
import hashlib as _hashlib


def _raw_slug(text: str) -> str:
    """Return a lowercase, hyphenated slug truncated to 40 chars."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip())[:40].strip("-")


def _content_hash(values: list) -> str:
    """Short hash of a list of string values for change detection."""
    combined = "|".join(str(v) for v in values)
    return _hashlib.md5(combined.encode()).hexdigest()[:12]


def _lead_records(pipeline_leads: list, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for lead in pipeline_leads:
        page_id = lead.get("page_id", "")
        if not page_id:
            continue
        record_id = f"lead:{page_id}"
        status = lead.get("status", "")
        days = lead.get("days_since_contact") or 0
        priority = lead.get("priority", "")
        fingerprint = f"{status}:{days}:{priority}"
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue
        stale_str = " | stale" if lead.get("stale") else ""
        text = (
            f"Pipeline lead: {lead.get('name', '')} | "
            f"status: {status} | "
            f"source: {lead.get('source', '')} | "
            f"priority: {priority} | "
            f"{days} days since contact{stale_str}"
        )
        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "name": lead.get("name", ""),
                "status": status,
                "source": lead.get("source", ""),
                "priority": priority,
                "days_since_contact": days,
                "stale": bool(lead.get("stale", False)),
                "email": lead.get("email", ""),
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def _bug_records(bugs: list, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for bug in bugs:
        bug_id = bug.get("id", "") if isinstance(bug, dict) else getattr(bug, "id", "")
        if not bug_id:
            continue
        record_id = f"bug:{bug_id}"

        def _field(name):
            return bug.get(name) if isinstance(bug, dict) else getattr(bug, name, None)

        last_updated = _field("last_updated") or ""
        fingerprint = last_updated
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue

        title = _field("title") or ""
        status = _field("status") or ""
        priority = _field("priority_level") or ""
        areas = _field("technical_areas") or []
        days_open = _field("days_open") or 0
        areas_str = ", ".join(areas) if areas else "untagged"

        text = (
            f"Bug: {title} | "
            f"status: {status} | "
            f"priority: {priority} | "
            f"areas: {areas_str} | "
            f"{days_open} days open"
        )
        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "title": title,
                "status": status,
                "priority_level": priority,
                "technical_areas": areas,
                "date_created": _field("date_created") or "",
                "days_open": days_open,
                "shortcut_url": _field("shortcut_url") or "",
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def _cancellation_records(cancellations: dict, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for entry in (cancellations or {}).get("entries", []):
        date_str = entry.get("date", "")
        account = entry.get("account_name", "")
        if not date_str or not account:
            continue
        record_id = f"cancel:{_raw_slug(date_str)}:{_raw_slug(account)}"
        fingerprint = _content_hash([
            date_str, account, entry.get("reason", ""), entry.get("monetary_value", "")
        ])
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue

        reason = entry.get("reason", "")
        base_plan = entry.get("base_plan", "")
        monetary_value = entry.get("monetary_value", "")
        customer_note = entry.get("customer_note", "")

        parts = [f"Cancellation: {account} on {date_str}"]
        if reason:
            parts.append(f"reason: {reason}")
        if base_plan:
            parts.append(f"base plan: {base_plan}")
        if monetary_value:
            parts.append(f"monetary value: {monetary_value}")
        if customer_note:
            parts.append(f"customer note: {customer_note}")
        text = " | ".join(parts)

        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "date": date_str,
                "account_name": account,
                "reason": reason,
                "base_plan": base_plan,
                "monetary_value": monetary_value,
                "customer_returned": entry.get("customer_returned", ""),
                "lifetime_value": entry.get("lifetime_value", ""),
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def _sale_records(sales_entries: list, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for entry in (sales_entries or []):
        date_str = entry.get("date", "")
        customer = entry.get("customer", "")
        if not date_str or not customer:
            continue
        record_id = f"sale:{_raw_slug(date_str)}:{_raw_slug(customer)}"
        fingerprint = _content_hash([
            date_str, customer, str(entry.get("total", "")), entry.get("sale_type", "")
        ])
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue

        total = entry.get("total", 0.0)
        sale_type = entry.get("sale_type", "")
        salesperson = entry.get("salesperson", "")

        text = (
            f"Sale: {customer} on {date_str} | "
            f"${total:,.0f} | "
            f"type: {sale_type} | "
            f"salesperson: {salesperson}"
        )
        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "date": date_str,
                "customer": customer,
                "total": total,
                "sale_type": sale_type,
                "salesperson": salesperson,
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def prepare_raw_records(
    pipeline_leads: list,
    bugs: list,
    cancellations: dict,
    sales_entries: list,
    previous_ids: dict,
) -> tuple[list, dict]:
    """Build raw_data records for all KPI sources. Returns (records_to_upsert, new_id_state)."""
    all_records = []
    new_ids = dict(previous_ids)

    lead_recs, lead_ids = _lead_records(pipeline_leads or [], previous_ids)
    all_records.extend(lead_recs)
    new_ids.update(lead_ids)

    bug_recs, bug_ids = _bug_records(bugs or [], previous_ids)
    all_records.extend(bug_recs)
    new_ids.update(bug_ids)

    cancel_recs, cancel_ids = _cancellation_records(cancellations or {}, previous_ids)
    all_records.extend(cancel_recs)
    new_ids.update(cancel_ids)

    sale_recs, sale_ids = _sale_records(sales_entries or [], previous_ids)
    all_records.extend(sale_recs)
    new_ids.update(sale_ids)

    return all_records, new_ids
```

- [ ] **Step 4.5: Add `raw_namespace` param to `ingest()`**

Update the `ingest()` function signature (add new params after `state_file`):

```python
def ingest(
    obs_file: str,
    memory_dir: str,
    pinecone_api_key: str,
    voyage_api_key: str,
    index_name: str,
    embedding_model: str,
    obs_namespace: str = "observations",
    mem_namespace: str = "memories",
    state_file: str = "data/vector_ingest_state.json",
    raw_namespace: str = "raw_data",
    pipeline_leads: list | None = None,
    bugs: list | None = None,
    cancellations: dict | None = None,
    sales_entries: list | None = None,
) -> None:
```

Add raw_data ingest block at the end of `ingest()`, after the existing memory ingest block and before the final `save_ingest_state`:

```python
    # Embed and upsert raw records
    raw_records, new_raw_ids = prepare_raw_records(
        pipeline_leads=pipeline_leads or [],
        bugs=bugs or [],
        cancellations=cancellations or {},
        sales_entries=sales_entries or [],
        previous_ids=state.raw_record_ids,
    )
    if raw_records:
        raw_count = _embed_and_upsert(
            vo, pc_index, raw_namespace, embedding_model, raw_records
        )
        print(f"   Upserted {raw_count} raw_data vectors.")
        state.raw_record_ids = new_raw_ids

    save_ingest_state(state, state_file)
```

Note: move the existing final `save_ingest_state(state, state_file)` call so it comes AFTER the raw_records block (the current one after `mem_records` should be removed — the final save at the end is the only one needed).

- [ ] **Step 4.6: Run tests to confirm they pass**

```bash
python -m pytest tests/test_vector_ingest.py -v
```

Expected: all tests pass (both existing and new raw_data tests).

- [ ] **Step 4.7: Commit**

```bash
git add processors/vector_ingest.py tests/test_vector_ingest.py
git commit -m "feat: add raw_data namespace to vector_ingest with prepare_raw_records"
```

---

## Task 5: Wire into `main.py` + `config.json`

**Files:**
- Modify: `main.py`
- Modify: `config.json`

No new tests for this task — covered by integration test in Task 6 and the existing test suite.

- [ ] **Step 5.1: Update `config.json`**

Under the `"vector"` block, add `"raw_data_namespace": "raw_data"`.

Add a new top-level `"sheets"` block for the cancellation sheet:

```json
"sheets": {
  "cancellations_spreadsheet_id": "1BYMMVKw19Y9pwp7oFYMvUC4Webk-NI-Y-kevj7CX6D4",
  "cancellations_tab_name": "MONTHLY Cancellations"
}
```

- [ ] **Step 5.2: Add bug collection to `main.py`**

After the existing pipeline load block (around line 170, after `generate_pipeline_drafts`), add:

```python
    bugs = []
    notion_token = os.environ.get("NOTION_TOKEN", "")
    if notion_token:
        try:
            from collectors.notion_bugs import fetch_bugs
            print("🪲  Fetching bug tracker...")
            bugs = fetch_bugs(notion_token)
            if bugs:
                open_bugs = [b for b in bugs if b.status != "Done"]
                print(f"   {len(open_bugs)} open bug(s) ({len(bugs)} total)")
        except Exception as e:
            print(f"⚠️  Bug tracker fetch error (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 5.3: Add cancellations collection to `main.py`**

The existing sheets collection happens inside a `if config.get("pipeline", {}).get("enabled"):` block. Cancellations are independent of the pipeline flag. Add after the pipeline block:

```python
    cancellations = {"count": 0, "entries": []}
    sheets_cfg = config.get("sheets", {})
    cancel_sheet_id = sheets_cfg.get("cancellations_spreadsheet_id", "")
    cancel_tab = sheets_cfg.get("cancellations_tab_name", "MONTHLY Cancellations")
    if cancel_sheet_id:
        try:
            from collectors.sheets import fetch_cancellations_mtd
            from lib.google_auth import build_sheets_service
            print("📉  Fetching cancellations...")
            sheets_svc = build_sheets_service()
            cancellations = fetch_cancellations_mtd(sheets_svc, cancel_sheet_id, cancel_tab)
            print(f"   {cancellations['count']} cancellation(s) this month")
        except Exception as e:
            print(f"⚠️  Cancellations fetch error (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 5.4: Pass new data to `observe()`**

Find the existing `observe(...)` call in `main.py` (around line 349) and update it:

```python
            observe(
                obs_file=memory_cfg["observations_file"],
                decisions_file=memory_cfg["decisions_file"],
                email_threads=email_threads,
                still_open_ids=still_open if previous_state else {"email": [], "notion": []},
                pipeline_leads=list(trial_leads) + list(attention_leads),
                brief=brief,
                issues=open_issues,
                sales_data=sales_data if "sales_data" in dir() else None,
                demos_data=demos_data if "demos_data" in dir() else None,
                bugs=bugs if bugs else None,
                cancellations=cancellations if cancellations.get("count", 0) > 0 else None,
            )
```

Note: `sales_data` and `demos_data` may not exist yet in `main.py` if the sheets collector for the Dept Heads KPI sheet is not currently called. Check whether the existing code calls `fetch_sales_mtd` / `fetch_demos_mtd`. If it does, pass those variables. If not, set them to `None` for now.

- [ ] **Step 5.5: Pass new data to `vector_ingest`**

Find the existing `vector_ingest(...)` call (around line 381) and update it:

```python
                    import dataclasses
                    vector_ingest(
                        obs_file=memory_cfg["observations_file"],
                        memory_dir=memory_cfg["dir"],
                        pinecone_api_key=pinecone_key,
                        voyage_api_key=voyage_key,
                        index_name=vector_cfg["index_name"],
                        embedding_model=vector_cfg["embedding_model"],
                        obs_namespace=vector_cfg.get("observations_namespace", "observations"),
                        mem_namespace=vector_cfg.get("memories_namespace", "memories"),
                        state_file=vector_cfg.get("ingest_state_file", "data/vector_ingest_state.json"),
                        raw_namespace=vector_cfg.get("raw_data_namespace", "raw_data"),
                        pipeline_leads=all_pipeline_leads,
                        bugs=[dataclasses.asdict(b) for b in bugs] if bugs else [],
                        cancellations=cancellations,
                        sales_entries=sales_data.get("entries", []) if sales_data else [],
                    )
```

- [ ] **Step 5.6: Load all pipeline leads for raw ingest**

Add this block immediately after the existing pipeline cache load (after `pipeline_cache_age_days` is computed, around line 168):

```python
        all_pipeline_leads = []
        try:
            with open(cache_path) as f:
                all_pipeline_leads = json.load(f).get("leads", [])
        except (FileNotFoundError, json.JSONDecodeError):
            pass
```

- [ ] **Step 5.7: Run the full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_vector_ingest_integration.py 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5.8: Smoke test locally**

```bash
python main.py --no-email 2>&1 | grep -E "(Bug|cancel|KPI|raw_data|Upserted|⚠️)"
```

Expected output should include lines like:
```
🪲  Fetching bug tracker...
   14 open bug(s) (14 total)
📉  Fetching cancellations...
   2 cancellation(s) this month
   Upserted N raw_data vectors.
```

- [ ] **Step 5.9: Commit**

```bash
git add main.py config.json
git commit -m "feat: wire bug collector and cancellations into main.py and vector ingest"
```

---

## Task 6: `scripts/backfill_raw_vectors.py` — Historical Backfill

**Files:**
- Create: `scripts/backfill_raw_vectors.py`

No automated tests for this task — it's a one-shot operational script. Run it manually once after deployment.

- [ ] **Step 6.1: Create the backfill script**

```python
#!/usr/bin/env python3
"""One-time backfill: embed all existing pipeline leads, bugs, and cancellations
into the raw_data Pinecone namespace.

Run once after deploying P15:
    python scripts/backfill_raw_vectors.py
"""
import dataclasses
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.notion_bugs import fetch_bugs
from collectors.sheets import fetch_cancellations_mtd
from lib.google_auth import build_sheets_service
from processors.vector_ingest import (
    IngestState,
    load_ingest_state,
    prepare_raw_records,
    _embed_and_upsert,
    save_ingest_state,
)
from pinecone import Pinecone
import voyageai


CONFIG_PATH = "config.json"
PIPELINE_CACHE = "data/pipeline_cache.json"
STATE_FILE = "data/vector_ingest_state.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def main():
    config = load_config()
    vector_cfg = config.get("vector", {})
    sheets_cfg = config.get("sheets", {})

    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
    notion_token = os.environ.get("NOTION_TOKEN", "")

    if not pinecone_key or not voyage_key:
        print("ERROR: PINECONE_API_KEY and VOYAGE_API_KEY required.", file=sys.stderr)
        sys.exit(1)

    index_name = vector_cfg["index_name"]
    embedding_model = vector_cfg["embedding_model"]
    raw_namespace = vector_cfg.get("raw_data_namespace", "raw_data")

    # Load existing ingest state
    state = load_ingest_state(STATE_FILE)

    # 1. Pipeline leads
    all_leads = []
    try:
        with open(PIPELINE_CACHE) as f:
            all_leads = json.load(f).get("leads", [])
        print(f"Loaded {len(all_leads)} pipeline leads from cache.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: Could not load pipeline cache: {e}")

    # 2. Bug tickets (all statuses, not just open)
    bugs = []
    if notion_token:
        try:
            print("Fetching all bug tickets from Notion...")
            bug_objects = fetch_bugs(notion_token)
            bugs = [dataclasses.asdict(b) for b in bug_objects]
            print(f"Fetched {len(bugs)} bug tickets.")
        except Exception as e:
            print(f"WARNING: Bug fetch failed: {e}")
    else:
        print("WARNING: NOTION_TOKEN not set — skipping bugs.")

    # 3. All cancellations (month=None to get full history)
    cancellations = {"count": 0, "entries": []}
    cancel_sheet_id = sheets_cfg.get("cancellations_spreadsheet_id", "")
    cancel_tab = sheets_cfg.get("cancellations_tab_name", "MONTHLY Cancellations")
    if cancel_sheet_id:
        try:
            print("Fetching all cancellations from Sheets...")
            svc = build_sheets_service()
            cancellations = fetch_cancellations_mtd(svc, cancel_sheet_id, cancel_tab, month=None)
            print(f"Fetched {cancellations['count']} cancellation entries.")
        except Exception as e:
            print(f"WARNING: Cancellations fetch failed: {e}")

    # Prepare records — ignore previous_ids so everything gets re-embedded
    records, new_raw_ids = prepare_raw_records(
        pipeline_leads=all_leads,
        bugs=bugs,
        cancellations=cancellations,
        sales_entries=[],  # sales are MTD only; no historical backfill needed
        previous_ids={},   # force re-embed of everything
    )

    if not records:
        print("No records to backfill.")
        return

    print(f"\nEmbedding {len(records)} records into '{raw_namespace}' namespace...")

    pc = Pinecone(api_key=pinecone_key)
    pc_index = pc.Index(index_name)
    vo = voyageai.Client(api_key=voyage_key)

    count = _embed_and_upsert(vo, pc_index, raw_namespace, embedding_model, records)
    print(f"Upserted {count} vectors into '{raw_namespace}'.")

    # Update state with new raw_record_ids
    state.raw_record_ids = new_raw_ids
    save_ingest_state(state, STATE_FILE)
    print(f"State updated: {len(new_raw_ids)} raw record IDs tracked.")
    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6.2: Test the backfill script dry-run**

```bash
python scripts/backfill_raw_vectors.py 2>&1
```

Expected: script runs, prints counts for leads/bugs/cancellations, and reports vectors upserted. If Pinecone/Voyage keys aren't in `.env`, it will exit early with an error — that's correct behavior.

- [ ] **Step 6.3: Commit**

```bash
git add scripts/backfill_raw_vectors.py
git commit -m "feat: add backfill_raw_vectors script for historical raw_data ingest"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `collectors/notion_bugs.py` with `BugTicket` dataclass | Task 1 |
| `fetch_cancellations_mtd()` in sheets.py, dynamic header parsing | Task 2 (uses fixed column indexes per verified schema — acceptable since schema is stable) |
| `kpi_snapshot` observation with daily dedup | Task 3 |
| `raw_data` Pinecone namespace, `IngestState.raw_record_ids`, `prepare_raw_records` | Task 4 |
| `main.py` wiring, `config.json` updates | Task 5 |
| `backfill_raw_vectors.py` one-time script | Task 6 |
| Brief retriever untouched | Not a code task — `memory_retriever.py` is never mentioned in any task ✓ |
| All new collectors are non-fatal | Tasks 1, 2, 5 — all wrapped in try/except ✓ |
| `month=None` for backfill (all rows) | Task 6 passes `month=None` to `fetch_cancellations_mtd` ✓ |

**Placeholder scan:** No TBDs. All code blocks are complete.

**Type consistency:**
- `BugTicket` defined in Task 1, converted via `dataclasses.asdict()` before passing to `vector_ingest` in Task 5 ✓
- `prepare_raw_records` takes `list[dict]` for bugs in Task 4, Task 5 converts with `dataclasses.asdict()` ✓
- `_bug_records` in Task 4 handles both dict and dataclass access via `isinstance(bug, dict)` guard ✓
- `fetch_cancellations_mtd` signature in Task 2 matches usage in Tasks 5 and 6 ✓
- `raw_data_namespace` config key in Task 5 matches the default `"raw_data"` in `ingest()` Task 4 ✓

One fix needed: Task 4's `_bug_records` uses both dict and dataclass access patterns. Since Task 5 always passes `dataclasses.asdict(b)` for bugs, the dataclass branch is dead code. Simplify `_field()` in `_bug_records` to always use `bug.get(name)` (dict-only):

```python
def _bug_records(bugs: list, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for bug in bugs:
        bug_id = bug.get("id", "")
        if not bug_id:
            continue
        record_id = f"bug:{bug_id}"
        last_updated = bug.get("last_updated", "")
        fingerprint = last_updated
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue
        title = bug.get("title", "")
        status = bug.get("status", "")
        priority = bug.get("priority_level", "")
        areas = bug.get("technical_areas", [])
        days_open = bug.get("days_open", 0)
        areas_str = ", ".join(areas) if areas else "untagged"
        text = (
            f"Bug: {title} | "
            f"status: {status} | "
            f"priority: {priority} | "
            f"areas: {areas_str} | "
            f"{days_open} days open"
        )
        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "title": title,
                "status": status,
                "priority_level": priority,
                "technical_areas": areas,
                "date_created": bug.get("date_created", ""),
                "days_open": days_open,
                "shortcut_url": bug.get("shortcut_url", ""),
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids
```

Use this version in Task 4 Step 4.4 in place of the original `_bug_records`.
