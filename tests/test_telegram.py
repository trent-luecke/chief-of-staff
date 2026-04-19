from unittest.mock import patch, MagicMock
from lib.telegram import send_message


def test_send_message_calls_correct_url():
    with patch("lib.telegram.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        send_message("TOKEN123", "CHAT456", "hello world")
    mock_post.assert_called_once_with(
        "https://api.telegram.org/botTOKEN123/sendMessage",
        json={"chat_id": "CHAT456", "text": "hello world"},
        timeout=10,
    )


def test_send_message_raises_on_http_error():
    with patch("lib.telegram.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("HTTP 403")
        mock_post.return_value = mock_resp
        try:
            send_message("TOKEN123", "CHAT456", "hello")
            assert False, "Should have raised"
        except Exception as e:
            assert "HTTP 403" in str(e)
