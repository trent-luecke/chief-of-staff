# tests/test_brief_extended.py
import json
from unittest.mock import patch, MagicMock
from datetime import date, datetime
import pytest
from processors.brief import generate_brief, BriefContent
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.local_data import Project, RecurringTask
from processors.loops import LoopSummary
from processors.issues import Issue
from processors.drafts import Draft


def make_mock_claude(text: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


MOCK_BRIEF = {
    "executive_summary": "Busy day — two demos, one open issue from yesterday, Monday pipeline review due.",
    "top_3_priorities": [
        "[ISSUE: 1 day, Slack #support] Login failures — still open, check with dev",
        "Demo: Apex Fitness at 10am — follow-up draft ready",
        "New leads in sales inbox — outreach drafts ready",
    ],
    "watch_outs": ["Apex trial ends Friday"],
    "schedule_notes": "Two demos back-to-back 10-11:30am, clear afternoon",
    "personal_items": ["wife@gmail.com: Pickup today?"],
    "recurring_due": ["Review sales pipeline (weekly, Monday)", "Budget tracker update (weekly, Monday)"],
    "drafts_ready": ["demo_followup: Apex Fitness — review and send"],
    "meeting_prep": [],
}


def test_generate_brief_includes_issue_fields(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(
        json.dumps(MOCK_BRIEF)
    )
    issues = [Issue(
        id="abc", title="Login failures", source="slack", source_ref="C001:123",
        channel="support", created_date=date.today().isoformat(),
        last_seen_date=date.today().isoformat(), status="open",
        actions_needed=[], outside_parties=[], resolved_date=None,
    )]
    brief = generate_brief(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        today_events=[], tomorrow_events=[], email_threads=[],
        projects=[], due_tasks=[], loop_summary=LoopSummary(),
        open_issues=issues, drafts=[], meeting_prep=[],
    )
    assert len(brief.top_3_priorities) == 3
    assert len(brief.recurring_due) == 2
    assert brief.executive_summary != ""


def test_generate_brief_handles_empty_new_fields(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(
        json.dumps(MOCK_BRIEF)
    )
    brief = generate_brief(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        today_events=[], tomorrow_events=[], email_threads=[],
        projects=[], due_tasks=[], loop_summary=LoopSummary(),
    )
    assert isinstance(brief.personal_items, list)
    assert isinstance(brief.drafts_ready, list)


@pytest.fixture
def mock_anthropic():
    with patch("processors.brief.anthropic.Anthropic") as m:
        yield m
