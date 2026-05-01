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


import os as _os_module, json as _json_module
from processors.meeting_prep import build_external_context


def test_build_external_context_people_match(tmp_path):
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    (people_dir / "mike-woodby.md").write_text("Mike Woodby — Apex Holland coach.")
    config = {
        "people_dir": str(people_dir),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Mike Woodby: OS Demo", attendees=["mike@apexholland.co"])
    result = build_external_context(event, config)
    assert "Mike Woodby" in result
    assert "Apex Holland" in result


def test_build_external_context_pipeline_match(tmp_path):
    pipeline = {"leads": [{"name": "Apex Holland", "status": "In-Trial", "contact": "Mike Woodby", "email": "mike@apexholland.co", "days_since_contact": 10, "estimated_value": 2000, "stale": False, "priority": "High", "last_contacted": "2026-04-20", "source": None}]}
    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(_json_module.dumps(pipeline))
    config = {
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(pipeline_path)},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Apex Holland Demo", attendees=["mike@apexholland.co"])
    result = build_external_context(event, config)
    assert "In-Trial" in result or "Apex Holland" in result


def test_build_external_context_empty_when_no_data(tmp_path):
    config = {
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Unknown Person Demo")
    result = build_external_context(event, config)
    assert isinstance(result, str)


from processors.meeting_prep import build_dept_heads_context, build_recurring_internal_context


def test_build_dept_heads_context_pipeline_summary(tmp_path):
    pipeline = {"leads": [
        {"name": "Tyler Landeck", "status": "In-Trial / Post Demo", "estimated_value": 2000, "stale": True, "contact": "", "email": "", "days_since_contact": 40, "priority": "High", "last_contacted": "2026-03-20", "source": None},
        {"name": "Mike Woodby", "status": "Out of Demo / Need Update", "estimated_value": None, "stale": False, "contact": "", "email": "", "days_since_contact": 5, "priority": "Medium", "last_contacted": "2026-04-25", "source": None},
    ]}
    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(_json_module.dumps(pipeline))
    config = {
        "pipeline": {"cache_path": str(pipeline_path)},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    result = build_dept_heads_context(config)
    assert "In-Trial" in result or "Tyler" in result
    assert "Out of Demo" in result or "Mike" in result


def test_build_dept_heads_context_no_crash_missing_files(tmp_path):
    config = {
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    result = build_dept_heads_context(config)
    assert isinstance(result, str)


def test_build_recurring_internal_context_observations(tmp_path):
    obs_path = tmp_path / "obs.jsonl"
    obs_path.write_text(
        _json_module.dumps({"date": "2026-04-28", "type": "top_priority", "entity": "priorities", "content": "Discussed LTV with Luke — he wants a demo next week", "source": "brief"}) + "\n"
    )
    projects_file = tmp_path / "projects.md"
    projects_file.write_text("## Project: LTV Lead Magnet\n**Next:** Design UI\n")
    config = {
        "memory": {"observations_file": str(obs_path)},
        "projects_file": str(projects_file),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Luke / Trent")
    result = build_recurring_internal_context(event, config)
    assert "luke" in result.lower() or "LTV" in result


def test_build_recurring_internal_context_no_crash_missing_files(tmp_path):
    config = {
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
        "projects_file": str(tmp_path / "projects.md"),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Luke / Trent")
    result = build_recurring_internal_context(event, config)
    assert isinstance(result, str)


from unittest.mock import patch as _patch
from processors.meeting_prep import build_prep_message


@_patch("processors.meeting_prep.anthropic.Anthropic")
def test_build_prep_message_external(mock_cls, tmp_path):
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = type("R", (), {
        "content": [type("C", (), {"text": "• Who: Mike\n• Context: Demo stage\n• Open: Contract\n• Goal: Close\n• Opener: How's Q2?"})()],
        "usage": type("U", (), {"input_tokens": 100, "output_tokens": 50})(),
    })()
    config = {
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Mike: OS Demo", attendees=["mike@apex.co"])
    result = build_prep_message(event, "external", config, api_key="test-key")
    assert "🎯" in result
    assert "Mike: OS Demo" in result
    assert "Who" in result


@_patch("processors.meeting_prep.anthropic.Anthropic")
def test_build_prep_message_dept_heads(mock_cls, tmp_path):
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = type("R", (), {
        "content": [type("C", (), {"text": "Pipeline: 3 in trial\nSignals: Q2 push\nTalking Points: Stale leads"})()],
        "usage": type("U", (), {"input_tokens": 100, "output_tokens": 50})(),
    })()
    config = {
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Department Heads Weekly")
    result = build_prep_message(event, "dept_heads", config, api_key="test-key")
    assert "📊" in result
    assert "Department Heads" in result


@_patch("processors.meeting_prep.anthropic.Anthropic")
def test_build_prep_message_recurring_internal(mock_cls, tmp_path):
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = type("R", (), {
        "content": [type("C", (), {"text": "Last Time: Discussed LTV\nOpen Items: Follow up demo\nProjects: LTV magnet\nFocus: Push to close"})()],
        "usage": type("U", (), {"input_tokens": 100, "output_tokens": 50})(),
    })()
    config = {
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
        "projects_file": str(tmp_path / "projects.md"),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Luke / Trent")
    result = build_prep_message(event, "recurring_internal", config, api_key="test-key")
    assert "📋" in result
    assert "Luke / Trent" in result
