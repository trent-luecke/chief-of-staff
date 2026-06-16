# tests/test_meeting_prep_integration.py
import json
from pathlib import Path
import lib.meetings as m


class _DirStore:
    """LocalStorage-like store over a tmp data dir (read/append_line only)."""
    def __init__(self, base): self.base = Path(base)
    def read(self, key):
        p = self.base / key
        return p.read_text() if p.exists() else None
    def append_line(self, key, line):
        p = self.base / key
        existing = p.read_text() if p.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        p.write_text(existing + line + "\n")


def test_last_session_from_store(tmp_path):
    store = _DirStore(tmp_path)
    m.append_create(store, "luke_1on1")
    m.append_add_session(store, "luke_1on1", "2026-06-08", "discussed roadmap")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert m.last_session(state["luke_1on1"]) == "discussed roadmap"


def test_render_for_prep_from_store(tmp_path):
    store = _DirStore(tmp_path)
    m.append_create(store, "luke_1on1")
    m.append_add_thread(store, "luke_1on1", "chase hire backfill", person_id="luke-green")
    m.append_add_session(store, "luke_1on1", "2026-06-08", "talked shop")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    out = m.render_for_prep(state["luke_1on1"])
    assert "chase hire backfill" in out
    assert "talked shop" in out
