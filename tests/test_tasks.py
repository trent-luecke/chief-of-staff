import json
import pytest
from datetime import date, timedelta
from lib.storage import LocalStorage
from lib.tasks import add_task, complete_task, get_open_tasks, get_recent_completions, edit_task, is_behind_horizon, get_surfaced_tasks


def _s(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


# --- Basic create/read ---

def test_add_task_minimal(tmp_path):
    task = add_task(_s(tmp_path), "Send deck")
    assert task["title"] == "Send deck"
    assert task["status"] == "open"
    assert task["source"] == "telegram"
    assert task["project_id"] is None
    assert task["collaborators"] == []
    assert task["metadata"] == {}


def test_add_task_with_project_id(tmp_path):
    task = add_task(_s(tmp_path), "Follow up", project_id="nicole-campaign")
    assert task["project_id"] == "nicole-campaign"


def test_add_task_with_collaborators(tmp_path):
    task = add_task(_s(tmp_path), "Prep slides", collaborators=["nicole-foley"])
    assert task["collaborators"] == ["nicole-foley"]


def test_add_task_with_metadata(tmp_path):
    meta = {"avoma_uuid": "abc", "thread_ts": "ts.123"}
    task = add_task(_s(tmp_path), "Follow up", source="avoma", metadata=meta)
    assert task["metadata"] == meta
    assert task["source"] == "avoma"


def test_get_open_tasks_empty(tmp_path):
    assert get_open_tasks(_s(tmp_path)) == []


def test_get_open_tasks_returns_open(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Task A")
    add_task(s, "Task B")
    tasks = get_open_tasks(s)
    assert len(tasks) == 2
    assert all(t["status"] == "open" for t in tasks)


def test_add_task_metadata_persisted(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Check in", source="avoma", metadata={"avoma_uuid": "xyz"})
    assert get_open_tasks(s)[0]["metadata"]["avoma_uuid"] == "xyz"


# --- Complete ---

def test_complete_task(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Send deck")
    result = complete_task(s, "Send deck")
    assert result is not None
    assert result["status"] == "completed"
    assert get_open_tasks(s) == []


def test_complete_task_partial_match(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Send the deck to Acme")
    assert complete_task(s, "deck to Acme") is not None


def test_complete_task_missing(tmp_path):
    assert complete_task(_s(tmp_path), "nonexistent") is None


def test_get_recent_completions(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Done task")
    complete_task(s, "Done task")
    assert len(get_recent_completions(s, days=7)) == 1


# --- Edit ---

def test_edit_task_project_id(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Unlinked task")
    edited = edit_task(s, task["id"], {"project_id": "nicole-campaign"})
    assert edited["project_id"] == "nicole-campaign"
    assert get_open_tasks(s)[0]["project_id"] == "nicole-campaign"


def test_edit_task_collaborators(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Solo task")
    edit_task(s, task["id"], {"collaborators": ["luke-martin"]})
    assert get_open_tasks(s)[0]["collaborators"] == ["luke-martin"]


def test_edit_task_missing(tmp_path):
    assert edit_task(_s(tmp_path), "t-nope", {"project_id": "x"}) is None


# --- JSONL format on disk ---

def test_events_are_appended_as_jsonl(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Check format")
    complete_task(s, "Check format")
    lines = (tmp_path / "tasks.jsonl").read_text().strip().splitlines()
    events = [json.loads(l) for l in lines]
    assert events[0]["event"] == "create"
    assert events[1]["event"] == "complete"
    assert events[0]["task_id"] == task["id"]
    assert events[1]["task_id"] == task["id"]


def test_edit_appends_edit_event(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Edit me")
    edit_task(s, task["id"], {"project_id": "proj-x"})
    lines = (tmp_path / "tasks.jsonl").read_text().strip().splitlines()
    events = [json.loads(l) for l in lines]
    assert events[1]["event"] == "edit"
    assert events[1]["patch"]["project_id"] == "proj-x"


# --- Migration from tasks.json ---

def test_migration_from_legacy_json(tmp_path):
    import json as _json
    (tmp_path / "tasks.json").write_text(_json.dumps({"tasks": [
        {"id": "t-old", "title": "Migrated task", "status": "open",
         "created_at": "2026-01-01", "due_date": None, "source": "telegram",
         "completed_at": None, "metadata": {}}
    ]}))
    s = _s(tmp_path)
    tasks = get_open_tasks(s)
    assert tasks[0]["title"] == "Migrated task"
    assert tasks[0]["project_id"] is None
    assert tasks[0]["collaborators"] == []
    # jsonl should now exist
    assert (tmp_path / "tasks.jsonl").exists()


def test_migration_preserves_completed_status(tmp_path):
    import json as _json
    (tmp_path / "tasks.json").write_text(_json.dumps({"tasks": [
        {"id": "t-done", "title": "Completed task", "status": "completed",
         "created_at": "2026-01-01", "due_date": None, "source": "telegram",
         "completed_at": "2026-01-02", "metadata": {}}
    ]}))
    s = _s(tmp_path)
    assert get_open_tasks(s) == []
    assert len(get_recent_completions(s, days=9999)) == 1


# --- Legacy record without project fields (post-migration safety) ---

def test_legacy_record_without_project_fields(tmp_path):
    s = _s(tmp_path)
    # Simulate a create event written before project_id was added
    (tmp_path / "tasks.jsonl").write_text(
        '{"event": "create", "task_id": "t-old", "title": "Old", '
        '"source": "telegram", "created_at": "2026-01-01", '
        '"due_date": null, "metadata": {}}\n'
    )
    tasks = get_open_tasks(s)
    assert tasks[0].get("project_id") is None
    assert tasks[0].get("collaborators", []) == []


def test_edit_task_ignores_protected_fields(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Protected test")
    original_id = task["id"]
    # Patching protected fields should be silently ignored
    result = edit_task(s, task["id"], {"status": "completed", "id": "t-hacked", "project_id": "proj-x"})
    assert result["id"] == original_id
    assert result["status"] == "open"  # not changed
    assert result["project_id"] == "proj-x"  # non-protected field applied
    tasks = get_open_tasks(s)
    assert tasks[0]["id"] == original_id
    assert tasks[0]["status"] == "open"


# --- complete_task_by_id ---

def test_complete_task_by_id(tmp_path):
    from lib.tasks import complete_task_by_id
    s = _s(tmp_path)
    task = add_task(s, "Complete by ID")
    result = complete_task_by_id(s, task["id"])
    assert result is not None
    assert result["status"] == "completed"
    assert get_open_tasks(s) == []


def test_complete_task_by_id_missing(tmp_path):
    from lib.tasks import complete_task_by_id
    assert complete_task_by_id(_s(tmp_path), "t-nope") is None


def test_complete_task_by_id_already_completed(tmp_path):
    from lib.tasks import complete_task_by_id
    s = _s(tmp_path)
    task = add_task(s, "Already done")
    complete_task_by_id(s, task["id"])
    assert complete_task_by_id(s, task["id"]) is None  # idempotent — returns None for already completed


def test_add_task_default_owner_is_none(tmp_path):
    task = add_task(_s(tmp_path), "Send deck")
    assert task["owner"] is None


def test_add_task_with_owner(tmp_path):
    task = add_task(_s(tmp_path), "Draft doc", owner="nicole-foley")
    assert task["owner"] == "nicole-foley"


def test_owner_persisted_and_replayed(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Draft doc", owner="nicole-foley")
    assert get_open_tasks(s)[0]["owner"] == "nicole-foley"


def test_edit_task_owner(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Solo task")
    edit_task(s, task["id"], {"owner": "luke-martin"})
    assert get_open_tasks(s)[0]["owner"] == "luke-martin"


def test_legacy_record_without_owner_field(tmp_path):
    s = _s(tmp_path)
    (tmp_path / "tasks.jsonl").write_text(
        '{"event": "create", "task_id": "t-old", "title": "Old", '
        '"source": "telegram", "created_at": "2026-01-01", '
        '"due_date": null, "metadata": {}}\n'
    )
    assert get_open_tasks(s)[0].get("owner") is None


# --- Horizon ---

def test_add_task_with_horizon(tmp_path):
    s = _s(tmp_path)
    task = add_task(s, "Renew SSL", horizon="2099-01-01")
    assert task["horizon"] == "2099-01-01"
    assert get_open_tasks(s)[0]["horizon"] == "2099-01-01"


def test_add_task_defaults_horizon_none(tmp_path):
    assert add_task(_s(tmp_path), "Send deck")["horizon"] is None


def test_replay_tolerates_legacy_events_without_horizon(tmp_path):
    s = _s(tmp_path)
    s.append_line("tasks.jsonl", json.dumps({
        "event": "create", "task_id": "t-legacy", "title": "Old task",
        "source": "slack", "created_at": "2026-01-01", "due_date": None,
        "metadata": {}, "project_id": None, "collaborators": [],
    }))
    tasks = get_open_tasks(s)
    assert tasks[0]["horizon"] is None


def test_edit_task_sets_and_clears_horizon(tmp_path):
    s = _s(tmp_path)
    t = add_task(s, "Send deck")
    assert edit_task(s, t["id"], {"horizon": "2099-01-01"})["horizon"] == "2099-01-01"
    assert edit_task(s, t["id"], {"horizon": None})["horizon"] is None
    assert get_open_tasks(s)[0]["horizon"] is None


def test_is_behind_horizon():
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=1)).isoformat()
    past = (date.today() - timedelta(days=1)).isoformat()
    assert is_behind_horizon({"horizon": None}) is False
    assert is_behind_horizon({}) is False
    assert is_behind_horizon({"horizon": today}) is False   # visible ON the horizon date
    assert is_behind_horizon({"horizon": future}) is True
    assert is_behind_horizon({"horizon": past}) is False


def test_is_behind_horizon_explicit_today():
    assert is_behind_horizon({"horizon": "2026-07-10"}, today="2026-07-09") is True
    assert is_behind_horizon({"horizon": "2026-07-10"}, today="2026-07-10") is False


def test_get_surfaced_tasks(tmp_path):
    s = _s(tmp_path)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    future = (date.today() + timedelta(days=3)).isoformat()
    add_task(s, "Arrived today", horizon=today)
    add_task(s, "Arrived yesterday", horizon=yesterday)
    add_task(s, "Still deferred", horizon=future)
    add_task(s, "No horizon")
    assert [t["title"] for t in get_surfaced_tasks(s)] == ["Arrived today"]


def test_get_surfaced_tasks_excludes_completed(tmp_path):
    s = _s(tmp_path)
    add_task(s, "Done already", horizon=date.today().isoformat())
    complete_task(s, "Done already")
    assert get_surfaced_tasks(s) == []
