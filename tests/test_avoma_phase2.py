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
