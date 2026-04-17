import json
from unittest.mock import patch, MagicMock
import pytest
from collectors.gmail import fetch_threads_needing_attention, EmailThread


MOCK_LIST_RESPONSE = {
    "threads": [
        {"id": "thread_001", "snippet": "Re: Contract renewal — sounds good"}
    ]
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
def mock_subprocess():
    with patch("collectors.gmail.subprocess.run") as mock:
        yield mock


def test_fetch_threads_returns_email_thread(mock_subprocess):
    mock_subprocess.side_effect = [
        MagicMock(stdout=json.dumps(MOCK_LIST_RESPONSE), returncode=0),
        MagicMock(stdout=json.dumps(MOCK_THREAD_RESPONSE), returncode=0),
    ]
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert len(threads) == 1
    assert threads[0].id == "thread_001"
    assert threads[0].subject == "Contract renewal"
    assert threads[0].last_sender == "John Smith <john@example.com>"


def test_fetch_threads_empty_when_gws_fails(mock_subprocess):
    mock_subprocess.return_value = MagicMock(stdout="{}", returncode=1)
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert threads == []


def test_fetch_threads_needs_reply_when_last_sender_is_not_user(mock_subprocess):
    mock_subprocess.side_effect = [
        MagicMock(stdout=json.dumps(MOCK_LIST_RESPONSE), returncode=0),
        MagicMock(stdout=json.dumps(MOCK_THREAD_RESPONSE), returncode=0),
    ]
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert threads[0].needs_reply is True


def test_fetch_threads_not_needs_reply_when_user_sent_last(mock_subprocess):
    thread_where_user_replied = {
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
    mock_subprocess.side_effect = [
        MagicMock(stdout=json.dumps({"threads": [{"id": "thread_002", "snippet": ""}]}), returncode=0),
        MagicMock(stdout=json.dumps(thread_where_user_replied), returncode=0),
    ]
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert threads[0].needs_reply is False
