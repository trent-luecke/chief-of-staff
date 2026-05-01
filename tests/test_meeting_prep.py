import pytest
from datetime import datetime
from collectors.calendar import CalendarEvent
from processors.meeting_prep import classify_meeting

BASE_CONFIG = {
    "meeting_prep": {
        "dept_heads_patterns": ["department heads", "dept heads"],
        "recurring_internal_patterns": ["marketing sync", "os weekly", "luke / trent", "luke/trent"],
    }
}

def _event(summary, attendees=None):
    now = datetime.now()
    return CalendarEvent(
        id="test-id",
        summary=summary,
        start=now,
        end=now,
        attendees=attendees or [],
    )


def test_classify_dept_heads():
    assert classify_meeting(_event("Department Heads Weekly"), BASE_CONFIG) == "dept_heads"

def test_classify_dept_heads_case_insensitive():
    assert classify_meeting(_event("DEPARTMENT HEADS"), BASE_CONFIG) == "dept_heads"

def test_classify_recurring_internal_marketing():
    assert classify_meeting(_event("OS Weekly Marketing Sync"), BASE_CONFIG) == "recurring_internal"

def test_classify_recurring_internal_luke():
    assert classify_meeting(_event("Luke / Trent"), BASE_CONFIG) == "recurring_internal"

def test_classify_external_by_keyword():
    assert classify_meeting(_event("Mike: OS Demo"), BASE_CONFIG) == "external"

def test_classify_external_by_attendee():
    assert classify_meeting(
        _event("Intro call", attendees=["coach@apexholland.co"]),
        BASE_CONFIG
    ) == "external"

def test_classify_skips_personal():
    assert classify_meeting(_event("Haircut"), BASE_CONFIG) is None

def test_classify_skips_generic_internal():
    assert classify_meeting(
        _event("TeamBuildr Standup", attendees=["team@teambuildr.com"]),
        BASE_CONFIG
    ) is None

def test_dept_heads_takes_priority_over_external():
    assert classify_meeting(_event("Department Heads Demo Review"), BASE_CONFIG) == "dept_heads"

def test_classify_external_by_keyword_no_attendees():
    assert classify_meeting(_event("Customer Demo"), BASE_CONFIG) == "external"


from collectors.sheets import month_label, fetch_sales_mtd, fetch_demos_mtd
from unittest.mock import MagicMock
from datetime import date


def test_month_label_current():
    label = month_label(0)
    today = date.today()
    expected = today.strftime("%B %Y")
    assert label == expected


def test_month_label_prior():
    label = month_label(-1)
    today = date.today()
    if today.month == 1:
        expected_year = today.year - 1
        expected_month = 12
    else:
        expected_year = today.year
        expected_month = today.month - 1
    from datetime import date as d
    expected = d(expected_year, expected_month, 1).strftime("%B %Y")
    assert label == expected


def test_fetch_sales_mtd_parses_rows():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.return_value = {
        "values": [
            ["`"],
            ["TeamBuildr OS Sales"],
            ["Date", "Sales", "Type", "Total Sale", "Customer Name", "Salesperson"],
            ["4/16/2026", "$200", "MONTHLY", "$1,800.00", "GRIT Athlete", "Trent"],
            ["4/28/2026", "$2,150", "ANNUAL", "$2,150.00", "Alapa Performance", "Trent"],
            [],
        ]
    }
    result = fetch_sales_mtd(mock_service, "fake-id", "April 2026")
    assert result["count"] == 2
    assert result["revenue"] == 3950.0
    assert result["entries"][0]["customer"] == "GRIT Athlete"


def test_fetch_sales_mtd_missing_tab_returns_empty():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.side_effect = Exception("Tab not found")
    result = fetch_sales_mtd(mock_service, "fake-id", "April 2026")
    assert result == {"count": 0, "revenue": 0.0, "entries": []}


def test_fetch_demos_mtd_parses_rows():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.return_value = {
        "values": [
            ["Event ID", "Date", "Event Title", "Salesperson", "Attendees"],
            ["abc123", "2026-04-01", "Demo with Mike", "Trent", "mike@apex.co"],
            ["def456", "2026-04-07", "Demo with Ben", "Luke Martin", "ben@adaptfs.com"],
        ]
    }
    result = fetch_demos_mtd(mock_service, "fake-id", "April 2026")
    assert result["count"] == 2
    assert result["entries"][0]["salesperson"] == "Trent"


def test_fetch_demos_mtd_missing_tab_returns_empty():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.side_effect = Exception("Tab not found")
    result = fetch_demos_mtd(mock_service, "fake-id", "April 2026")
    assert result == {"count": 0, "entries": []}


import json as _json_module
from datetime import date as _date_module, timedelta
from processors.meeting_prep import make_prep_key, load_prep_state, save_prep_state


def test_make_prep_key():
    event = _event("Luke / Trent")
    event.id = "abc123"
    key = make_prep_key(event)
    assert key == f"abc123_{_date_module.today().isoformat()}"


def test_load_prep_state_missing_file():
    assert load_prep_state("/nonexistent/path.json") == set()


def test_load_prep_state_corrupt_file(tmp_path):
    p = tmp_path / "preps.json"
    p.write_text("not json")
    assert load_prep_state(str(p)) == set()


def test_save_and_load_roundtrip(tmp_path):
    p = str(tmp_path / "preps.json")
    keys = {f"event1_{_date_module.today().isoformat()}", f"event2_{_date_module.today().isoformat()}"}
    save_prep_state(keys, p)
    assert load_prep_state(p) == keys


def test_save_prunes_old_keys(tmp_path):
    p = str(tmp_path / "preps.json")
    old_date = (_date_module.today() - timedelta(days=8)).isoformat()
    old_key = f"old_event_{old_date}"
    today_key = f"new_event_{_date_module.today().isoformat()}"
    save_prep_state({old_key, today_key}, p)
    loaded = load_prep_state(p)
    assert today_key in loaded
    assert old_key not in loaded
