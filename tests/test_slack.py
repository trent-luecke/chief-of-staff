from unittest.mock import MagicMock, patch
import pytest
from collectors.slack import fetch_channel_messages, SlackMessage, resolve_channel_ids

MOCK_HISTORY = {
    "messages": [
        {
            "type": "message",
            "text": "App is down — users reporting login failures",
            "user": "U123",
            "ts": "1713450000.123456",
            "thread_ts": "1713450000.123456",
            "reply_count": 2,
        },
        {
            "type": "message",
            "subtype": "bot_message",
            "text": "Deployment complete",
            "ts": "1713450100.000000",
        },
    ]
}

MOCK_CHANNELS = {
    "channels": [
        {"id": "C001", "name": "support"},
        {"id": "C002", "name": "support-tickets"},
    ]
}


def test_fetch_channel_messages_excludes_bots(mock_client):
    mock_client.return_value.conversations_history.return_value = MOCK_HISTORY
    messages = fetch_channel_messages(token="xoxb-test", channel_id="C001", since_hours=1)
    assert len(messages) == 1
    assert messages[0].text == "App is down — users reporting login failures"
    assert messages[0].thread_ts == "1713450000.123456"


def test_fetch_channel_messages_returns_empty_on_error(mock_client):
    from slack_sdk.errors import SlackApiError
    mock_client.return_value.conversations_history.side_effect = SlackApiError(
        "error", {"error": "not_in_channel"}
    )
    messages = fetch_channel_messages(token="xoxb-test", channel_id="C001", since_hours=1)
    assert messages == []


def test_resolve_channel_ids(mock_client):
    mock_client.return_value.conversations_list.return_value = MOCK_CHANNELS
    ids = resolve_channel_ids(token="xoxb-test", channel_names=["support", "support-tickets"])
    assert ids == {"support": "C001", "support-tickets": "C002"}


@pytest.fixture
def mock_client():
    with patch("collectors.slack.WebClient") as m:
        yield m
