# tests/test_meetings_lib.py
import json
import lib.meetings as m


def _content(events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_replay_empty():
    assert m.replay_meetings_content("") == {}


def test_replay_create_only():
    c = _content([{"event": "create_meeting", "id": "luke_1on1", "ts": "2026-06-01T10:00:00"}])
    state = m.replay_meetings_content(c)
    assert set(state.keys()) == {"luke_1on1"}
    mtg = state["luke_1on1"]
    assert mtg["agenda"] == []
    assert mtg["threads"] == []
    assert mtg["sessions"] == []


def test_replay_set_agenda_replaces():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "set_agenda", "id": "x", "ts": "2026-06-01T11:00:00", "items": ["a", "b"]},
        {"event": "set_agenda", "id": "x", "ts": "2026-06-01T12:00:00", "items": ["c"]},
    ])
    assert m.replay_meetings_content(c)["x"]["agenda"] == ["c"]


def test_replay_thread_lifecycle():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_thread", "id": "x", "ts": "2026-06-01T11:00:00",
         "thread_id": "th-1", "text": "follow up", "person_id": "luke-green"},
        {"event": "update_thread", "id": "x", "ts": "2026-06-01T12:00:00",
         "thread_id": "th-1", "task_id": "t-abc123"},
        {"event": "update_thread", "id": "x", "ts": "2026-06-02T09:00:00",
         "thread_id": "th-1", "closed": True, "closed_date": "2026-06-02"},
    ])
    th = m.replay_meetings_content(c)["x"]["threads"][0]
    assert th["thread_id"] == "th-1"
    assert th["text"] == "follow up"
    assert th["person_id"] == "luke-green"
    assert th["task_id"] == "t-abc123"
    assert th["closed"] is True
    assert th["closed_date"] == "2026-06-02"


def test_replay_delete_thread():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_thread", "id": "x", "ts": "2026-06-01T11:00:00",
         "thread_id": "th-1", "text": "t", "person_id": None},
        {"event": "delete_thread", "id": "x", "ts": "2026-06-01T12:00:00", "thread_id": "th-1"},
    ])
    assert m.replay_meetings_content(c)["x"]["threads"] == []


def test_replay_sessions_newest_first():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "first"},
        {"event": "add_session", "id": "x", "ts": "2026-06-08T10:01:00",
         "session_id": "s-2", "date": "2026-06-08", "body": "second"},
    ])
    sessions = m.replay_meetings_content(c)["x"]["sessions"]
    assert [s["session_id"] for s in sessions] == ["s-2", "s-1"]


def test_open_threads_excludes_closed():
    mtg = {"threads": [
        {"thread_id": "a", "closed": False, "closed_date": None, "text": "open", "person_id": None, "task_id": None},
        {"thread_id": "b", "closed": True, "closed_date": "2026-06-02", "text": "done", "person_id": None, "task_id": None},
    ]}
    assert [t["thread_id"] for t in m.open_threads(mtg)] == ["a"]


def test_render_for_prep_includes_open_threads_and_sessions():
    mtg = {
        "id": "x",
        "agenda": ["prep item"],
        "threads": [{"thread_id": "a", "closed": False, "closed_date": None,
                     "text": "chase invoice", "person_id": None, "task_id": None}],
        "sessions": [{"session_id": "s-1", "date": "2026-06-08", "body": "talked shop", "ts": "2026-06-08T10:00:00"}],
    }
    out = m.render_for_prep(mtg)
    assert "chase invoice" in out
    assert "2026-06-08" in out
    assert "talked shop" in out


def test_last_session_returns_newest_body():
    mtg = {"sessions": [
        {"session_id": "s-2", "date": "2026-06-08", "body": "newer", "ts": "2026-06-08T10:00:00"},
        {"session_id": "s-1", "date": "2026-06-01", "body": "older", "ts": "2026-06-01T10:00:00"},
    ]}
    assert m.last_session(mtg) == "newer"


def test_last_session_empty():
    assert m.last_session({"sessions": []}) == ""


class _FakeStore:
    def __init__(self):
        self.data = {}
    def read(self, key):
        return self.data.get(key)
    def append_line(self, key, line):
        existing = self.data.get(key) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.data[key] = existing + line + "\n"


def test_append_add_session_writes_event_and_replays():
    store = _FakeStore()
    m.append_create(store, "x")
    ev = m.append_add_session(store, "x", "2026-06-12", "notes here")
    assert ev["event"] == "add_session"
    assert ev["session_id"].startswith("s-")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["sessions"][0]["body"] == "notes here"


def test_append_add_thread_generates_id():
    store = _FakeStore()
    m.append_create(store, "x")
    ev = m.append_add_thread(store, "x", "do the thing", person_id="luke-green")
    assert ev["thread_id"].startswith("th-")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["threads"][0]["text"] == "do the thing"
    assert state["x"]["threads"][0]["person_id"] == "luke-green"
