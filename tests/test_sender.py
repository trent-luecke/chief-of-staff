from unittest.mock import patch, MagicMock
import pytest
from processors.brief import BriefContent
from processors.loops import LoopSummary
from outputs.sender import build_html_email, send_brief_email


def make_brief() -> BriefContent:
    return BriefContent(
        act_today=["Close Apex", "Reply to contract email", "Check trials"],
        what_moved=["CrossFit Box had a demo"],
        metric_flags=["All GTM metrics in range"],
    )


def test_build_html_email_contains_act_today():
    html = build_html_email(
        brief=make_brief(),
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        template_dir="templates",
    )
    assert "Close Apex" in html
    assert "CrossFit Box had a demo" in html
    assert "All GTM metrics in range" in html


def test_build_html_email_contains_no_metric_data_fallback():
    brief_no_flags = BriefContent(
        act_today=[],
        what_moved=[],
        metric_flags=[],
    )
    html = build_html_email(
        brief=brief_no_flags,
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        template_dir="templates",
    )
    assert "No metric data available" in html
    assert "Nothing urgent today" in html


def test_send_brief_email_calls_gmail_api(mock_gmail_service):
    mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_001", "threadId": "thread_001"}

    result = send_brief_email(
        gmail_service=mock_gmail_service,
        to_email="trent@teambuildr.com",
        subject="Morning Brief",
        html_body="<h1>Brief</h1>",
    )
    msg_id, thread_id = result
    assert msg_id == "msg_001"
    assert thread_id == "thread_001"
    mock_gmail_service.users().messages().send.assert_called_once()


def test_send_brief_email_encodes_html(mock_gmail_service):
    mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_002", "threadId": "thread_002"}
    send_brief_email(
        gmail_service=mock_gmail_service,
        to_email="trent@teambuildr.com",
        subject="Test",
        html_body="<p>Hello</p>",
    )
    call_args = mock_gmail_service.users().messages().send.call_args
    body = call_args.kwargs["body"]
    assert "raw" in body


def test_send_brief_email_uses_thread_id_when_provided(mock_gmail_service):
    mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_003", "threadId": "thread_003"}
    send_brief_email(
        gmail_service=mock_gmail_service,
        to_email="trent@teambuildr.com",
        subject="Re: Morning Brief",
        html_body="<p>Got it.</p>",
        thread_id="thread_003",
    )
    call_args = mock_gmail_service.users().messages().send.call_args
    body = call_args.kwargs["body"]
    assert body.get("threadId") == "thread_003"


def test_build_html_email_contains_feedback_footer():
    html = build_html_email(
        brief=make_brief(),
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        template_dir="templates",
    )
    assert "Reply to this email" in html


@pytest.fixture
def mock_gmail_service():
    return MagicMock()
