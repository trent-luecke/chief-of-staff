import os
import tempfile
import pytest
from processors.query_tools import execute_tool


def _config(tmp_dir: str) -> dict:
    return {
        "captures_file": os.path.join(tmp_dir, "captures.md"),
        "projects_file": os.path.join(tmp_dir, "projects.md"),
        "people_dir": os.path.join(tmp_dir, "people"),
        "issues_file": os.path.join(tmp_dir, "issues.json"),
        "pipeline": {"cache_path": os.path.join(tmp_dir, "pipeline_cache.json")},
        "email": "trent@teambuildr.com",
        "calendar_ids": ["primary"],
        "memory": {"retrieval_token_budget": 550},
    }


def test_add_capture_writes_to_file():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        result = execute_tool("add_capture", {"capture_type": "todo", "text": "Call Marcus"}, config)
        assert "captured" in result.lower() or "added" in result.lower()
        with open(config["captures_file"]) as f:
            content = f.read()
        assert "Call Marcus" in content
        assert "[todo]" in content


def test_complete_task_removes_from_captures():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        with open(config["captures_file"], "w") as f:
            f.write("## 2026-04-22 10:00 — [todo] Call Marcus\n")
        result = execute_tool("complete_task", {"description": "Call Marcus"}, config)
        assert "completed" in result.lower()
        with open(config["captures_file"]) as f:
            content = f.read()
        assert "Call Marcus" not in content
        # projects file doesn't exist — should not be created
        assert not os.path.exists(config["projects_file"])


def test_complete_task_returns_error_when_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        with open(config["captures_file"], "w") as f:
            f.write("## 2026-04-22 10:00 — [todo] Something else\n")
        result = execute_tool("complete_task", {"description": "Nonexistent task"}, config)
        assert "not found" in result.lower() or "no match" in result.lower()


def test_execute_tool_unknown_name_returns_error():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        result = execute_tool("nonexistent_tool", {}, config)
        assert "unknown" in result.lower()


def test_execute_tool_missing_key_returns_clear_message():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        result = execute_tool("add_capture", {}, config)  # missing capture_type and text
        assert "missing" in result.lower() and "field" in result.lower()
