from unittest.mock import patch, MagicMock
import pytest
from processors.brief import BriefContent
from processors.loops import LoopSummary
from outputs.sender import build_html_email, send_brief_email


def make_brief() -> BriefContent:
    return BriefContent(
        executive_summary="Today is busy.",
        top_3_priorities=["Close Apex", "Reply to contract email", "Check trials"],
        watch_outs=["Trial ending Friday"],
        schedule_notes="Back-to-back 9-11am",
    )


def test_build_html_email_contains_summary():
    html = build_html_email(
        brief=make_brief(),
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        template_dir="templates",
    )
    assert "Today is busy." in html
    assert "Close Apex" in html
    assert "Trial ending Friday" in html


def test_build_html_email_contains_no_open_loops_message():
    html = build_html_email(
        brief=make_brief(),
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        template_dir="templates",
    )
    assert "No open loops" in html


def test_send_brief_email_calls_gmail_api(mock_gmail_service):
    mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_001"}

    result = send_brief_email(
        gmail_service=mock_gmail_service,
        to_email="trent@teambuildr.com",
        subject="Morning Brief",
        html_body="<h1>Brief</h1>",
    )
    assert result == "msg_001"
    mock_gmail_service.users().messages().send.assert_called_once()


def test_send_brief_email_encodes_html(mock_gmail_service):
    mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {"id": "msg_002"}
    send_brief_email(
        gmail_service=mock_gmail_service,
        to_email="trent@teambuildr.com",
        subject="Test",
        html_body="<p>Hello</p>",
    )
    call_args = mock_gmail_service.users().messages().send.call_args
    body = call_args.kwargs.get("body") or call_args.args[0] if call_args.args else call_args.kwargs["body"]
    assert "raw" in body


@pytest.fixture
def mock_gmail_service():
    return MagicMock()
