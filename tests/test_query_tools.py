import os
import tempfile
import pytest
import json as _json
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


def test_add_people_note_appends_to_file():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        os.makedirs(config["people_dir"])
        with open(os.path.join(config["people_dir"], "ryan_smith.md"), "w") as f:
            f.write("# Ryan Smith\n## Activity\n- Called 2026-04-01\n")
        result = execute_tool("add_people_note", {"person_name": "Ryan", "note": "Going on vacation for 2 weeks"}, config)
        assert "ryan" in result.lower() or "added" in result.lower() or "noted" in result.lower()
        with open(os.path.join(config["people_dir"], "ryan_smith.md")) as f:
            content = f.read()
        assert "Going on vacation for 2 weeks" in content


def test_add_people_note_returns_error_when_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        os.makedirs(config["people_dir"])
        result = execute_tool("add_people_note", {"person_name": "Nobody", "note": "test"}, config)
        assert "not found" in result.lower() or "no file" in result.lower() or "no match" in result.lower()


def test_update_project_next_action():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        with open(config["projects_file"], "w") as f:
            f.write("## Project: LTV Lead Magnet\n**Status:** In Progress\n**Next:** Old action\n**Notes:** some notes\n")
        result = execute_tool("update_project_next_action", {"project_name": "LTV", "next_action": "Ship MVP by Friday"}, config)
        assert "updated" in result.lower() or "ltv" in result.lower()
        with open(config["projects_file"]) as f:
            content = f.read()
        assert "Ship MVP by Friday" in content
        assert "Old action" not in content


def test_create_project_appends_to_file():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        with open(config["projects_file"], "w") as f:
            f.write("## Project: Existing\n**Status:** Active\n**Next:** Do thing\n**Notes:** notes\n")
        result = execute_tool("create_project", {
            "name": "New Campaign",
            "description": "Q3 outreach campaign",
            "next_action": "Draft list of targets"
        }, config)
        assert "created" in result.lower() or "new campaign" in result.lower()
        with open(config["projects_file"]) as f:
            content = f.read()
        assert "New Campaign" in content
        assert "Draft list of targets" in content


def test_resolve_issue_marks_resolved():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        issues = {"issues": [{"id": "abc123", "title": "Apex login broken", "source": "gmail",
            "source_ref": "thread1", "channel": "gmail", "created_date": "2026-04-20",
            "last_seen_date": "2026-04-20", "status": "open", "actions_needed": [],
            "outside_parties": [], "resolved_date": None}]}
        with open(config["issues_file"], "w") as f:
            _json.dump(issues, f)
        result = execute_tool("resolve_issue", {"title_fragment": "Apex login"}, config)
        assert "resolved" in result.lower() or "apex" in result.lower()
        with open(config["issues_file"]) as f:
            data = _json.load(f)
        assert data["issues"][0]["status"] == "resolved"


def test_resolve_issue_returns_error_when_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        with open(config["issues_file"], "w") as f:
            _json.dump({"issues": []}, f)
        result = execute_tool("resolve_issue", {"title_fragment": "nonexistent"}, config)
        assert "not found" in result.lower() or "no issue" in result.lower() or "no match" in result.lower() or "no open" in result.lower()


def test_update_config_safe_key():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "config.json")
        cfg = {"issue_auto_resolve_days": 3, "memory": {"retrieval_token_budget": 550}}
        with open(config_path, "w") as f:
            _json.dump(cfg, f)
        config = _config(tmp)
        config["_config_path"] = config_path
        result = execute_tool("update_config", {"key": "issue_auto_resolve_days", "value": 5}, config)
        assert "updated" in result.lower() or "issue_auto_resolve_days" in result.lower()
        with open(config_path) as f:
            updated = _json.load(f)
        assert updated["issue_auto_resolve_days"] == 5


def test_update_config_rejects_unsafe_key():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "config.json")
        with open(config_path, "w") as f:
            _json.dump({"email": "trent@teambuildr.com"}, f)
        config = _config(tmp)
        config["_config_path"] = config_path
        result = execute_tool("update_config", {"key": "email", "value": "hacker@evil.com"}, config)
        assert "not allowed" in result.lower() or "safe" in result.lower() or "cannot" in result.lower() or "allowed" in result.lower()
        # email must not have changed
        with open(config_path) as f:
            data = _json.load(f)
        assert data["email"] == "trent@teambuildr.com"


