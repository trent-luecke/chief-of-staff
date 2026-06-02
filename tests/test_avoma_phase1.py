import json
import pytest
from unittest.mock import MagicMock, patch
from lib.storage import LocalStorage
from collectors.avoma import AvomaTranscript


def _storage(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    for d in ["state", "memory"]:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return s


def _fake_transcript(uuid="uuid-abc", title="TeamBuildr OS Demo - Acme Corp", os_interested=True):
    return AvomaTranscript(
        uuid=uuid,
        title=title,
        start_at="2026-06-02T14:00:00Z",
        participants=["john@acme.com", "trent@teambuildr.com"],
        call_type="demo",
        os_interested=os_interested,
        summary="Good demo. Strong interest.",
        features_covered=["scheduling"],
        gaps=["mobile app"],
        objections=[],
        buying_signals=["asked about pricing"],
        competitors=[],
        onboarding_completed=[],
        onboarding_next_steps=[],
        action_items=["Send pricing deck", "Schedule follow-up"],
    )


def _config():
    return {
        "ai_model": "claude-sonnet-4-6",
        "avoma": {
            "lookback_hours": 96,
            "filter_internal": True,
            "sales_rep_emails": ["trent@teambuildr.com"],
        },
    }


def test_run_phase1_posts_output_to_thread(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="https://avoma.com/meetings/uuid-abc"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript()), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="1234.9999") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    mock_post.assert_called_once()
    # First call is the summary message; Notion payload is a second call
    first_call = mock_post.call_args_list[0]
    assert first_call[0][1] == "C-avoma"  # channel_id
    assert first_call[0][2] == "t.123"    # thread_ts
    assert "Action Items" in first_call[0][3] or "action" in first_call[0][3].lower()


def test_run_phase1_sets_processed_state(tmp_path):
    from processors.avoma_phase1 import run_phase1
    from processors.avoma_thread_state import is_processed
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="https://avoma.com/meetings/uuid-abc"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript()), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="1234.9999"), \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    assert is_processed(s, "t.123") is True


def test_run_phase1_is_idempotent(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="url"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript()), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="1234.9999") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")
        run_phase1("t.123", "C-avoma", "second call", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    # OS-interested call posts summary + Notion payload (2 calls); second run is skipped entirely
    assert mock_post.call_count == 2


def test_run_phase1_posts_error_when_transcript_not_found(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="no uuid here"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value=None), \
         patch("processors.avoma_phase1.fetch_recent_meetings", return_value=[]), \
         patch("processors.avoma_phase1.post_to_thread", return_value=None) as mock_post:
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    mock_post.assert_called_once()
    posted_text = mock_post.call_args[0][3]
    assert "not found" in posted_text.lower() or "could not" in posted_text.lower()


def test_run_phase1_includes_notion_block_for_os_interested(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="url"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript(os_interested=True)), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="ts") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    output = mock_post.call_args[0][3]
    assert "Notion" in output


def test_run_phase1_omits_notion_block_for_non_os(tmp_path):
    from processors.avoma_phase1 import run_phase1
    s = _storage(tmp_path)

    with patch("processors.avoma_phase1.get_thread_root_text", return_value="url"), \
         patch("processors.avoma_phase1.extract_avoma_uuid_from_text", return_value="uuid-abc"), \
         patch("processors.avoma_phase1.fetch_meeting_by_uuid", return_value=_fake_transcript(os_interested=False)), \
         patch("processors.avoma_phase1._write_observation"), \
         patch("processors.avoma_phase1.post_to_thread", return_value="ts") as mock_post, \
         patch("processors.avoma_phase1._load_registry", return_value={"people": []}), \
         patch("processors.avoma_phase1._save_registry"):
        run_phase1("t.123", "C-avoma", "ready to process", s, _config(), "avoma-key", "anthropic-key", "slack-tok")

    output = mock_post.call_args[0][3]
    assert "Notion" not in output
