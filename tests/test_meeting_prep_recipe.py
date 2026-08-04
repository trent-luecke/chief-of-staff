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
