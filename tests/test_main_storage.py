# tests/test_main_storage.py
import json
from lib.main_storage import MainStorage


def _store(blobs):
    """blobs: {repo_rel_path: content}. Returns a MainStorage reading from that dict."""
    return MainStorage(read_blob=lambda rel: blobs.get(rel))


def test_read_falls_back_to_blob():
    s = _store({"data/tasks.jsonl": '{"id":"a"}\n'})
    assert s.read("tasks.jsonl") == '{"id":"a"}\n'


def test_read_missing_blob_returns_none():
    assert _store({}).read("tasks.jsonl") is None


def test_write_then_read_uses_buffer():
    s = _store({"data/tasks.jsonl": "old\n"})
    s.write("tasks.jsonl", "new\n")
    assert s.read("tasks.jsonl") == "new\n"


def test_append_line_starts_from_blob():
    s = _store({"data/tasks.jsonl": '{"id":"a"}\n'})
    s.append_line("tasks.jsonl", '{"id":"b"}')
    assert s.read("tasks.jsonl") == '{"id":"a"}\n{"id":"b"}\n'


def test_append_line_on_missing_blob():
    s = _store({})
    s.append_line("notes.jsonl", '{"id":"n"}')
    assert s.read("notes.jsonl") == '{"id":"n"}\n'


def test_exists_reflects_blob_and_buffer():
    s = _store({"data/a.json": "{}"})
    assert s.exists("a.json") is True
    assert s.exists("b.json") is False
    s.write("b.json", "{}")
    assert s.exists("b.json") is True


def test_read_json_and_write_json():
    s = _store({"data/projects_registry.json": json.dumps({"version": 1, "projects": []})})
    data = s.read_json("projects_registry.json")
    assert data == {"version": 1, "projects": []}
    data["projects"].append({"id": "x"})
    s.write_json("projects_registry.json", data)
    assert s.read_json("projects_registry.json")["projects"] == [{"id": "x"}]


def test_read_json_default_on_missing():
    assert _store({}).read_json("x.json", default={"k": 1}) == {"k": 1}


def test_dirty_maps_to_repo_rel_paths():
    s = _store({})
    s.write("tasks.jsonl", "line\n")
    s.write_json("notes_tags.json", [])
    assert s.dirty() == {"data/tasks.jsonl": "line\n", "data/notes_tags.json": "[]"}


# append to tests/test_main_storage.py
import lib.tasks as tasks_lib
import lib.projects as projects_lib


def test_add_task_against_main_storage():
    s = _store({"data/tasks.jsonl": '{"event":"create","task_id":"t-aaa","title":"old","source":"slack","created_at":"2026-01-01","due_date":null,"metadata":{},"project_id":null,"collaborators":[],"owner":null}\n'})
    task = tasks_lib.add_task(s, "new task", source="ui")
    # buffer should now contain the original line plus the new create event
    content = s.read("tasks.jsonl")
    assert '"title": "new task"' in content
    assert "t-aaa" in content  # original preserved
    assert "data/tasks.jsonl" in s.dirty()
    # open tasks replays both
    open_titles = {t["title"] for t in tasks_lib.get_open_tasks(s)}
    assert {"old", "new task"} <= open_titles


def test_add_project_against_main_storage():
    s = _store({"data/projects_registry.json": json.dumps({"version": 1, "projects": []})})
    proj = projects_lib.add_project(s, "Test Project")
    assert proj["id"] == "test-project"
    assert s.dirty() == {"data/projects_registry.json": json.dumps({"version": 1, "projects": [proj]}, indent=2)}
