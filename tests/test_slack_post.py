import pytest
from unittest.mock import MagicMock, patch
from slack_sdk.errors import SlackApiError


def _make_post_client(ts="1234.5678"):
    client = MagicMock()
    resp = MagicMock()
    resp.data = {"ok": True, "ts": ts}
    client.chat_postMessage.return_value = resp
    return client


def _make_replies_client(text="Root message text"):
    client = MagicMock()
    resp = MagicMock()
    resp.data = {"messages": [{"text": text}]}
    client.conversations_replies.return_value = resp
    return client


def test_post_to_thread_returns_ts():
    from lib.slack_post import post_to_thread
    with patch("lib.slack_post.WebClient", return_value=_make_post_client("ts.999")):
        result = post_to_thread("tok", "C123", "t.123", "hello")
    assert result == "ts.999"


def test_post_to_thread_returns_none_on_slack_error():
    from lib.slack_post import post_to_thread
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError("fail", {"error": "not_in_channel"})
    with patch("lib.slack_post.WebClient", return_value=client):
        result = post_to_thread("tok", "C123", "t.123", "hello")
    assert result is None


def test_get_thread_root_text_returns_first_message():
    from lib.slack_post import get_thread_root_text
    with patch("lib.slack_post.WebClient", return_value=_make_replies_client("Avoma meeting text")):
        text = get_thread_root_text("tok", "C123", "t.123")
    # Returns full JSON of the message object so UUIDs in blocks are searchable
    assert "Avoma meeting text" in text


def test_get_thread_root_text_returns_empty_on_error():
    from lib.slack_post import get_thread_root_text
    client = MagicMock()
    client.conversations_replies.side_effect = SlackApiError("fail", {"error": "channel_not_found"})
    with patch("lib.slack_post.WebClient", return_value=client):
        text = get_thread_root_text("tok", "C123", "t.123")
    assert text == ""


def test_get_thread_root_text_returns_empty_on_no_messages():
    from lib.slack_post import get_thread_root_text
    client = MagicMock()
    resp = MagicMock()
    resp.data = {"messages": []}
    client.conversations_replies.return_value = resp
    with patch("lib.slack_post.WebClient", return_value=client):
        assert get_thread_root_text("tok", "C123", "t.123") == ""


def test_post_message_returns_ts():
    from lib.slack_post import post_message
    with patch("lib.slack_post.WebClient", return_value=_make_post_client("ts.001")):
        result = post_message("tok", "D04EQ4BBW2H", "hello")
    assert result == "ts.001"


def test_post_message_raises_on_slack_error():
    from lib.slack_post import post_message
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError("fail", {"error": "not_in_channel"})
    with patch("lib.slack_post.WebClient", return_value=client):
        with pytest.raises(SlackApiError):
            post_message("tok", "D04EQ4BBW2H", "hello")


def test_post_message_calls_correct_channel():
    from lib.slack_post import post_message
    with patch("lib.slack_post.WebClient", return_value=_make_post_client()) as mock_wc:
        post_message("tok", "D04EQ4BBW2H", "test message")
    mock_wc.return_value.chat_postMessage.assert_called_once_with(
        channel="D04EQ4BBW2H", text="test message"
    )
