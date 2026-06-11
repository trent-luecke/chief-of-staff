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


def test_replay_update_clears_brief_flagged_date(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-01T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": True, "pinned": False},
        {"event": "update", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "brief": False},
    ])
    notes = replay_notes(p)
    assert notes[0]["brief"] is False
    assert notes[0]["brief_flagged_date"] is None


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


# ── project_id replay ─────────────────────────────────────────────────────────

def test_replay_create_carries_project_id(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "project_id": "proj-acme", "brief": False, "pinned": False}
    ])
    notes = replay_notes(p)
    assert notes[0]["project_id"] == "proj-acme"


def test_replay_create_defaults_project_id_none(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-09T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False}
    ])
    notes = replay_notes(p)
    assert notes[0]["project_id"] is None


def test_replay_update_sets_project_id(tmp_path):
    p = _write_jsonl(tmp_path, [
        {"event": "create", "id": "n-aaa111", "ts": "2026-06-01T10:00:00",
         "body": "x", "tags": [], "person_id": None, "task_id": None,
         "brief": False, "pinned": False},
        {"event": "update", "id": "n-aaa111", "ts": "2026-06-02T10:00:00",
         "project_id": "proj-acme"},
    ])
    notes = replay_notes(p)
    assert notes[0]["project_id"] == "proj-acme"


# ── add_note ──────────────────────────────────────────────────────────────────

class _CapturingStorage:
    """Minimal storage stub capturing append_line writes into an in-memory file."""
    def __init__(self):
        self._lines = []
    def append_line(self, key, line):
        self._lines.append(line)
    def content(self):
        return "\n".join(self._lines) + "\n"


def test_add_note_appends_create_event_with_links():
    from lib.notes import add_note, replay_notes_content
    store = _CapturingStorage()
    out = add_note(store, body="call Acme", tags=["SALES"],
                   person_id="jane", project_id="proj-acme", task_id=None)
    assert out["body"] == "call Acme"
    assert out["project_id"] == "proj-acme"
    assert out["person_id"] == "jane"
    assert out["id"].startswith("n-")
    replayed = replay_notes_content(store.content())
    assert len(replayed) == 1
    assert replayed[0]["tags"] == ["SALES"]
    assert replayed[0]["project_id"] == "proj-acme"
    assert replayed[0]["brief"] is False


# ── project name in brief line ────────────────────────────────────────────────

def test_format_note_line_includes_project_name():
    line = _format_note_line(
        {"body": "ship it", "tags": [], "person_id": None,
         "project_id": "proj-acme", "task_id": None},
        people_by_id={},
        projects_by_id={"proj-acme": "Acme Onboarding"},
    )
    assert "Acme Onboarding" in line
