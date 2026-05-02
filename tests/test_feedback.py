import pytest
from unittest.mock import patch, MagicMock

from lib.storage import LocalStorage
from processors.feedback import classify_feedback, append_brief_feedback, FeedbackResult


def test_classify_feedback_action_signal():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"classification": "action_signal", "capture_type": "flag", "capture_target": "Apex", "capture_content": "elevate in tomorrow brief", "delivery_note": null, "clarification_question": null}')]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "Elevate Apex", "Morning Brief — Monday")

    assert result.classification == "action_signal"
    assert result.capture_type == "flag"
    assert result.capture_target == "Apex"
    assert result.capture_content == "elevate in tomorrow brief"


def test_classify_feedback_delivery_note():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"classification": "delivery_note", "capture_type": null, "capture_target": null, "capture_content": null, "delivery_note": "Cut gym scout section unless 3+ leads", "clarification_question": null}')]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "Too much gym stuff", "Morning Brief")

    assert result.classification == "delivery_note"
    assert result.delivery_note == "Cut gym scout section unless 3+ leads"
    assert result.capture_content is None


def test_classify_feedback_unclear():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text='{"classification": "unclear", "capture_type": null, "capture_target": null, "capture_content": null, "delivery_note": null, "clarification_question": "What would you like me to do?"}')]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "hmm", "Morning Brief")

    assert result.classification == "unclear"
    assert result.clarification_question is not None


def test_classify_feedback_handles_malformed_json():
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="not json")]

    with patch("processors.feedback.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_cls.return_value = mock_client
        result = classify_feedback("fake-key", "claude-sonnet-4-6", "anything", "Brief")

    assert result.classification == "unclear"
    assert result.clarification_question is not None


def test_append_brief_feedback_writes_timestamped_line(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    append_brief_feedback(storage, "Cut gym scout section unless 3+ leads")
    content = storage.read("brief_feedback.md")
    assert "Cut gym scout section" in content
    assert "##" in content


def test_append_brief_feedback_accumulates(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))
    append_brief_feedback(storage, "First note")
    append_brief_feedback(storage, "Second note")
    lines = [l for l in storage.read("brief_feedback.md").splitlines() if l.strip()]
    assert len(lines) >= 4  # 2 headers + 2 notes
