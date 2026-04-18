from collectors.gmail import EmailThread
from datetime import datetime
from watcher import detect_flareups_from_gmail, is_business_hours
from unittest.mock import patch


def make_thread(subject: str, snippet: str) -> EmailThread:
    return EmailThread(
        id="t1", subject=subject, last_sender="customer@gym.com",
        snippet=snippet, last_message_date=datetime.now(), needs_reply=True,
    )


def test_detect_flareups_from_gmail_keyword_match():
    threads = [
        make_thread("Re: Login issue", "I can't log in — getting 500 error"),
        make_thread("Newsletter signup", "Thanks for subscribing"),
    ]
    flareups = detect_flareups_from_gmail(threads)
    assert len(flareups) == 1
    assert flareups[0].subject == "Re: Login issue"


def test_detect_flareups_from_gmail_empty():
    flareups = detect_flareups_from_gmail([])
    assert flareups == []


def test_is_business_hours_midday():
    with patch("watcher.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 18, 12, 0)
        assert is_business_hours() is True


def test_is_business_hours_evening():
    with patch("watcher.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 18, 20, 0)
        assert is_business_hours() is False
