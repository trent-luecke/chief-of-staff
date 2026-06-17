from unittest.mock import patch

from lib import alerts


def test_send_ops_alert_dms_operator_in_cloud(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.alerts.open_dm", return_value="D123") as mock_open, \
         patch("lib.alerts.post_message", return_value="111.222") as mock_post:
        sent = alerts.send_ops_alert("memory pipeline broke", slack_user_id="U04ECG6KEA3")
    assert sent is True
    mock_open.assert_called_once_with("xoxb-test", "U04ECG6KEA3")
    mock_post.assert_called_once_with("xoxb-test", "D123", "memory pipeline broke")


def test_send_ops_alert_noops_outside_github_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.alerts.open_dm") as mock_open, \
         patch("lib.alerts.post_message") as mock_post:
        sent = alerts.send_ops_alert("local run", slack_user_id="U04ECG6KEA3")
    assert sent is False
    mock_open.assert_not_called()
    mock_post.assert_not_called()


def test_send_ops_alert_force_sends_locally(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.alerts.open_dm", return_value="D123"), \
         patch("lib.alerts.post_message", return_value="111.222") as mock_post:
        sent = alerts.send_ops_alert("forced", slack_user_id="U04ECG6KEA3", force=True)
    assert sent is True
    mock_post.assert_called_once()


def test_send_ops_alert_skips_when_token_missing(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with patch("lib.alerts.open_dm") as mock_open:
        sent = alerts.send_ops_alert("no token", slack_user_id="U04ECG6KEA3")
    assert sent is False
    mock_open.assert_not_called()


def test_send_ops_alert_skips_when_user_id_missing(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.alerts.open_dm") as mock_open:
        sent = alerts.send_ops_alert("no user", slack_user_id="")
    assert sent is False
    mock_open.assert_not_called()


def test_send_ops_alert_never_raises_on_slack_error(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    with patch("lib.alerts.open_dm", side_effect=Exception("network down")):
        sent = alerts.send_ops_alert("boom", slack_user_id="U04ECG6KEA3")
    assert sent is False
