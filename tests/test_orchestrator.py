"""Tests for bot-as-orchestrator capabilities."""

import json
import os
import tempfile


def _config(tmp_dir: str) -> dict:
    return {
        "data_dir": tmp_dir,
        "captures_file": os.path.join(tmp_dir, "captures.md"),
        "projects_file": os.path.join(tmp_dir, "projects.md"),
        "people_dir": os.path.join(tmp_dir, "people"),
        "issues_file": os.path.join(tmp_dir, "issues.json"),
        "pipeline": {"cache_path": os.path.join(tmp_dir, "pipeline_cache.json")},
        "email": "trent@teambuildr.com",
        "notion_queue_path": os.path.join(tmp_dir, "notion_updates_queue.json"),
        "brief_prefs_path": os.path.join(tmp_dir, "brief_prefs.md"),
    }


def test_system_prompt_requires_receipt():
    from processors.query import _SYSTEM_PROMPT
    prompt_lower = _SYSTEM_PROMPT.lower()
    assert "receipt" in prompt_lower or "here's what i wrote" in prompt_lower or "here's what" in prompt_lower


# ── Task 2: queue_notion_update ──────────────────────────────────────────────

def test_queue_notion_update_add_note():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "queue_notion_update",
            {"person": "Jake Torres", "action": "add_note", "note": "Pricing concern raised"},
            config, storage=storage,
        )
        assert "Jake Torres" in result
        assert "cowork" in result.lower() or "next scheduled" in result.lower()
        with open(config["notion_queue_path"]) as f:
            queue = json.load(f)
        assert len(queue) == 1
        assert queue[0]["person"] == "Jake Torres"
        assert queue[0]["action"] == "add_note"
        assert queue[0]["note"] == "Pricing concern raised"
        assert "id" in queue[0]
        assert "timestamp" in queue[0]


def test_queue_notion_update_delete_requires_reason():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "queue_notion_update",
            {"person": "Jake Torres", "action": "delete_record"},
            config, storage=storage,
        )
        assert "reason" in result.lower()
        assert not os.path.exists(config["notion_queue_path"])


def test_queue_notion_update_invalid_action():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "queue_notion_update",
            {"person": "Jake Torres", "action": "explode"},
            config, storage=storage,
        )
        assert "invalid action" in result.lower()


def test_queue_notion_update_appends_multiple():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        execute_tool("queue_notion_update", {"person": "Alice", "action": "add_note", "note": "First"}, config, storage=storage)
        execute_tool("queue_notion_update", {"person": "Bob", "action": "update_stage", "stage": "Trial"}, config, storage=storage)
        with open(config["notion_queue_path"]) as f:
            queue = json.load(f)
        assert len(queue) == 2
        assert queue[1]["person"] == "Bob"


# ── Task 3: set_brief_preference ─────────────────────────────────────────────


def test_set_brief_preference_writes_to_file():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "set_brief_preference",
            {"preference": "Skip the gym scout section this week"},
            config, storage=storage,
        )
        assert "preference" in result.lower() or "brief" in result.lower()
        with open(config["brief_prefs_path"]) as f:
            content = f.read()
        assert "Skip the gym scout section this week" in content


def test_set_brief_preference_appends_multiple():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        execute_tool("set_brief_preference", {"preference": "First pref"}, config, storage=storage)
        execute_tool("set_brief_preference", {"preference": "Second pref"}, config, storage=storage)
        with open(config["brief_prefs_path"]) as f:
            content = f.read()
        assert "First pref" in content
        assert "Second pref" in content


def test_load_brief_prefs_returns_empty_when_missing():
    from lib.captures import load_brief_prefs

    with tempfile.TemporaryDirectory() as tmp:
        config = {"brief_prefs_path": os.path.join(tmp, "brief_prefs.md")}
        result = load_brief_prefs(config)
        assert result == ""


def test_load_brief_prefs_returns_content():
    from lib.captures import load_brief_prefs

    with tempfile.TemporaryDirectory() as tmp:
        prefs_path = os.path.join(tmp, "brief_prefs.md")
        with open(prefs_path, "w") as f:
            f.write("## 2026-05-14\n- Skip gym scout\n")
        config = {"brief_prefs_path": prefs_path}
        result = load_brief_prefs(config)
        assert "Skip gym scout" in result


# ── Task 4: brief prefs in daily brief ───────────────────────────────────────

def test_build_prompt_includes_brief_prefs():
    from processors.brief import _build_prompt
    result = _build_prompt(
        today_events=[], tomorrow_events=[], email_threads=[], projects=[],
        due_tasks=[], loop_summary=None, open_issues=[], drafts=[],
        meeting_prep=[], inbox_text="",
        brief_prefs_context="- Skip gym scout section\n- Lead with pipeline",
    )
    assert "Skip gym scout section" in result
    assert "Lead with pipeline" in result
