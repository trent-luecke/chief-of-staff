import json
import os
import tempfile
from unittest.mock import patch, MagicMock

from processors.query import _load_local_context, answer_query_with_tools


def _make_config(tmp_dir: str) -> dict:
    pipeline_cache = os.path.join(tmp_dir, "pipeline_cache.json")
    people_dir = os.path.join(tmp_dir, "people")
    issues_file = os.path.join(tmp_dir, "issues.json")
    captures_file = os.path.join(tmp_dir, "captures.md")
    os.makedirs(people_dir)

    with open(pipeline_cache, "w") as f:
        json.dump({"leads": [{"name": "Apex Fitness", "status": "trial", "contact": "john@apex.com"}]}, f)
    with open(issues_file, "w") as f:
        json.dump({"issues": [{"title": "Follow up with Marcus", "age_days": 2, "source": "email",
            "channel": "inbox", "status": "open", "id": "abc", "source_ref": "t1",
            "created_date": "2026-04-20", "last_seen_date": "2026-04-20",
            "actions_needed": [], "outside_parties": [], "resolved_date": None}]}, f)
    with open(os.path.join(people_dir, "marcus.md"), "w") as f:
        f.write("# Marcus\n## Activity\n- Called 2026-04-18\n")

    return {
        "email": "trent@teambuildr.com",
        "pipeline": {"enabled": True, "cache_path": pipeline_cache},
        "people_dir": people_dir,
        "issues_file": issues_file,
        "captures_file": captures_file,
        "projects_file": os.path.join(tmp_dir, "projects.md"),
        "calendar_ids": ["primary"],
        "memory": {"enabled": False},
        "_config_path": os.path.join(tmp_dir, "config.json"),
        "_backlog_path": os.path.join(tmp_dir, "BACKLOG.md"),
    }


def test_load_local_context_includes_pipeline():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        context = _load_local_context(config)
        assert "Apex Fitness" in context


def test_load_local_context_includes_people():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        context = _load_local_context(config)
        assert "Marcus" in context


def test_answer_query_with_tools_returns_string_on_end_turn():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Apex Fitness is in trial, sir."

        response = MagicMock()
        response.stop_reason = "end_turn"
        response.content = [text_block]
        response.usage = MagicMock(input_tokens=100, output_tokens=50)

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = response
            mock_cls.return_value = mock_client
            result = answer_query_with_tools("fake-key", "claude-sonnet-4-6", "Status of Apex?", config)

        assert isinstance(result, str)
        assert "Apex" in result


def test_answer_query_with_tools_executes_tool_then_returns_answer():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_123"
        tool_block.name = "add_capture"
        tool_block.input = {"capture_type": "todo", "text": "Call Marcus"}

        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_response.content = [tool_block]
        tool_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Done. Added todo: Call Marcus."

        final_response = MagicMock()
        final_response.stop_reason = "end_turn"
        final_response.content = [text_block]
        final_response.usage = MagicMock(input_tokens=150, output_tokens=30)

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [tool_response, final_response]
            mock_cls.return_value = mock_client
            result = answer_query_with_tools("fake-key", "claude-sonnet-4-6", "Add todo: Call Marcus", config)

        assert isinstance(result, str)
        assert mock_client.messages.create.call_count == 2
        with open(config["captures_file"]) as f:
            assert "Call Marcus" in f.read()


def test_answer_query_with_tools_caps_at_10_iterations():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tu_loop"
        tool_block.name = "add_capture"
        tool_block.input = {"capture_type": "note", "text": "loop"}

        looping_response = MagicMock()
        looping_response.stop_reason = "tool_use"
        looping_response.content = [tool_block]
        looping_response.usage = MagicMock(input_tokens=50, output_tokens=10)

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = looping_response
            mock_cls.return_value = mock_client
            result = answer_query_with_tools("fake-key", "claude-sonnet-4-6", "loop forever", config)

        assert isinstance(result, str)
        assert mock_client.messages.create.call_count == 10
