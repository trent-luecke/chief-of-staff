import pytest
from unittest.mock import patch, MagicMock


def test_extract_uuid_from_url():
    from collectors.avoma import extract_avoma_uuid_from_text
    text = "New recording: https://my.avoma.com/meetings/3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    result = extract_avoma_uuid_from_text(text)
    assert result == "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


def test_extract_uuid_case_insensitive():
    from collectors.avoma import extract_avoma_uuid_from_text
    text = "UUID: 3F2504E0-4F89-11D3-9A0C-0305E82C3301"
    result = extract_avoma_uuid_from_text(text)
    assert result == "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


def test_extract_uuid_returns_none_when_absent():
    from collectors.avoma import extract_avoma_uuid_from_text
    assert extract_avoma_uuid_from_text("No UUID here") is None
    assert extract_avoma_uuid_from_text("") is None


def _mock_meeting_response(uuid="test-uuid-1234", transcript_ready=True, title="TeamBuildr OS Demo - Acme"):
    return {
        "uuid": uuid,
        "subject": title,
        "start_at": "2026-06-02T14:00:00Z",
        "transcript_ready": transcript_ready,
        "attendees": [
            {"name": "John Smith", "email": "john@acme.com"},
            {"name": "Trent Luecke", "email": "trent@teambuildr.com"},
        ],
    }


def test_fetch_meeting_by_uuid_returns_transcript():
    from collectors.avoma import fetch_meeting_by_uuid

    mock_meeting = _mock_meeting_response()
    mock_analysis = {
        "os_interested": True,
        "call_type": "demo",
        "summary": "Good demo call.",
        "features_covered": ["scheduling"],
        "gaps": [],
        "objections": [],
        "buying_signals": ["asked about pricing"],
        "competitors": [],
        "onboarding_completed": [],
        "onboarding_next_steps": [],
        "action_items": ["Send pricing deck"],
    }

    with patch("collectors.avoma.requests.get") as mock_get, \
         patch("collectors.avoma._fetch_transcript", return_value=([], [{"speaker_id": "1", "transcript": "Hi there"}])), \
         patch("collectors.avoma._analyze_with_claude", return_value=mock_analysis):

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_meeting
        mock_get.return_value = mock_resp

        transcript = fetch_meeting_by_uuid("avoma-key", "anthropic-key", "claude-sonnet-4-6", "test-uuid-1234")

    assert transcript is not None
    assert transcript.uuid == "test-uuid-1234"
    assert transcript.title == "TeamBuildr OS Demo - Acme"
    assert transcript.os_interested is True
    assert transcript.action_items == ["Send pricing deck"]
    assert "John Smith" in transcript.participants


def test_fetch_meeting_by_uuid_returns_none_when_not_ready():
    from collectors.avoma import fetch_meeting_by_uuid

    with patch("collectors.avoma.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = _mock_meeting_response(transcript_ready=False)
        mock_get.return_value = mock_resp

        result = fetch_meeting_by_uuid("avoma-key", "anthropic-key", "claude-sonnet-4-6", "test-uuid")

    assert result is None


def test_fetch_meeting_by_uuid_returns_none_on_api_error():
    from collectors.avoma import fetch_meeting_by_uuid
    import requests

    with patch("collectors.avoma.requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("network error")
        result = fetch_meeting_by_uuid("avoma-key", "anthropic-key", "claude-sonnet-4-6", "test-uuid")

    assert result is None
