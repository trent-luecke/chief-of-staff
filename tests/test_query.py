import json
import os
import tempfile
from unittest.mock import patch, MagicMock

from processors.query import _load_local_context, answer_query, QueryResult, Capture


def _make_config(tmp_dir: str) -> dict:
    pipeline_cache = os.path.join(tmp_dir, "pipeline_cache.json")
    people_dir = os.path.join(tmp_dir, "people")
    issues_file = os.path.join(tmp_dir, "issues.json")
    captures_file = os.path.join(tmp_dir, "captures.md")
    os.makedirs(people_dir)

    with open(pipeline_cache, "w") as f:
        json.dump({"leads": [{"name": "Apex Fitness", "status": "trial", "contact": "john@apex.com"}]}, f)
    with open(issues_file, "w") as f:
        json.dump([{"title": "Follow up with Marcus", "age_days": 2, "source": "email", "channel": "inbox", "status": "open"}], f)
    with open(os.path.join(people_dir, "marcus.md"), "w") as f:
        f.write("# Marcus\n## Activity\n- Called 2026-04-18\n")

    return {
        "email": "trent@teambuildr.com",
        "pipeline": {"enabled": True, "cache_path": pipeline_cache},
        "people_dir": people_dir,
        "issues_file": issues_file,
        "captures_file": captures_file,
        "calendar_ids": ["primary"],
        "memory": {"enabled": False},
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


def test_load_local_context_includes_issues():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        context = _load_local_context(config)
        assert "Follow up with Marcus" in context


def test_answer_query_returns_query_result():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        intent_resp = MagicMock()
        intent_resp.content = [MagicMock(text='{"needs_live_gmail": false, "needs_live_calendar": false, "gmail_search_query": null, "calendar_date_range": null}')]
        answer_resp = MagicMock()
        answer_resp.content = [MagicMock(text='{"answer": "Apex Fitness is in trial.", "captures": []}')]

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [intent_resp, answer_resp]
            mock_cls.return_value = mock_client
            result = answer_query("fake-key", "claude-sonnet-4-6", "What's the status of Apex?", config)

        assert isinstance(result, QueryResult)
        assert "Apex" in result.answer
        assert result.captures == []


def test_answer_query_extracts_captures():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        intent_resp = MagicMock()
        intent_resp.content = [MagicMock(text='{"needs_live_gmail": false, "needs_live_calendar": false, "gmail_search_query": null, "calendar_date_range": null}')]
        answer_resp = MagicMock()
        answer_resp.content = [MagicMock(text='{"answer": "Done.", "captures": [{"type": "todo", "target": "Marcus", "content": "Call back re: contract"}]}')]

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [intent_resp, answer_resp]
            mock_cls.return_value = mock_client
            result = answer_query("fake-key", "claude-sonnet-4-6", "Remind me to call Marcus about his contract", config)

        assert len(result.captures) == 1
        assert result.captures[0].type == "todo"
        assert result.captures[0].target == "Marcus"
        assert result.captures[0].content == "Call back re: contract"


def test_answer_query_handles_malformed_json_gracefully():
    with tempfile.TemporaryDirectory() as tmp:
        config = _make_config(tmp)
        intent_resp = MagicMock()
        intent_resp.content = [MagicMock(text="not json")]
        answer_resp = MagicMock()
        answer_resp.content = [MagicMock(text="also not json")]

        with patch("processors.query.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = [intent_resp, answer_resp]
            mock_cls.return_value = mock_client
            result = answer_query("fake-key", "claude-sonnet-4-6", "anything", config)

        assert isinstance(result, QueryResult)
        assert len(result.answer) > 0
        assert result.captures == []
