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
from lib.storage import LocalStorage
from processors.meeting_prep import make_prep_key, load_prep_state, save_prep_state


def test_make_prep_key():
    event = _event("Luke / Trent")
    event.id = "abc123"
    key = make_prep_key(event)
    assert key == f"abc123_{_date_module.today().isoformat()}"


def test_load_prep_state_missing_file(tmp_path):
    storage = LocalStorage(str(tmp_path))
    assert load_prep_state(storage) == set()


def test_load_prep_state_corrupt_file(tmp_path):
    storage = LocalStorage(str(tmp_path))
    storage.write("meeting_preps.json", "not json")
    assert load_prep_state(storage) == set()


def test_save_and_load_roundtrip(tmp_path):
    storage = LocalStorage(str(tmp_path))
    keys = {f"event1_{_date_module.today().isoformat()}", f"event2_{_date_module.today().isoformat()}"}
    save_prep_state(keys, storage)
    assert load_prep_state(storage) == keys


def test_save_prunes_old_keys(tmp_path):
    storage = LocalStorage(str(tmp_path))
    old_date = (_date_module.today() - timedelta(days=8)).isoformat()
    old_key = f"old_event_{old_date}"
    today_key = f"new_event_{_date_module.today().isoformat()}"
    save_prep_state({old_key, today_key}, storage)
    loaded = load_prep_state(storage)
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
import json as _json_for_meeting


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


