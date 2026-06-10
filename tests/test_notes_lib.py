# tests/test_notes_lib.py
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
import pytest
from lib.notes import replay_notes, load_notes_for_brief, _format_note_line


# ── replay_notes ─────────────────────────────────────────────────────────────

def _write_jsonl(tmp_path, events):
    p = tmp_path / "notes.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return p


def test_replay_empty_file(tmp_path):
    p = tmp_path / "notes.jsonl"
    p.write_text("")
    assert replay_notes(p) == []


def test_replay_missing_file(tmp_path):
    assert replay_notes(tmp_path / "notes.jsonl") == []


def test_replay_create_event(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "hello", "tags": ["SALES"], "person_id": None, "task_id": None,
         "brief": False, "pinned": False}
    ])
    notes = replay_notes(p)
    assert len(notes) == 1
    assert notes[0]["body"] == "hello"
    assert notes[0]["brief_flagged_date"] is None


def test_replay_create_with_brief(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": True, "pinned": False}
    ])
    notes = replay_notes(p)
    assert notes[0]["brief_flagged_date"] == "2026-06-09"


def test_replay_update_sets_brief_flagged_date(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-01T10:00:00",
         "body": "old", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False},
        {"event": "update", "id": "n-aaa111", "ts": "2026-06-15T08:00:00",
         "brief": True},
    ])
    notes = replay_notes(p)
    assert notes[0]["brief_flagged_date"] == "2026-06-15"
    assert notes[0]["brief"] is True


def test_replay_delete_tombstone(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False},
        {"event": "delete", "id": "n-aaa111", "ts": "2026-06-09T11:00:00"},
    ])
    assert replay_notes(p) == []


def test_replay_pin_event(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False},
        {"event": "pin", "id": "n-aaa111", "ts": "2026-06-09T11:00:00", "pinned": True},
    ])
    notes = replay_notes(p)
    assert notes[0]["pinned"] is True


def test_replay_update_partial_patch(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "original", "tags": ["SALES"], "person_id": None, "task_id": None,
         "brief": False, "pinned": False},
        {"event": "update", "id": "n-aaa111", "ts": "2026-06-09T11:00:00",
         "tags": ["SALES", "ACTION"]},
    ])
    notes = replay_notes(p)
    assert notes[0]["body"] == "original"
    assert notes[0]["tags"] == ["SALES", "ACTION"]


# ── load_notes_for_brief ──────────────────────────────────────────────────────

class _FakeStorage:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)


def test_brief_loader_no_file(tmp_path):
    assert load_notes_for_brief(_FakeStorage(tmp_path)) == ""


def test_brief_loader_buckets_by_flagged_date(tmp_path):
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    two_days_ago = (today - timedelta(days=2)).isoformat()

    events = [
        {"event": "create", "id": "n-111111", "ts": f"{yesterday}T09:00:00",
         "body": "note for today bucket", "tags": ["SALES"],
         "person_id": None, "task_id": None, "brief": True, "pinned": False},
        {"event": "create", "id": "n-222222", "ts": f"{two_days_ago}T09:00:00",
         "body": "note for yesterday bucket", "tags": [],
         "person_id": None, "task_id": None, "brief": True, "pinned": False},
        {"event": "create", "id": "n-333333", "ts": "2026-01-01T09:00:00",
         "body": "old note not in brief", "tags": [],
         "person_id": None, "task_id": None, "brief": True, "pinned": False},
    ]
    (tmp_path / "notes.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")

    result = load_notes_for_brief(_FakeStorage(tmp_path))
    assert "Today's Notes" in result
    assert "note for today bucket" in result
    assert "Yesterday's Notes" in result
    assert "note for yesterday bucket" in result
    assert "old note not in brief" not in result


def test_brief_loader_empty_when_no_flagged_notes(tmp_path):
    events = [
        {"event": "create", "id": "n-111111", "ts": "2026-06-09T09:00:00",
         "body": "unflagged", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False},
    ]
    (tmp_path / "notes.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    assert load_notes_for_brief(_FakeStorage(tmp_path)) == ""
