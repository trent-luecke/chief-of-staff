import json
from unittest.mock import patch, MagicMock
import pytest
from datetime import datetime
from processors.brief import generate_brief, BriefContent
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.local_data import Project, RecurringTask
from processors.loops import LoopSummary


MOCK_BRIEF_JSON = {
    "executive_summary": "Today is focused on demos and follow-ups.",
    "top_3_priorities": ["Close Apex Fitness", "Reply to contract renewal email", "Review pipeline"],
    "watch_outs": ["Apex trial ends Friday"],
    "schedule_notes": "Back-to-back demos 9-11am — no buffer",
}


def make_mock_claude_response(text: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


def test_generate_brief_returns_content(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(
        json.dumps(MOCK_BRIEF_JSON)
    )
    events = [CalendarEvent(id="e1", summary="Demo: Apex", start=datetime.now(), end=datetime.now())]
    projects = [Project(name="CRM", status="In Progress", next_step="Deploy")]
    tasks = [RecurringTask(name="Check trials", schedule="daily")]

    content = generate_brief(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        today_events=events,
        tomorrow_events=[],
        email_threads=[],
        projects=projects,
        due_tasks=tasks,
        loop_summary=LoopSummary(),
    )

    assert content.executive_summary == "Today is focused on demos and follow-ups."
    assert len(content.top_3_priorities) == 3
    assert content.watch_outs == ["Apex trial ends Friday"]
    assert content.schedule_notes == "Back-to-back demos 9-11am — no buffer"


def test_generate_brief_handles_markdown_wrapped_json(mock_anthropic):
    wrapped = f"```json\n{json.dumps(MOCK_BRIEF_JSON)}\n```"
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(wrapped)

    content = generate_brief(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
    )
    assert content.executive_summary == "Today is focused on demos and follow-ups."


def test_generate_brief_uses_correct_model(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(
        json.dumps(MOCK_BRIEF_JSON)
    )
    generate_brief(
        api_key="sk-test",
        model="claude-sonnet-4-6",
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
    )
    call_kwargs = mock_anthropic.return_value.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-sonnet-4-6"


def test_generate_brief_raises_on_invalid_json(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(
        "This is not JSON at all, just plain text."
    )
    with pytest.raises(ValueError, match="Claude returned non-JSON response"):
        generate_brief(
            api_key="sk-test",
            model="claude-haiku-4-5-20251001",
            today_events=[],
            tomorrow_events=[],
            email_threads=[],
            projects=[],
            due_tasks=[],
            loop_summary=LoopSummary(),
        )


def test_generate_brief_prompt_includes_calendar_events(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(
        json.dumps(MOCK_BRIEF_JSON)
    )
    event = CalendarEvent(
        id="e1",
        summary="9am Demo: Crossfit Box",
        start=datetime(2026, 4, 17, 9, 0),
        end=datetime(2026, 4, 17, 10, 0),
    )
    generate_brief(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        today_events=[event],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
    )
    call_kwargs = mock_anthropic.return_value.messages.create.call_args
    user_prompt = call_kwargs.kwargs["messages"][0]["content"]
    assert "Crossfit Box" in user_prompt


@pytest.fixture
def mock_anthropic():
    with patch("processors.brief.anthropic.Anthropic") as mock:
        yield mock
