from unittest.mock import patch, MagicMock
import pytest
from collectors.gmail import fetch_threads_needing_attention, EmailThread

MOCK_LIST_RESPONSE = {
    "threads": [{"id": "thread_001", "snippet": "Re: Contract renewal — sounds good"}]
}

MOCK_THREAD_RESPONSE = {
    "id": "thread_001",
    "messages": [
        {
            "id": "msg_a",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Contract renewal"},
                    {"name": "From", "value": "John Smith <john@example.com>"},
                    {"name": "Date", "value": "Thu, 16 Apr 2026 10:00:00 -0700"},
                ]
            },
            "internalDate": "1713279600000",
        }
    ],
}


@pytest.fixture
def mock_gmail_service():
    with patch("collectors.gmail._build_service") as mock:
        service = MagicMock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = MOCK_LIST_RESPONSE
        service.users.return_value.threads.return_value.get.return_value.execute.return_value = MOCK_THREAD_RESPONSE
        mock.return_value = service
        yield service


def test_fetch_threads_returns_email_thread(mock_gmail_service):
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert len(threads) == 1
    assert threads[0].id == "thread_001"
    assert threads[0].subject == "Contract renewal"
    assert threads[0].last_sender == "John Smith <john@example.com>"


def test_fetch_threads_empty_when_api_fails():
    with patch("collectors.gmail._build_service") as mock:
        mock.side_effect = Exception("API error")
        threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
        assert threads == []


def test_fetch_threads_needs_reply_when_last_sender_is_not_user(mock_gmail_service):
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert threads[0].needs_reply is True


def test_fetch_threads_not_needs_reply_when_user_sent_last():
    with patch("collectors.gmail._build_service") as mock:
        service = MagicMock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "thread_002", "snippet": ""}]
        }
        service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "thread_002",
            "messages": [
                {
                    "id": "msg_b",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Follow up"},
                            {"name": "From", "value": "Trent Luecke <trent@teambuildr.com>"},
                        ]
                    },
                    "internalDate": "1713279600000",
                }
            ],
        }
        mock.return_value = service
        threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
        assert threads[0].needs_reply is False
