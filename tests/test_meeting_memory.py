# tests/test_meeting_memory.py
from datetime import datetime
from unittest.mock import patch, MagicMock
import json
import pytest
from lib.storage import LocalStorage
from processors.meeting_memory import (
    load_meeting_index, find_meeting_for_event, append_session_notes,
    load_last_session_summary, rewrite_meeting_memory, MeetingConfig,
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


def _mock_claude_response(text: str):
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=text)]
    )
    return mock_client


_WELL_FORMED_DOC = """\
# Marketing Sync

## Current State
Good progress on the roadmap. The team is aligned on Q2 priorities.

## Open Threads
- Follow up on budget approval

## Session Log

### 2026-04-21
Discussed Q2 roadmap. Action: share feedback by Friday."""


@patch("processors.meeting_memory.anthropic.Anthropic")
def test_rewrite_meeting_memory_creates_file_if_missing(mock_cls, tmp_path):
    mock_cls.return_value = _mock_claude_response(_WELL_FORMED_DOC)
    storage = LocalStorage(str(tmp_path))
    rewrite_meeting_memory(storage, "meeting_memory/marketing_sync.md", "2026-04-21", "Discussed Q2 roadmap.", api_key="test")
    content = storage.read("meeting_memory/marketing_sync.md")
    assert "Current State" in content
    assert "Open Threads" in content
    assert "Session Log" in content


@patch("processors.meeting_memory.anthropic.Anthropic")
def test_rewrite_meeting_memory_preserves_recent_sessions(mock_cls, tmp_path):
    recent_doc = _WELL_FORMED_DOC + "\n\n### 2026-04-14\nPrevious session from 15 days ago."
    mock_cls.return_value = _mock_claude_response(recent_doc)
    storage = LocalStorage(str(tmp_path))
    storage.write("meeting_memory/marketing_sync.md", "# Marketing Sync\n\n## Session Log\n\n### 2026-04-14\nPrevious session.\n")
    rewrite_meeting_memory(storage, "meeting_memory/marketing_sync.md", "2026-04-21", "New notes.", api_key="test")
    content = storage.read("meeting_memory/marketing_sync.md")
    assert "2026-04-14" in content


@patch("processors.meeting_memory.anthropic.Anthropic")
def test_rewrite_meeting_memory_drops_old_sessions(mock_cls, tmp_path):
    # Claude returns a doc without the old session (as instructed by the prompt)
    mock_cls.return_value = _mock_claude_response(_WELL_FORMED_DOC)
    storage = LocalStorage(str(tmp_path))
    storage.write(
        "meeting_memory/marketing_sync.md",
        "# Marketing Sync\n\n## Session Log\n\n### 2026-03-01\nSession from 51 days ago.\n",
    )
    rewrite_meeting_memory(storage, "meeting_memory/marketing_sync.md", "2026-04-21", "New notes.", api_key="test")
    content = storage.read("meeting_memory/marketing_sync.md")
    assert "2026-03-01" not in content


def test_load_meeting_index_parses_prep_recipe(tmp_path):
    from processors.meeting_memory import load_meeting_index
    p = tmp_path / "meeting_index.json"
    p.write_text(json.dumps({"meetings": [{
        "calendar_pattern": "luke / trent",
        "memory_file": "data/meeting_memory/luke_1on1.md",
        "nudge_subject": "1:1 notes?",
        "nudge_minutes_after": 5,
        "name": "Luke 1:1",
        "prep_recipe": {"blocks": ["open_threads"], "instruction": "Keep it short."},
    }]}))
    configs = load_meeting_index(str(p))
    assert len(configs) == 1
    assert configs[0].prep_recipe == {"blocks": ["open_threads"], "instruction": "Keep it short."}


def test_load_meeting_index_recipe_defaults_none(tmp_path):
    from processors.meeting_memory import load_meeting_index
    p = tmp_path / "meeting_index.json"
    p.write_text(json.dumps({"meetings": [{
        "calendar_pattern": "dev sync",
        "memory_file": "data/meeting_memory/dev_triage.md",
        "nudge_subject": "notes?",
        "nudge_minutes_after": 5,
        "name": "Dev Sync",
    }]}))
    configs = load_meeting_index(str(p))
    assert configs[0].prep_recipe is None
