# tests/test_notes_replay.py
from pathlib import Path
from lib.notes import replay_notes, replay_notes_content


def test_replay_notes_content_create_and_update():
    content = (
        '{"event":"create","id":"n-1","ts":"2026-06-10T10:00:00","body":"first","tags":["X"]}\n'
        '{"event":"update","id":"n-1","ts":"2026-06-10T11:00:00","body":"edited"}\n'
    )
    notes = replay_notes_content(content)
    assert len(notes) == 1
    assert notes[0]["body"] == "edited"
    assert notes[0]["tags"] == ["X"]


def test_replay_notes_content_delete():
    content = (
        '{"event":"create","id":"n-1","ts":"2026-06-10T10:00:00","body":"x"}\n'
        '{"event":"delete","id":"n-1","ts":"2026-06-10T11:00:00"}\n'
    )
    assert replay_notes_content(content) == []


def test_replay_notes_content_empty():
    assert replay_notes_content("") == []


def test_replay_notes_path_delegates(tmp_path):
    p = Path(tmp_path) / "notes.jsonl"
    p.write_text('{"event":"create","id":"n-1","ts":"2026-06-10T10:00:00","body":"hi"}\n')
    assert replay_notes(p) == replay_notes_content(p.read_text())
