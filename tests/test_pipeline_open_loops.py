import json
from processors.meeting_memory import MeetingConfig
from pipeline import build_open_loops


def test_build_open_loops_reads_local_stores(tmp_path):
    (tmp_path / "meetings.jsonl").write_text("\n".join([
        json.dumps({"event": "create_meeting", "id": "luke_1on1", "ts": "2026-06-01T10:00:00"}),
        json.dumps({"event": "add_thread", "id": "luke_1on1", "ts": "2026-06-01T11:00:00",
                    "thread_id": "th-1", "text": "loop luke", "person_id": "luke-green"}),
    ]) + "\n")
    (tmp_path / "people_registry.json").write_text(json.dumps(
        {"version": 1, "people": [{"id": "luke-green", "canonical_name": "Luke Green"}]}))
    configs = [MeetingConfig(calendar_pattern="luke 1:1",
                             memory_file="data/luke_1on1.md", name="Luke 1:1",
                             nudge_subject="", nudge_minutes_after=0)]

    # no calendar events today -> the loop falls to OTHER
    out = build_open_loops([], configs, data_dir=str(tmp_path))

    assert out["today"] == []
    assert out["other"] == [
        {"meeting_name": "Luke 1:1",
         "loops": [{"text": "loop luke", "owner": "Luke Green",
                    "age_days": out["other"][0]["loops"][0]["age_days"]}]}
    ]
    assert out["other"][0]["loops"][0]["age_days"] >= 0
