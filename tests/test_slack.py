from unittest.mock import MagicMock, patch
import pytest
from collectors.slack import fetch_channel_messages, SlackMessage, resolve_channel_ids, fetch_dm_messages, SlackDM

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

MOCK_DM_CHANNELS = {
    "channels": [
        {"id": "D001", "user": "U123", "is_open": True},
        {"id": "D002", "user": "U456", "is_open": False},  # closed DM — should be skipped
    ]
}

MOCK_USER_INFO = {
    "user": {
        "profile": {
            "real_name": "Luke Martin",
            "display_name": "lmartin",
            "email": "lmartin@teambuildr.com",
        }
    }
}

MOCK_DM_HISTORY = {
    "messages": [
        {"type": "message", "text": "Can you send me the CSM list?", "user": "U123",
         "ts": "1713450000.0", "thread_ts": "1713450000.0", "reply_count": 0},
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


def test_fetch_dm_messages_returns_dm_for_open_channel(mock_client):
    mock_client.return_value.conversations_list.return_value = MOCK_DM_CHANNELS
    mock_client.return_value.conversations_history.return_value = MOCK_DM_HISTORY
    mock_client.return_value.users_info.return_value = MOCK_USER_INFO

    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)

    assert len(dms) == 1
    assert dms[0].user_id == "U123"
    assert dms[0].display_name == "Luke Martin"
    assert dms[0].email == "lmartin@teambuildr.com"
    assert dms[0].messages == ["Can you send me the CSM list?"]


def test_fetch_dm_messages_skips_closed_channels(mock_client):
    mock_client.return_value.conversations_list.return_value = MOCK_DM_CHANNELS
    mock_client.return_value.conversations_history.return_value = {"messages": []}
    mock_client.return_value.users_info.return_value = MOCK_USER_INFO

    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)
    assert all(dm.channel_id != "D002" for dm in dms)


def test_fetch_dm_messages_returns_empty_on_api_error(mock_client):
    from slack_sdk.errors import SlackApiError
    mock_client.return_value.conversations_list.side_effect = SlackApiError(
        "error", {"error": "not_authed"}
    )
    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)
    assert dms == []


def test_fetch_dm_messages_handles_missing_email(mock_client):
    mock_client.return_value.conversations_list.return_value = {
        "channels": [{"id": "D001", "user": "U999", "is_open": True}]
    }
    mock_client.return_value.conversations_history.return_value = MOCK_DM_HISTORY
    mock_client.return_value.users_info.return_value = {
        "user": {"profile": {"real_name": "Unknown Person", "display_name": "unknown"}}
    }
    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)
    assert len(dms) == 1
    assert dms[0].email == ""


@pytest.fixture
def mock_client():
    with patch("collectors.slack.WebClient") as m:
        yield m
