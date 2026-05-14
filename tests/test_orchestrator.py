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


# ── Task 5: propose_code_change ───────────────────────────────────────────────
from unittest.mock import patch, MagicMock


def test_propose_code_change_rejects_non_whitelisted_file():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        result = execute_tool(
            "propose_code_change",
            {"file": "cloudflare/telegram-bridge.js", "description": "test", "new_content": "x"},
            config, storage=storage,
        )
        assert "whitelist" in result.lower() or "not on the" in result.lower()


def test_propose_code_change_rejects_syntax_error():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        bad_python = "def broken(\n  print('hello')\n"
        config = _config(tmp)
        storage = LocalStorage(tmp)
        pending_path = os.path.join(tmp, "pending_change.json")
        with patch("processors.query_tools.PENDING_CHANGE_PATH", pending_path):
            with patch("processors.query_tools.CHANGE_WHITELIST", frozenset({"processors/query.py"})):
                result = execute_tool(
                    "propose_code_change",
                    {"file": "processors/query.py", "description": "break it", "new_content": bad_python},
                    config, storage=storage,
                )
        assert "syntax" in result.lower() or "failed" in result.lower()
        assert not os.path.exists(pending_path)


def test_propose_code_change_blocks_if_pending_exists():
    from processors.query_tools import execute_tool
    from lib.storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        storage = LocalStorage(tmp)
        pending_path = os.path.join(tmp, "pending_change.json")
        with open(pending_path, "w") as f:
            json.dump({"file": "main.py", "description": "old change", "new_content": "# old"}, f)
        with patch("processors.query_tools.PENDING_CHANGE_PATH", pending_path):
            result = execute_tool(
                "propose_code_change",
                {"file": "main.py", "description": "new change", "new_content": "# new"},
                config, storage=storage,
            )
        assert "pending" in result.lower()
        assert "approve" in result.lower() or "reject" in result.lower()


# ── Task 6: approve/reject routing ───────────────────────────────────────────
import subprocess as _subprocess
from unittest.mock import patch, MagicMock, call


def _write_pending_change(path: str, file_rel: str, new_content: str, description: str = "test change") -> None:
    with open(path, "w") as f:
        json.dump({
            "timestamp": "2026-05-14T10:00:00Z",
            "file": file_rel,
            "description": description,
            "diff": "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-old\n+new\n",
            "new_content": new_content,
        }, f)


def test_handle_pending_change_reject_deletes_file():
    with tempfile.TemporaryDirectory() as tmp:
        pending_path = os.path.join(tmp, "pending_change.json")
        _write_pending_change(pending_path, "main.py", "# new\n")
        with patch("ask.PENDING_CHANGE_PATH", pending_path):
            with patch("ask.send_message") as mock_send:
                from ask import _handle_pending_change
                _handle_pending_change("reject", "123", "fake-token")
    assert not os.path.exists(pending_path)
    mock_send.assert_called_once()
    assert "rejected" in mock_send.call_args[0][2].lower()


def test_handle_pending_change_approve_writes_and_commits():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "main.py")
        with open(target, "w") as f:
            f.write("# old\n")
        pending_path = os.path.join(tmp, "pending_change.json")
        _write_pending_change(pending_path, target, "# new content\n")
        with patch("ask.PENDING_CHANGE_PATH", pending_path):
            with patch("ask.CHANGE_WHITELIST", {target}):
                with patch("ask.send_message") as mock_send:
                    with patch("ask.subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0)
                        from ask import _handle_pending_change
                        _handle_pending_change("approve", "123", "fake-token")
                        with open(target) as f:
                            assert f.read() == "# new content\n"
                        assert not os.path.exists(pending_path)
                        mock_send.assert_called_once()
                        assert "applied" in mock_send.call_args[0][2].lower()
                        # verify git pull + git add + commit + push were called
                        calls = [str(c) for c in mock_run.call_args_list]
                        assert any("pull" in c for c in calls)
                        assert any("git" in c for c in calls)
