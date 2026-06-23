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


def test_replay_update_session_changes_body():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "original"},
        {"event": "update_session", "id": "x", "ts": "2026-06-02T09:00:00",
         "session_id": "s-1", "body": "edited"},
    ])
    sess = m.replay_meetings_content(c)["x"]["sessions"][0]
    assert sess["body"] == "edited"
    assert sess["date"] == "2026-06-01"   # date unchanged
    assert sess["edited_ts"] == "2026-06-02T09:00:00"


def test_replay_delete_session_removes_it():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "gone soon"},
        {"event": "delete_session", "id": "x", "ts": "2026-06-02T09:00:00", "session_id": "s-1"},
    ])
    assert m.replay_meetings_content(c)["x"]["sessions"] == []


def test_replay_update_unknown_session_is_noop():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "kept"},
        {"event": "update_session", "id": "x", "ts": "2026-06-02T09:00:00",
         "session_id": "s-nope", "body": "ignored"},
        {"event": "delete_session", "id": "x", "ts": "2026-06-02T09:01:00", "session_id": "s-nope"},
    ])
    sessions = m.replay_meetings_content(c)["x"]["sessions"]
    assert [s["session_id"] for s in sessions] == ["s-1"]
    assert sessions[0]["body"] == "kept"


def test_append_update_and_delete_session_writers():
    store = _FakeStore()
    m.append_create(store, "x")
    add = m.append_add_session(store, "x", "2026-06-12", "first draft")
    sid = add["session_id"]
    upd = m.append_update_session(store, "x", sid, "second draft")
    assert upd["event"] == "update_session"
    assert upd["session_id"] == sid
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["sessions"][0]["body"] == "second draft"
    dele = m.append_delete_session(store, "x", sid)
    assert dele["event"] == "delete_session"
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["sessions"] == []


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


def test_replay_local_and_append_session_local(tmp_path):
    d = str(tmp_path)
    # empty / missing file → empty replay
    assert m.replay_local(d) == {}
    # seed a meeting via the storage-based writers, then read via replay_local
    from lib.storage import LocalStorage
    store = LocalStorage(d)
    m.append_create(store, "luke_1on1")
    # append a session via the local helper
    ev = m.append_session_local(d, "luke_1on1", "2026-06-12", "session via local helper")
    assert ev["event"] == "add_session"
    state = m.replay_local(d)
    assert state["luke_1on1"]["sessions"][0]["body"] == "session via local helper"


from datetime import date


def _mtg(slug, threads):
    return {"id": slug, "agenda": [], "threads": threads, "sessions": []}


def _thread(tid, text, person_id=None, closed=False, created_ts="2026-06-01T10:00:00"):
    return {"thread_id": tid, "text": text, "person_id": person_id,
            "task_id": None, "closed": closed, "closed_date": None, "created_ts": created_ts}


def test_open_loops_empty():
    out = m.open_loops_buckets({}, {}, set(), {}, date(2026, 6, 23))
    assert out == {"today": [], "other": [], "other_more": 0}


def test_open_loops_today_vs_other_and_closed_excluded():
    state = {
        "rev_dept_heads": _mtg("rev_dept_heads", [
            _thread("th-1", "quota model", person_id="quinn-kastle"),
            _thread("th-2", "done thing", closed=True),
        ]),
        "luke_1on1": _mtg("luke_1on1", [_thread("th-3", "loop luke in")]),
    }
    names = {"rev_dept_heads": "Rev Dept Heads", "luke_1on1": "Luke 1:1"}
    persons = {"quinn-kastle": "Quinn Kastle"}
    out = m.open_loops_buckets(state, names, {"rev_dept_heads"}, persons, date(2026, 6, 23))
    assert out["today"] == [
        {"meeting_name": "Rev Dept Heads",
         "loops": [{"text": "quota model", "owner": "Quinn Kastle", "age_days": 22}]}
    ]
    assert out["other"] == [
        {"meeting_name": "Luke 1:1",
         "loops": [{"text": "loop luke in", "owner": None, "age_days": 22}]}
    ]
    assert out["other_more"] == 0


def test_open_loops_owner_unresolved_passthrough():
    state = {"x": _mtg("x", [_thread("th-1", "t", person_id="ghost-id")])}
    out = m.open_loops_buckets(state, {"x": "X Meeting"}, set(), {}, date(2026, 6, 23))
    assert out["other"][0]["loops"][0]["owner"] == "ghost-id"


def test_open_loops_slug_name_fallback():
    state = {"os_sit_down": _mtg("os_sit_down", [_thread("th-1", "t")])}
    out = m.open_loops_buckets(state, {}, set(), {}, date(2026, 6, 23))
    assert out["other"][0]["meeting_name"] == "Os Sit Down"


def test_open_loops_age_today():
    state = {"x": _mtg("x", [_thread("th-1", "t", created_ts="2026-06-23T08:00:00")])}
    out = m.open_loops_buckets(state, {"x": "X"}, set(), {}, date(2026, 6, 23))
    assert out["other"][0]["loops"][0]["age_days"] == 0


def test_open_loops_other_cap_keeps_recent_displays_oldest_first():
    threads = [_thread(f"th-{i}", f"loop {i}", created_ts=f"2026-06-{i + 1:02d}T10:00:00")
               for i in range(13)]
    state = {"x": _mtg("x", threads)}
    out = m.open_loops_buckets(state, {"x": "X"}, set(), {}, date(2026, 7, 1), other_cap=10)
    kept = out["other"][0]["loops"]
    assert len(kept) == 10
    assert out["other_more"] == 3
    # cap drops the 3 oldest by creation (loop 0,1,2); display is oldest-first within the kept set
    assert kept[0]["text"] == "loop 3"
    assert kept[-1]["text"] == "loop 12"
