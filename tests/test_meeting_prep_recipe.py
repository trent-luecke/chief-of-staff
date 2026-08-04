import json
from dataclasses import dataclass
from types import SimpleNamespace

import processors.meeting_prep_recipe as mpr
from processors.meeting_memory import MeetingConfig


class FakeStorage:
    """Minimal storage: dict-backed read/read_json."""
    def __init__(self, files=None, json_files=None):
        self._files = files or {}
        self._json = json_files or {}

    def read(self, key, default=None):
        return self._files.get(key, default)

    def read_json(self, key, default=None):
        return self._json.get(key, default if default is not None else {})

    def write_json(self, key, value):
        self._json[key] = value


def _event(summary="Luke / Trent", attendees=None):
    details = attendees or []
    return SimpleNamespace(
        id="evt1",
        summary=summary,
        attendees=[d["email"] for d in details],
        attendee_details=details,
        declined=False,
    )


def _cfg(**over):
    base = dict(
        calendar_pattern="luke / trent",
        memory_file="data/meeting_memory/luke_1on1.md",
        nudge_subject="1:1?",
        nudge_minutes_after=5,
        name="Luke 1:1",
    )
    base.update(over)
    return MeetingConfig(**base)


def test_gather_open_threads_renders_open_only(monkeypatch):
    meeting_state = {"luke_1on1": {
        "id": "luke_1on1",
        "threads": [
            {"text": "Ship onboarding v2", "person_id": "luke-green", "closed": False},
            {"text": "Old resolved thing", "person_id": None, "closed": True},
        ],
        "sessions": [],
    }}
    monkeypatch.setattr(mpr.meetings_lib, "replay_local", lambda data_dir: meeting_state)
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={"data_dir": "data"}, storage=FakeStorage())
    out = mpr.gather_open_threads(ctx, {})
    assert "Open Threads" in out
    assert "Ship onboarding v2" in out
    assert "Old resolved thing" not in out


def test_gather_open_threads_none_when_no_meeting(monkeypatch):
    monkeypatch.setattr(mpr.meetings_lib, "replay_local", lambda data_dir: {})
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=FakeStorage())
    assert mpr.gather_open_threads(ctx, {}) is None


def test_gather_last_session_reads_md_summary():
    storage = FakeStorage(files={
        "meeting_memory/luke_1on1.md": "# Luke 1:1\n\n## Session Log\n\n### 2026-07-28\nTalked roadmap.\n"
    })
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=storage)
    out = mpr.gather_last_session(ctx, {})
    assert "Last Session" in out
    assert "Talked roadmap." in out


def test_gather_last_session_none_when_absent():
    ctx = mpr.PrepContext(event=_event(), meeting_cfg=_cfg(), config={}, storage=FakeStorage())
    assert mpr.gather_last_session(ctx, {}) is None


def _projects(*projs):
    return {"version": 1, "projects": list(projs)}


def test_project_next_actions_selects_by_attendee_membership():
    people = [{"id": "luke-green", "email": "luke@teambuildr.com", "canonical_name": "Luke Green", "aliases": []}]
    projects = _projects(
        {"id": "p-onb", "canonical_name": "Onboarding", "status": "active",
         "members": [{"id": "luke-green", "role": "contact"}]},
        {"id": "p-other", "canonical_name": "Unrelated", "status": "active",
         "members": [{"id": "someone-else", "role": "owner"}]},
    )
    storage = FakeStorage(json_files={
        "people_registry.json": {"version": 1, "people": people},
        "projects_registry.json": projects,
    })
    tasks = [
        {"id": "t1", "title": "Draft flow", "status": "open", "project_id": "p-onb", "due_date": "2026-08-10", "horizon": None},
    ]
    import processors.meeting_prep_recipe as m
    m_get = m.tasks_lib.get_open_tasks
    try:
        m.tasks_lib.get_open_tasks = lambda s: tasks
        ctx = m.PrepContext(
            event=_event(attendees=[{"email": "luke@teambuildr.com", "name": "Luke Green"}]),
            meeting_cfg=_cfg(),
            config={"demo_scan": {"internal_domains": ["teambuildr.com"]}},
            storage=storage,
        )
        out = m.gather_project_next_actions(ctx, {})
    finally:
        m.tasks_lib.get_open_tasks = m_get
    assert "Onboarding" in out
    assert "Draft flow" in out
    assert "Unrelated" not in out


def test_project_next_actions_none_when_no_membership():
    storage = FakeStorage(json_files={
        "people_registry.json": {"version": 1, "people": []},
        "projects_registry.json": _projects(
            {"id": "p1", "canonical_name": "X", "status": "active", "members": []}),
    })
    import processors.meeting_prep_recipe as m
    ctx = m.PrepContext(
        event=_event(attendees=[{"email": "ext@other.com", "name": "Ext"}]),
        meeting_cfg=_cfg(),
        config={"demo_scan": {"internal_domains": ["teambuildr.com"]}},
        storage=storage,
    )
    assert m.gather_project_next_actions(ctx, {}) is None


def test_select_project_tasks_shows_all_at_or_below_threshold():
    import processors.meeting_prep_recipe as m
    tasks = [{"id": f"t{i}", "title": f"T{i}", "status": "open", "project_id": "p", "due_date": f"2026-08-0{i}", "horizon": None} for i in range(1, 6)]
    sel = m._select_project_tasks(tasks, "p", expand_threshold=5, max_per_project=3)
    assert len(sel) == 5


def test_select_project_tasks_caps_and_sorts_by_nearest_when_over_threshold():
    import processors.meeting_prep_recipe as m
    tasks = [
        {"id": "t1", "title": "far", "status": "open", "project_id": "p", "due_date": "2026-12-01", "horizon": None},
        {"id": "t2", "title": "near", "status": "open", "project_id": "p", "due_date": "2026-08-05", "horizon": None},
        {"id": "t3", "title": "mid", "status": "open", "project_id": "p", "due_date": "2026-09-01", "horizon": None},
        {"id": "t4", "title": "horizon-only", "status": "open", "project_id": "p", "due_date": None, "horizon": "2026-08-07"},
        {"id": "t5", "title": "none", "status": "open", "project_id": "p", "due_date": None, "horizon": None},
        {"id": "t6", "title": "nearest", "status": "open", "project_id": "p", "due_date": "2026-08-01", "horizon": None},
    ]
    sel = m._select_project_tasks(tasks, "p", expand_threshold=5, max_per_project=3)
    assert [t["title"] for t in sel] == ["nearest", "near", "horizon-only"]
