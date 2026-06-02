import json
import pytest
from unittest.mock import MagicMock, patch
from lib.storage import LocalStorage
from processors.avoma_thread_state import set_phase1_complete


def _storage(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    for d in ["state", "memory"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return s


def _state_record(phase1_output="Action items: 1. Send pricing deck", transcript_json=None):
    return {
        "phase": 2,
        "avoma_uuid": "uuid-abc",
        "processed_at": "2026-06-02T14:00:00+00:00",
        "output_ts": "ts.999",
        "phase1_output": phase1_output,
        "transcript_json": transcript_json or {"uuid": "uuid-abc", "title": "Demo - Acme", "summary": "Good call."},
        "pending_correction": None,
    }


def _config():
    return {"ai_model": "claude-sonnet-4-6"}


def _make_text_response(text="Here is your answer."):
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


def _make_tool_response(description="Fix the name", writes=None, notion_payload=None, prompt="Reply yes to confirm"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "propose_correction"
    block.input = {
        "description": description,
        "writes": writes or [{"type": "observation_correction", "target": "observations.jsonl", "value": "corrected name"}],
        "notion_payload": notion_payload,
        "confirmation_prompt": prompt,
    }
    resp = MagicMock()
    resp.content = [block]
    return resp


def test_phase2_question_posts_answer(tmp_path):
    from processors.avoma_phase2 import run_phase2
    s = _storage(tmp_path)
    rec = _state_record()

    with patch("processors.avoma_phase2.anthropic.Anthropic") as mock_cls, \
         patch("processors.avoma_phase2.post_to_thread", return_value="ts.post") as mock_post:
        mock_cls.return_value.messages.create.return_value = _make_text_response("They discussed pricing on the call.")
        run_phase2("t.123", "what did they say about pricing?", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    mock_post.assert_called_once()
    assert "pricing" in mock_post.call_args[0][3].lower() or "discussed" in mock_post.call_args[0][3].lower()


def test_phase2_correction_stores_pending_and_posts_proposal(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from processors.avoma_thread_state import get_thread_record
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {})

    with patch("processors.avoma_phase2.anthropic.Anthropic") as mock_cls, \
         patch("processors.avoma_phase2.post_to_thread", return_value="ts.post") as mock_post:
        mock_cls.return_value.messages.create.return_value = _make_tool_response(
            description="Change rep name from Chris to Quinn"
        )
        run_phase2("t.123", "their account owner is Quinn not Chris", _state_record(), "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    rec = get_thread_record(s, "t.123")
    assert rec["pending_correction"] is not None
    assert "Quinn" in rec["pending_correction"]["description"] or "name" in rec["pending_correction"]["description"].lower()
    mock_post.assert_called_once()


def test_phase2_confirmation_applies_correction(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, get_thread_record
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {"uuid": "uuid-abc"})
    set_pending_correction(s, "t.123", {
        "description": "Fix rep name",
        "writes": [{"type": "observation_correction", "target": "observations.jsonl", "value": "corrected info"}],
        "notion_payload": None,
        "confirmation_prompt": "Reply yes to confirm",
    })

    state_rec = get_thread_record(s, "t.123")

    with patch("processors.avoma_phase2.post_to_thread", return_value="ts.ack") as mock_post:
        run_phase2("t.123", "yes", state_rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    rec = get_thread_record(s, "t.123")
    assert rec["pending_correction"] is None
    mock_post.assert_called_once()

    obs = (tmp_path / "memory" / "observations.jsonl").read_text()
    assert "correction" in obs


def test_phase2_rejection_clears_pending(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from processors.avoma_thread_state import set_phase1_complete, set_pending_correction, get_thread_record
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {})
    set_pending_correction(s, "t.123", {
        "description": "Fix name", "writes": [], "notion_payload": None, "confirmation_prompt": "Reply yes"
    })

    state_rec = get_thread_record(s, "t.123")

    with patch("processors.avoma_phase2.post_to_thread"):
        run_phase2("t.123", "no", state_rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    assert get_thread_record(s, "t.123")["pending_correction"] is None


def test_phase2_notion_payload_included_in_proposal(tmp_path):
    from processors.avoma_phase2 import run_phase2
    s = _storage(tmp_path)
    set_phase1_complete(s, "t.123", "uuid-abc", "ts.999", "output", {})

    notion_payload = "📤 Notion Pipeline Update — paste into Claude Desktop\nUpdate record for Acme..."

    with patch("processors.avoma_phase2.anthropic.Anthropic") as mock_cls, \
         patch("processors.avoma_phase2.post_to_thread") as mock_post:
        mock_cls.return_value.messages.create.return_value = _make_tool_response(
            notion_payload=notion_payload
        )
        run_phase2("t.123", "drop objection 1", _state_record(), "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    post_text = mock_post.call_args[0][3]
    assert "Notion" in post_text


# ---- Task-selection tests ----

def _state_record_with_actions(action_items):
    return {
        "phase": 2,
        "avoma_uuid": "uuid-abc",
        "processed_at": "2026-06-02T14:00:00+00:00",
        "output_ts": "ts.999",
        "phase1_output": "some output",
        "transcript_json": {
            "uuid": "uuid-abc",
            "title": "Demo - Acme Corp",
            "start_at": "2026-06-01T15:00:00Z",
            "action_items": action_items,
        },
        "pending_correction": None,
    }


def test_task_selection_add_single(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Send pricing deck", "Schedule follow-up", "Get IT contact"])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas") as mock_canvas:
        run_phase2("t.123", "add 2", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    tasks = get_open_tasks(s)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Schedule follow-up"
    assert tasks[0]["source"] == "avoma"
    assert tasks[0]["metadata"]["avoma_uuid"] == "uuid-abc"
    assert tasks[0]["metadata"]["thread_ts"] == "t.123"
    assert tasks[0]["metadata"]["call_title"] == "Demo - Acme Corp"
    assert tasks[0]["metadata"]["call_date"] == "2026-06-01"
    mock_canvas.assert_called_once()
    mock_post.assert_called_once()
    assert "1 task" in mock_post.call_args[0][3].lower()


def test_task_selection_add_multiple_comma(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Send pricing deck", "Schedule follow-up", "Get IT contact"])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add 1, 3", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    tasks = get_open_tasks(s)
    assert len(tasks) == 2
    titles = {t["title"] for t in tasks}
    assert titles == {"Send pricing deck", "Get IT contact"}
    assert "2 task" in mock_post.call_args[0][3].lower()


def test_task_selection_add_with_and(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Send pricing deck", "Schedule follow-up", "Get IT contact"])

    with patch("processors.avoma_phase2.post_to_thread"), \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add 1 and 3", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    tasks = get_open_tasks(s)
    assert len(tasks) == 2


def test_task_selection_add_all(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    items = ["Send pricing deck", "Schedule follow-up", "Get IT contact"]
    rec = _state_record_with_actions(items)

    with patch("processors.avoma_phase2.post_to_thread"), \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add all", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    assert len(get_open_tasks(s)) == 3


def test_task_selection_out_of_range_skipped(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions(["Only one item"])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas"):
        run_phase2("t.123", "add 1, 5", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    # index 5 is out of range — only item 1 added
    assert len(get_open_tasks(s)) == 1
    assert "1 task" in mock_post.call_args[0][3].lower()


def test_task_selection_no_action_items(tmp_path):
    from processors.avoma_phase2 import run_phase2
    from lib.tasks import get_open_tasks
    s = _storage(tmp_path)
    rec = _state_record_with_actions([])

    with patch("processors.avoma_phase2.post_to_thread") as mock_post, \
         patch("processors.avoma_phase2._sync_canvas") as mock_canvas:
        run_phase2("t.123", "add 1", rec, "slack-tok", "C-avoma", s, _config(), "anthropic-key")

    assert len(get_open_tasks(s)) == 0
    mock_canvas.assert_not_called()
    mock_post.assert_called_once()
    assert "no" in mock_post.call_args[0][3].lower() or "0" in mock_post.call_args[0][3]


def test_task_selection_does_not_intercept_question(tmp_path):
    """'add me to the call' should NOT be detected as task selection."""
    from processors.avoma_phase2 import _is_task_selection
    assert not _is_task_selection("add me to the call")
    assert not _is_task_selection("add something about pricing")
    assert not _is_task_selection("can you add a note")


def test_task_selection_pattern_variants():
    from processors.avoma_phase2 import _is_task_selection
    assert _is_task_selection("add 1")
    assert _is_task_selection("Add 1")
    assert _is_task_selection("add 1, 3")
    assert _is_task_selection("add 1 and 3")
    assert _is_task_selection("add 1 2 3")
    assert _is_task_selection("add all")
    assert _is_task_selection("ADD ALL")
