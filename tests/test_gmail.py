from unittest.mock import patch, MagicMock
import pytest
from collectors.gmail import fetch_threads_needing_attention, fetch_threads_for_attendee, EmailThread

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


# ── fetch_threads_for_attendee ──────────────────────────────────────────────

def test_fetch_threads_for_attendee_passes_attendee_email_in_query():
    """The Gmail query must include the attendee's email address."""
    with patch("collectors.gmail._build_service") as mock_build:
        service = MagicMock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "t1", "snippet": "Looking forward to our call"}]
        }
        service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t1",
            "messages": [{
                "id": "m1",
                "payload": {"headers": [
                    {"name": "Subject", "value": "Calendly confirmed"},
                    {"name": "From", "value": "bre@crossfitcentral.com"},
                    {"name": "To", "value": "trent@teambuildr.com"},
                ]},
                "internalDate": "1748476800000",
            }],
        }
        mock_build.return_value = service

        fetch_threads_for_attendee("trent@teambuildr.com", "bre@crossfitcentral.com", max_results=5)

        list_call = service.users.return_value.threads.return_value.list
        query_used = list_call.call_args.kwargs.get("q") or list_call.call_args.args[0] if list_call.call_args.args else list_call.call_args[1].get("q", "")
        assert "bre@crossfitcentral.com" in query_used


def test_fetch_threads_for_attendee_returns_thread_objects():
    """Returns populated EmailThread objects for matching threads."""
    with patch("collectors.gmail._build_service") as mock_build:
        service = MagicMock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "t99", "snippet": "Re: demo booking"}]
        }
        service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "t99",
            "messages": [{
                "id": "m99",
                "payload": {"headers": [
                    {"name": "Subject", "value": "Demo booking confirmed"},
                    {"name": "From", "value": "bre@crossfitcentral.com"},
                    {"name": "To", "value": "trent@teambuildr.com"},
                ]},
                "internalDate": "1748476800000",
            }],
        }
        mock_build.return_value = service

        threads = fetch_threads_for_attendee("trent@teambuildr.com", "bre@crossfitcentral.com")
        assert len(threads) == 1
        assert threads[0].subject == "Demo booking confirmed"


def test_fetch_threads_for_attendee_returns_empty_on_failure():
    """Returns [] when the Gmail API raises an exception."""
    with patch("collectors.gmail._build_service") as mock_build:
        mock_build.side_effect = Exception("no credentials")
        threads = fetch_threads_for_attendee("trent@teambuildr.com", "bre@crossfitcentral.com")
        assert threads == []