def test_update_config_nested_key():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = os.path.join(tmp, "config.json")
        cfg = {"issue_auto_resolve_days": 3, "memory": {"retrieval_token_budget": 550}}
        with open(config_path, "w") as f:
            _json.dump(cfg, f)
        config = _config(tmp)
        config["_config_path"] = config_path
        result = execute_tool("update_config", {"key": "memory.retrieval_token_budget", "value": 400}, config)
        assert "updated" in result.lower() or "memory" in result.lower()
        with open(config_path) as f:
            updated = _json.load(f)
        assert updated["memory"]["retrieval_token_budget"] == 400


def test_add_to_backlog_creates_inbox_section():
    with tempfile.TemporaryDirectory() as tmp:
        backlog_path = os.path.join(tmp, "BACKLOG.md")
        with open(backlog_path, "w") as f:
            f.write("# Chief of Staff — Backlog\n\n## P1 — Done\n")
        config = _config(tmp)
        config["_backlog_path"] = backlog_path
        result = execute_tool("add_to_backlog", {"description": "Add web search tool"}, config)
        assert "added" in result.lower() or "backlog" in result.lower()
        with open(backlog_path) as f:
            content = f.read()
        assert "Add web search tool" in content
        assert "📥 Inbox" in content


def test_add_to_backlog_appends_to_existing_inbox():
    with tempfile.TemporaryDirectory() as tmp:
        backlog_path = os.path.join(tmp, "BACKLOG.md")
        with open(backlog_path, "w") as f:
            f.write("# Chief of Staff — Backlog\n\n## 📥 Inbox\n- 2026-04-21: Existing item\n")
        config = _config(tmp)
        config["_backlog_path"] = backlog_path
        execute_tool("add_to_backlog", {"description": "New item"}, config)
        with open(backlog_path) as f:
            content = f.read()
        assert "Existing item" in content
        assert "New item" in content
        assert content.index("New item") < content.index("Existing item")


from unittest.mock import patch, MagicMock


def test_search_gmail_returns_thread_summaries():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        mock_thread = MagicMock()
        mock_thread.last_sender = "john@apex.com"
        mock_thread.subject = "Re: Onboarding questions"
        mock_thread.snippet = "Quick question about the dashboard"
        with patch("processors.query_tools.fetch_threads_needing_attention", return_value=[mock_thread]):
            result = execute_tool("search_gmail", {"query": "from:john@apex.com", "max_results": 5}, config)
        assert "Onboarding questions" in result
        assert "john@apex.com" in result


def test_search_gmail_returns_empty_message_when_no_results():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        with patch("processors.query_tools.fetch_threads_needing_attention", return_value=[]):
            result = execute_tool("search_gmail", {"query": "from:nobody@nowhere.com"}, config)
        assert "no" in result.lower() or "0" in result.lower()


def test_get_pipeline_lead_returns_lead_data():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        leads = {"leads": [{"name": "Apex Fitness", "status": "In-Trial / Post Demo", "email": "john@apex.com",
            "contact": "John", "priority": "High", "last_contacted": "2026-04-20",
            "days_since_contact": 2, "estimated_value": 500.0, "source": "inbound", "stale": False}]}
        with open(config["pipeline"]["cache_path"], "w") as f:
            _json.dump(leads, f)
        result = execute_tool("get_pipeline_lead", {"lead_name": "Apex"}, config)
        assert "Apex Fitness" in result
        assert "In-Trial" in result


def test_get_pipeline_lead_returns_error_when_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        with open(config["pipeline"]["cache_path"], "w") as f:
            _json.dump({"leads": []}, f)
        result = execute_tool("get_pipeline_lead", {"lead_name": "Nobody"}, config)
        assert "not found" in result.lower() or "no lead" in result.lower()


def test_create_email_draft_calls_gmail_api():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        mock_service = MagicMock()
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {"id": "draft123"}
        with patch("processors.query_tools.build_gmail_service", return_value=mock_service):
            result = execute_tool("create_email_draft", {
                "to": "john@apex.com",
                "subject": "Following up on demo",
                "body": "Hi John, just wanted to follow up..."
            }, config)
        assert "draft" in result.lower()
        assert mock_service.users.return_value.drafts.return_value.create.called