def test_build_recurring_internal_context_reads_memory_file(tmp_path):
    meeting_index = {"meetings": [{"calendar_pattern": "marketing sync", "memory_file": "data/meeting_memory/marketing_sync.md", "nudge_subject": "Notes?", "nudge_minutes_after": 5}]}
    idx_path = tmp_path / "meeting_index.json"
    idx_path.write_text(_json_for_meeting.dumps(meeting_index))

    from lib.storage import LocalStorage
    storage = LocalStorage(str(tmp_path))
    storage.write(
        "meeting_memory/marketing_sync.md",
        "# Marketing Sync\n\n## Current State\nSolid working relationship.\n\n## Open Threads\n- Budget review\n\n## Session Log\n\n### 2026-04-28\nDiscussed Q2 priorities.\n",
    )

    obs_path = tmp_path / "obs.jsonl"
    obs_path.write_text(_json_for_meeting.dumps({"date": "2026-04-28", "type": "note", "entity": "", "content": "marketing sync discussion", "source": "brief"}) + "\n")

    config = {
        "data_dir": str(tmp_path),
        "meeting_index_file": str(idx_path),
        "memory": {"observations_file": str(obs_path)},
        "projects_file": str(tmp_path / "projects.md"),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Weekly Marketing Sync")
    result = build_recurring_internal_context(event, config)
    assert "Current State" in result
    assert "Solid working relationship" in result
    assert "## Recent Context" not in result


def test_build_recurring_internal_context_falls_back_to_observations(tmp_path):
    obs_path = tmp_path / "obs.jsonl"
    obs_path.write_text(_json_for_meeting.dumps({"date": "2026-04-28", "type": "note", "entity": "", "content": "Discussed product roadmap with Luke", "source": "brief"}) + "\n")

    config = {
        "data_dir": str(tmp_path),
        "memory": {"observations_file": str(obs_path)},
        "projects_file": str(tmp_path / "projects.md"),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Luke / Trent")
    result = build_recurring_internal_context(event, config)
    assert "Recent Context" in result
    assert "product roadmap" in result
    assert "Luke" in result


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
    with _upatch("processors.meeting_prep._fetch_gmail_context",
                 return_value="## Email History (mike@apex.co)\n  [2026-05-28] Demo confirmed"):
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


# ── Tiered Gmail fallback (gaps 1 + 2) ─────────────────────────────────────

from unittest.mock import patch as _upatch


def test_build_external_context_calls_gmail_when_no_local_context(tmp_path):
    """When all three local sources miss, Gmail lookup is attempted."""
    config = {
        "email": "trent@teambuildr.com",
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Bre / Trent", attendees=["bre@crossfitcentral.com"])

    with _upatch("processors.meeting_prep._fetch_gmail_context", return_value="## Email History\n• Calendly booking confirmed") as mock_gmail:
        result = build_external_context(event, config)

    mock_gmail.assert_called_once()
    assert "Email History" in result
    assert "Calendly" in result


def test_build_external_context_skips_gmail_when_person_file_found(tmp_path):
    """When a person file is found, Gmail is NOT called (Tier 1 path)."""
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    (people_dir / "bre-smith.md").write_text("Bre Smith — CrossFit Central owner.")
    config = {
        "email": "trent@teambuildr.com",
        "people_dir": str(people_dir),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Bre / Trent", attendees=["bre@crossfitcentral.com"])

    with _upatch("processors.meeting_prep._fetch_gmail_context") as mock_gmail:
        result = build_external_context(event, config)

    mock_gmail.assert_not_called()
    assert "Bre Smith" in result


def test_build_external_context_returns_empty_when_gmail_also_empty(tmp_path):
    """When all sources (including Gmail) return nothing, context is empty string."""
    config = {
        "email": "trent@teambuildr.com",
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Bre / Trent", attendees=["bre@crossfitcentral.com"])

    with _upatch("processors.meeting_prep._fetch_gmail_context", return_value=""):
        result = build_external_context(event, config)

    assert result == ""


def test_build_prep_message_returns_none_when_no_external_context(tmp_path):
    """No person file, no pipeline, no Gmail → returns None (Tier 3 suppress). No Claude call."""
    config = {
        "email": "trent@teambuildr.com",
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Bre / Trent", attendees=["bre@crossfitcentral.com"])

    with _upatch("processors.meeting_prep._fetch_gmail_context", return_value=""):
        with _upatch("processors.meeting_prep.anthropic.Anthropic") as mock_anthropic:
            result = build_prep_message(event, "external", config, api_key="test-key")

    assert result is None
    mock_anthropic.assert_not_called()


@_patch("processors.meeting_prep.anthropic.Anthropic")
def test_build_prep_message_calls_claude_with_gmail_context(mock_cls, tmp_path):
    """When only Gmail context is available, Claude is called with that context."""
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = type("R", (), {
        "content": [type("C", (), {"text": "• Who: Bre Smith\n• Context: Calendly inbound\n• Open: None\n• Goal: Demo\n• Opener: Tell me about CrossFit Central"})()],
        "usage": type("U", (), {"input_tokens": 120, "output_tokens": 60})(),
    })()
    config = {
        "email": "trent@teambuildr.com",
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Bre / Trent", attendees=["bre@crossfitcentral.com"])

    with _upatch("processors.meeting_prep._fetch_gmail_context",
                 return_value="## Email History (bre@crossfitcentral.com)\n  [2026-05-28] Calendly confirmed — Looking forward to our call"):
        result = build_prep_message(event, "external", config, api_key="test-key")

    assert result is not None
    assert "🎯" in result
    call_kwargs = mock_client.messages.create.call_args
    user_msg = call_kwargs.kwargs["messages"][0]["content"] if call_kwargs.kwargs else call_kwargs[1]["messages"][0]["content"]
    assert "Email History" in user_msg
    assert "Calendly" in user_msg


# ── Session 3: person-centric read path ─────────────────────────────────────

import json as _j
from processors.meeting_prep import _find_observations, _resolve_person_from_registry


# Job 1a — stamped observation found by person_id even when content has no name tokens

def test_find_observations_stamped_by_id_found_without_name_in_content(tmp_path):
    obs_path = tmp_path / "obs.jsonl"
    obs_path.write_text(
        _j.dumps({
            "date": "2026-05-28",
            "type": "signal",
            "content": "Expressed interest in annual plan.",
            "primary_person_id": "ryan-pace",
        }) + "\n"
    )
    result = _find_observations(str(obs_path), tokens=["xyz-no-match"], person_id="ryan-pace")
    assert len(result) == 1
    assert "Expressed interest in annual plan" in result[0]


# Job 1b — unstamped observation still found via content tokens (legacy fallback)

def test_find_observations_unstamped_fallback_to_content_tokens(tmp_path):
    obs_path = tmp_path / "obs.jsonl"
    obs_path.write_text(
        _j.dumps({
            "date": "2026-05-01",
            "type": "note",
            "content": "Ryan Pace demo went well — interested in annual.",
        }) + "\n"
    )
    result = _find_observations(str(obs_path), tokens=["ryan", "pace"], person_id="ryan-pace")
    assert len(result) == 1
    assert "Ryan Pace" in result[0]


# Job 1c — stamped obs for person-A NOT returned when looking up person-B

def test_find_observations_stamped_obs_not_leaked_across_people(tmp_path):
    obs_path = tmp_path / "obs.jsonl"
    obs_path.write_text(
        _j.dumps({
            "date": "2026-05-28",
            "content": "ryan pace discussion.",
            "primary_person_id": "ryan-pace",
        }) + "\n"
    )
    # Looking up a different person who happens to have "ryan" in their token list
    result = _find_observations(str(obs_path), tokens=["ryan"], person_id="some-other-person")
    assert result == []


# Job 1d — registry resolver: known email returns person_id and all emails

def test_resolve_person_from_registry_known_email(tmp_path):
    reg = {
        "version": 1,
        "people": [{
            "id": "ryan-pace",
            "canonical_name": "Ryan Pace",
            "email": "coachpace@realflowperformance.com",
            "aliases": ["Ryan Pace", "coachpace@realflowperformance.com", "pace@old-domain.com"],
            "type": "lead",
        }]
    }
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(_j.dumps(reg))
    person_id, all_emails = _resolve_person_from_registry(str(reg_path), "coachpace@realflowperformance.com")
    assert person_id == "ryan-pace"
    assert "coachpace@realflowperformance.com" in all_emails
    assert "pace@old-domain.com" in all_emails


# Job 1e — registry resolver: unknown email returns (None, [email])

def test_resolve_person_from_registry_unknown_email(tmp_path):
    reg = {"version": 1, "people": []}
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(_j.dumps(reg))
    person_id, all_emails = _resolve_person_from_registry(str(reg_path), "unknown@x.com")
    assert person_id is None
    assert all_emails == ["unknown@x.com"]


# Job 1f — registry resolver: missing registry file returns (None, [email]) gracefully

def test_resolve_person_from_registry_missing_file(tmp_path):
    person_id, all_emails = _resolve_person_from_registry(str(tmp_path / "missing.json"), "x@x.com")
    assert person_id is None
    assert all_emails == ["x@x.com"]


# Job 2 — _fetch_gmail_context queries all known addresses, not just calendar email

def test_fetch_gmail_context_queries_all_known_addresses(tmp_path):
    """When a person has two known addresses, fetch_threads is called with a query covering both."""
    reg = {
        "version": 1,
        "people": [{
            "id": "ryan-pace",
            "canonical_name": "Ryan Pace",
            "email": "coachpace@realflowperformance.com",
            "aliases": ["Ryan Pace", "coachpace@realflowperformance.com", "rpace@gmail.com"],
            "type": "lead",
        }]
    }
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(_j.dumps(reg))

    config = {
        "email": "trent@teambuildr.com",
        "registry_path": str(reg_path),
    }
    event = _event("Ryan Pace: Cold Demo", attendees=["coachpace@realflowperformance.com"])

    with _upatch("processors.meeting_prep.fetch_threads_needing_attention", return_value=[]) as mock_fetch:
        from processors.meeting_prep import _fetch_gmail_context
        _fetch_gmail_context(event, config)

    assert mock_fetch.called
    call_args = mock_fetch.call_args
    query = call_args.kwargs.get("query", "")
    assert "rpace@gmail.com" in query
    assert "coachpace@realflowperformance.com" in query


# Job 3 — Gmail fires when pipeline record exists but no people file

def test_build_external_context_gmail_fires_with_pipeline_but_no_people_file(tmp_path):
    pipeline = {"leads": [{"name": "Ryan Pace", "status": "In-Trial", "contact": "Ryan Pace",
                           "email": "coachpace@realflowperformance.com", "days_since_contact": 5,
                           "estimated_value": 2000, "stale": False, "priority": "High",
                           "last_contacted": "2026-05-20", "source": None}]}
    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(_j.dumps(pipeline))

    config = {
        "email": "trent@teambuildr.com",
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(pipeline_path)},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
        "registry_path": str(tmp_path / "registry.json"),
    }
    event = _event("Ryan Pace: Cold Demo", attendees=["coachpace@realflowperformance.com"])

    with _upatch("processors.meeting_prep._fetch_gmail_context",
                 return_value="## Email History\n  [2026-05-20] Calendly confirmed") as mock_gmail:
        result = build_external_context(event, config)

    mock_gmail.assert_called_once()
    assert "Email History" in result
    assert "Pipeline Record" in result  # pipeline and Gmail both present


# Job 3 — Gmail still suppressed when people file IS found (Tier 1 unchanged)

def test_build_external_context_gmail_suppressed_when_people_file_found_job3(tmp_path):
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    (people_dir / "ryan-pace.md").write_text("Ryan Pace — Real Flow Performance coach.")

    pipeline = {"leads": [{"name": "Ryan Pace", "status": "In-Trial", "contact": "",
                           "email": "coachpace@realflowperformance.com", "days_since_contact": 5,
                           "estimated_value": 2000, "stale": False, "priority": "High",
                           "last_contacted": "2026-05-20", "source": None}]}
    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(_j.dumps(pipeline))

    config = {
        "email": "trent@teambuildr.com",
        "people_dir": str(people_dir),
        "pipeline": {"cache_path": str(pipeline_path)},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
        "registry_path": str(tmp_path / "registry.json"),
    }
    event = _event("Ryan Pace: Cold Demo", attendees=["coachpace@realflowperformance.com"])

    with _upatch("processors.meeting_prep._fetch_gmail_context") as mock_gmail:
        result = build_external_context(event, config)

    mock_gmail.assert_not_called()
    assert "Ryan Pace" in result
