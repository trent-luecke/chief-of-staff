# tests/test_meeting_memory.py
from datetime import datetime
import pytest
from lib.storage import LocalStorage
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
    storage = LocalStorage(str(tmp_path))
    key = "meeting.md"
    storage.write(key, "# Test Meeting\n\n## Session Log\n\n")
    append_session_notes(storage, key, "2026-04-21", "Discussed roadmap. Action: share feedback by Friday.")
    content = storage.read(key)
    assert "2026-04-21" in content
    assert "Discussed roadmap" in content


def test_load_last_session_summary_returns_most_recent(tmp_path):
    storage = LocalStorage(str(tmp_path))
    key = "meeting.md"
    content = "# Test\n\n## Session Log\n\n### 2026-04-14\nOld session.\n\n### 2026-04-21\nLatest session.\n"
    storage.write(key, content)
    summary = load_last_session_summary(storage, key)
    assert "Latest session" in summary
    assert "Old session" not in summary


def test_append_session_notes_creates_file_if_missing(tmp_path):
    storage = LocalStorage(str(tmp_path))
    key = "new_meeting.md"
    append_session_notes(storage, key, "2026-04-21", "First session notes.")
    content = storage.read(key)
    assert "2026-04-21" in content
    assert "First session notes" in content


def test_load_last_session_summary_single_session(tmp_path):
    storage = LocalStorage(str(tmp_path))
    key = "meeting.md"
    content = "# Test\n\n## Session Log\n\n### 2026-04-21\nOnly session.\n"
    storage.write(key, content)
    summary = load_last_session_summary(storage, key)
    assert "Only session" in summary
