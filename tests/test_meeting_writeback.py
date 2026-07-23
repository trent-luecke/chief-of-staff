import json
from unittest.mock import patch, MagicMock

from scripts import meeting_writeback


def _resp(payload, status=201):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = payload
    m.raise_for_status = MagicMock()
    return m


def test_oneoff_writes_note_tasks_and_decisions():
    payload = {
        "meeting": {"kind": "oneoff", "name": "Impromptu Sync",
                    "people_ids": [], "date": "2026-07-23"},
        "summary": "Talked pricing.",
        "commitments": [{"text": "Send recap", "owner": "trent-luecke"}],
        "owed_to_me": [{"text": "Rachel confirms budget", "owner": "rachel-y"}],
        "team_tasks": [{"text": "Nicole drafts brief", "owner": "nicole-x"}],
        "decisions": ["Hold pricing flat for Q3"],
    }
    with patch("scripts.meeting_writeback.requests.post") as post:
        post.side_effect = [
            _resp({"note": {"id": "n-1"}}),        # POST /api/notes
            _resp({"task": {"id": "t-1"}}),        # commitment task
            _resp({"task": {"id": "t-2"}}),        # owed_to_me task
            _resp({"task": {"id": "t-3"}}),        # team task
            _resp({"decision": "2026-07-23: Hold pricing flat for Q3"}),  # decision
        ]
        summary = meeting_writeback.write_back(payload, base_url="http://x")

    urls = [c.args[0] for c in post.call_args_list]
    assert urls == [
        "http://x/api/notes",
        "http://x/api/tasks",
        "http://x/api/tasks",
        "http://x/api/tasks",
        "http://x/api/decisions",
    ]
    # note tagged MEETING_NOTES
    assert post.call_args_list[0].kwargs["json"]["tags"] == ["MEETING_NOTES"]
    # every task carries its owner
    assert post.call_args_list[1].kwargs["json"]["owner"] == "trent-luecke"
    assert post.call_args_list[2].kwargs["json"]["owner"] == "rachel-y"
    assert post.call_args_list[3].kwargs["json"]["owner"] == "nicole-x"
    assert len(summary["created"]) == 5
    assert summary["errors"] == []


def test_recurring_creates_session_threads_and_promotes_commitment():
    payload = {
        "meeting": {"kind": "recurring", "meeting_id": "marketing_sync",
                    "name": "Marketing Sync", "people_ids": ["nicole-x"],
                    "date": "2026-07-23"},
        "summary": "Weekly marketing sync.",
        "commitments": [{"text": "Send deck", "owner": "trent-luecke"}],
        "owed_to_me": [{"text": "Rachel budget", "owner": "rachel-y"}],
        "team_tasks": [],
        "decisions": [],
    }
    with patch("scripts.meeting_writeback.requests.post") as post:
        post.side_effect = [
            _resp({"meeting": {"id": "marketing_sync"}}),               # add session
            _resp({"meeting": {"threads": [{"thread_id": "th-1"}]}}),   # commitment thread
            _resp({"task": {"id": "t-9"}}),                             # promote commitment
            _resp({"meeting": {"threads": [{"thread_id": "th-2"}]}}),   # owed_to_me thread
        ]
        summary = meeting_writeback.write_back(payload, base_url="http://x")

    urls = [c.args[0] for c in post.call_args_list]
    assert urls == [
        "http://x/api/meetings/marketing_sync/sessions",
        "http://x/api/meetings/marketing_sync/threads",
        "http://x/api/meetings/marketing_sync/threads/th-1/promote",
        "http://x/api/meetings/marketing_sync/threads",
    ]
    # commitment thread carries person_id = owner
    assert post.call_args_list[1].kwargs["json"]["person_id"] == "trent-luecke"
    assert summary["errors"] == []


def test_recurring_creates_series_when_meeting_id_absent():
    payload = {
        "meeting": {"kind": "recurring", "meeting_id": "", "name": "New Sync",
                    "people_ids": ["nicole-x"], "date": "2026-07-23"},
        "summary": "First occurrence.",
        "commitments": [], "owed_to_me": [], "team_tasks": [], "decisions": [],
    }
    with patch("scripts.meeting_writeback.requests.post") as post:
        post.side_effect = [
            _resp({"id": "new_sync"}),                    # create meeting
            _resp({"meeting": {"id": "new_sync"}}),       # add session
        ]
        summary = meeting_writeback.write_back(payload, base_url="http://x")

    urls = [c.args[0] for c in post.call_args_list]
    assert urls[0] == "http://x/api/meetings"
    assert urls[1] == "http://x/api/meetings/new_sync/sessions"
    assert summary["errors"] == []
