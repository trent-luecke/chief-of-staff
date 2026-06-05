import pytest
from datetime import date
from processors.what_moved import build_what_moved_context, WHAT_MOVED_CAP
from unittest.mock import MagicMock


def _make_transcript(call_type: str, start_at: str, participants: list[str], summary: str):
    t = MagicMock()
    t.call_type = call_type
    t.start_at = start_at
    t.participants = participants
    t.summary = summary
    return t


def _make_onboarding(page_id: str, customer_name: str, status: str, current_phase: str = "Phase 1"):
    return {"page_id": page_id, "customer_name": customer_name, "status": status, "current_phase": current_phase}


def _make_lead(name: str, status: str = "Demo Scheduled"):
    return {"name": name, "status": status, "last_contacted": None}


def test_returns_empty_string_when_no_events():
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_includes_cancellation_from_yesterday():
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/4", "account_name": "Iron Works", "reason": "budget"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Iron Works" in result
    assert "budget" in result


def test_excludes_cancellation_not_from_yesterday():
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/1", "account_name": "Old Gym", "reason": "price"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_includes_unhosted_demo_from_yesterday():
    t = _make_transcript(
        call_type="demo",
        start_at="2026-06-04T15:00:00Z",
        participants=["Alex Smith"],
        summary="Strong interest in OS pricing.",
    )
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[t],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Alex Smith" in result
    assert "Strong interest" in result


def test_excludes_non_demo_avoma_call():
    t = _make_transcript(
        call_type="onboarding",
        start_at="2026-06-04T15:00:00Z",
        participants=["Alex Smith"],
        summary="Phase 1 complete.",
    )
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[t],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_excludes_demo_not_from_yesterday():
    t = _make_transcript(
        call_type="demo",
        start_at="2026-06-02T15:00:00Z",
        participants=["Old Lead"],
        summary="Old demo.",
    )
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[t],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_detects_new_onboarding_entry():
    current = [_make_onboarding("abc", "Apex Gym", "In Progress", "Phase 1 — Initial Setup")]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=current,
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Apex Gym" in result
    assert "entered onboarding" in result


def test_detects_onboarding_phase_change():
    prev = [_make_onboarding("abc", "Apex Gym", "In Progress", "Phase 1 — Initial Setup")]
    current = [_make_onboarding("abc", "Apex Gym", "In Progress", "Phase 2 — Member Profile Upload")]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=current,
        onboarding_prev=prev,
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Apex Gym" in result
    assert "Phase 1" in result
    assert "Phase 2" in result


def test_no_event_for_unchanged_onboarding():
    entry = _make_onboarding("abc", "Apex Gym", "In Progress", "Phase 1 — Initial Setup")
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[entry],
        onboarding_prev=[entry],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_detects_new_pipeline_lead():
    current = [_make_lead("New Gym LLC", "Demo Scheduled")]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=current,
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "New Gym LLC" in result
    assert "entered pipeline" in result


def test_existing_pipeline_lead_not_included():
    lead = _make_lead("Existing Gym", "Demo Scheduled")
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[lead],
        pipeline_prev=[lead],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_cap_is_enforced():
    # 10 new pipeline leads — should be capped at WHAT_MOVED_CAP
    current = [_make_lead(f"Gym {i}") for i in range(10)]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=current,
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    lines = [l for l in result.split("\n") if "entered pipeline" in l]
    assert len(lines) == WHAT_MOVED_CAP


def test_priority_order_cancellation_before_lead():
    current = [_make_lead("New Gym LLC")]
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/4", "account_name": "Iron Works", "reason": "budget"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=current,
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    iron_pos = result.index("Iron Works")
    gym_pos = result.index("New Gym LLC")
    assert iron_pos < gym_pos


def test_includes_header_when_events_present():
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/4", "account_name": "Iron Works", "reason": "budget"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "What Moved Yesterday" in result
