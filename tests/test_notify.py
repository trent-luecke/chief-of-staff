from unittest.mock import patch
import lib.notify as notify


CONFIG = {"notifications": {"slack_user_id": "U_NOTIFY"}}


def test_notify_user_sends_to_dm(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.notify.open_dm", return_value="D123") as mock_open, \
         patch("lib.notify.post_message", return_value="1700.00") as mock_post:
        result = notify.notify_user("hello", CONFIG)
    assert result is True
    mock_open.assert_called_once_with("xoxb-test", "U_NOTIFY")
    mock_post.assert_called_once_with("xoxb-test", "D123", "hello")


def test_notify_user_falls_back_to_ops_alerts_user(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    cfg = {"ops_alerts": {"slack_user_id": "U_OPS"}}
    with patch("lib.notify.open_dm", return_value="D1") as mock_open, \
         patch("lib.notify.post_message", return_value="ts"):
        notify.notify_user("hi", cfg)
    mock_open.assert_called_once_with("xoxb-test", "U_OPS")


def test_notify_user_noops_without_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with patch("lib.notify.open_dm") as mock_open:
        result = notify.notify_user("hello", CONFIG)
    assert result is False
    mock_open.assert_not_called()


def test_notify_user_noops_without_user(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.notify.open_dm") as mock_open:
        result = notify.notify_user("hello", {})
    assert result is False
    mock_open.assert_not_called()


def test_notify_user_never_raises_on_slack_error(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.notify.open_dm", side_effect=Exception("slack down")):
        result = notify.notify_user("hello", CONFIG)
    assert result is False
