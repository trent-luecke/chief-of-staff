from collectors.gmail import EmailThread
from datetime import datetime
from watcher import classify_thread, is_active_hours
from unittest.mock import patch


def make_thread(subject: str, snippet: str, sender: str = "customer@gym.com") -> EmailThread:
    return EmailThread(
        id="t1", subject=subject, last_sender=sender,
        snippet=snippet, last_message_date=datetime.now(), needs_reply=True,
    )


def test_classify_thread_detects_flareup():
    thread = make_thread("Re: Login issue", "I can't log in — getting 500 error")
    _, is_flareup = classify_thread(thread, lead_index={})
    assert is_flareup is True


def test_classify_thread_no_flareup():
    thread = make_thread("Newsletter signup", "Thanks for subscribing")
    _, is_flareup = classify_thread(thread, lead_index={})
    assert is_flareup is False


def test_classify_thread_detects_lead():
    thread = make_thread("Hey", "Just checking in", sender="coach@apex.co")
    is_lead, _ = classify_thread(thread, lead_index={"coach@apex.co": "Apex"})
    assert is_lead is True


def test_is_active_hours_midday():
    with patch("watcher.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 18, 12, 0)
        assert is_active_hours() is True


def test_is_active_hours_evening():
    with patch("watcher.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 18, 20, 0)
        assert is_active_hours() is False
