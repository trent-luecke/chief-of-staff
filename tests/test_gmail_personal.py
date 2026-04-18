import json
from unittest.mock import patch, MagicMock
import pytest
from collectors.gmail_personal import fetch_personal_emails, PersonalEmail

MOCK_LIST = {"threads": [{"id": "t1", "snippet": "Are you picking up Maya today?"}]}

MOCK_THREAD = {
    "id": "t1",
    "messages": [{
        "id": "m1",
        "payload": {"headers": [
            {"name": "Subject", "value": "Pickup today?"},
            {"name": "From", "value": "wife@gmail.com"},
        ]},
        "internalDate": "1713450000000",
    }]
}


def test_fetch_personal_emails_allowlisted_sender(mock_sub):
    mock_sub.side_effect = [
        MagicMock(stdout=json.dumps(MOCK_LIST), returncode=0),
        MagicMock(stdout=json.dumps(MOCK_THREAD), returncode=0),
    ]
    emails = fetch_personal_emails(
        profile="personal",
        allowed_senders=["wife@gmail.com"],
        allowed_domains=[],
        max_results=10,
    )
    assert len(emails) == 1
    assert emails[0].subject == "Pickup today?"
    assert emails[0].sender == "wife@gmail.com"


def test_fetch_personal_emails_blocks_unknown_sender(mock_sub):
    mock_sub.side_effect = [
        MagicMock(stdout=json.dumps(MOCK_LIST), returncode=0),
        MagicMock(stdout=json.dumps(MOCK_THREAD), returncode=0),
    ]
    emails = fetch_personal_emails(
        profile="personal",
        allowed_senders=["someone-else@gmail.com"],
        allowed_domains=[],
        max_results=10,
    )
    assert len(emails) == 0


def test_fetch_personal_emails_gws_failure_returns_empty(mock_sub):
    mock_sub.return_value = MagicMock(stdout="{}", returncode=1)
    emails = fetch_personal_emails(
        profile="personal", allowed_senders=["x@y.com"], allowed_domains=[], max_results=10
    )
    assert emails == []


def test_sender_email_parses_display_name_format(mock_sub):
    thread_with_display_name = {
        "id": "t2",
        "messages": [{
            "id": "m2",
            "payload": {"headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "Jane Smith <jane@school.edu>"},
            ]},
            "internalDate": "1713450000000",
        }]
    }
    mock_sub.side_effect = [
        MagicMock(stdout=json.dumps({"threads": [{"id": "t2", "snippet": "hi"}]}), returncode=0),
        MagicMock(stdout=json.dumps(thread_with_display_name), returncode=0),
    ]
    emails = fetch_personal_emails(
        profile="personal",
        allowed_senders=["jane@school.edu"],
        allowed_domains=[],
        max_results=10,
    )
    assert len(emails) == 1
    assert emails[0].sender == "jane@school.edu"


@pytest.fixture
def mock_sub():
    with patch("collectors.gmail_personal.subprocess.run") as m:
        yield m
