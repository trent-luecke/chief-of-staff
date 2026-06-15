# tests/test_meeting_config.py
import json
from processors.meeting_memory import MeetingConfig, load_meeting_index


def test_meeting_config_defaults_and_id():
    cfg = MeetingConfig(
        calendar_pattern="luke / trent",
        memory_file="data/meeting_memory/luke_1on1.md",
        nudge_subject="1:1 notes?",
        nudge_minutes_after=5,
    )
    assert cfg.name == ""
    assert cfg.people_ids == []
    assert cfg.meeting_id == "luke_1on1"


def test_meeting_config_with_new_fields():
    cfg = MeetingConfig(
        calendar_pattern="department heads",
        memory_file="data/meeting_memory/rev_dept_heads.md",
        nudge_subject="Dept heads notes?",
        nudge_minutes_after=5,
        name="Revenue Dept Heads",
        people_ids=["luke-green", "james-peters"],
    )
    assert cfg.name == "Revenue Dept Heads"
    assert cfg.people_ids == ["luke-green", "james-peters"]
    assert cfg.meeting_id == "rev_dept_heads"


def test_load_meeting_index_tolerates_new_fields(tmp_path):
    p = tmp_path / "meeting_index.json"
    p.write_text(json.dumps({"meetings": [
        {"calendar_pattern": "x", "memory_file": "data/meeting_memory/x.md",
         "nudge_subject": "x?", "nudge_minutes_after": 5,
         "name": "X Meeting", "people_ids": ["a"]},
    ]}))
    cfgs = load_meeting_index(str(p))
    assert cfgs[0].name == "X Meeting"
    assert cfgs[0].meeting_id == "x"
