# tests/test_meeting_memory.py
from datetime import datetime
import pytest
from processors.meeting_memory import (
    load_meeting_index, find_meeting_for_event, append_session_notes,
    load_last_session_summary, MeetingConfig,
)
from collectors.calendar import CalendarEvent


def make_event(summary: str) -> CalendarEvent:
    dt = datetime(2026, 4, 21, 10, 0)
    return CalendarEvent(id="e1", summary=summary, start=dt, end=dt)


def test_find_meeting_for_event_matches_pattern():
    configs = [
        MeetingConfig(calendar_pattern="product", memory_file="data/meeting_memory/product_sync.md",
                      nudge_subject="Notes?", nudge_minutes_after=5),
        MeetingConfig(calendar_pattern="dev", memory_file="data/meeting_memory/dev_triage.md",
                      nudge_subject="Notes?", nudge_minutes_after=5),
    ]
    event = make_event("Weekly Product Sync")
    match = find_meeting_for_event(event, configs)
    assert match is not None
    assert match.memory_file == "data/meeting_memory/product_sync.md"


def test_find_meeting_for_event_no_match():
    configs = [MeetingConfig(calendar_pattern="product", memory_file="p.md",
                             nudge_subject="n", nudge_minutes_after=5)]
    event = make_event("Demo: Apex Fitness")
    match = find_meeting_for_event(event, configs)
    assert match is None


def test_append_session_notes_creates_entry(tmp_path):
    memory_file = str(tmp_path / "meeting.md")
    with open(memory_file, "w") as f:
        f.write("# Test Meeting\n\n## Session Log\n\n")
    append_session_notes(memory_file, "2026-04-21", "Discussed roadmap. Action: share feedback by Friday.")
    with open(memory_file) as f:
        content = f.read()
    assert "2026-04-21" in content
    assert "Discussed roadmap" in content


def test_load_last_session_summary_returns_most_recent(tmp_path):
    memory_file = str(tmp_path / "meeting.md")
    content = "# Test\n\n## Session Log\n\n### 2026-04-14\nOld session.\n\n### 2026-04-21\nLatest session.\n"
    with open(memory_file, "w") as f:
        f.write(content)
    summary = load_last_session_summary(memory_file)
    assert "Latest session" in summary
    assert "Old session" not in summary
