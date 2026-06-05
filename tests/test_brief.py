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
    "act_today": [
        "Close Apex Fitness — trial ends Friday, send contract today",
        "Reply to renewal email from SportsPlex — 3 days stale",
    ],
    "what_moved": [
        "CrossFit Box had a demo — strong interest in OS pricing",
    ],
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

    assert len(content.act_today) == 2
    assert "Apex Fitness" in content.act_today[0]
    assert content.what_moved == ["CrossFit Box had a demo — strong interest in OS pricing"]
    assert content.metric_flags == []


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
    assert len(content.act_today) == 2


def test_generate_brief_stores_metric_flags(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(
        json.dumps(MOCK_BRIEF_JSON)
    )
    flags = ["Leads MTD: tracking 40% below pace — next month tracking light"]

    content = generate_brief(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        metric_flags=flags,
    )
    assert content.metric_flags == flags


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


def test_people_context_appears_in_prompt():
    from processors.brief import _build_prompt

    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=MagicMock(resolved_email_ids=[], still_open_email_ids=[]),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        people_context="# Luke Martin\n**Email:** lmartin@teambuildr.com",
    )
    assert "Luke Martin" in prompt
    assert "People Context" in prompt


def test_build_prompt_includes_memory_context():
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary
    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        memory_context="## Cross-Day Memory\n\n**apex** Apex stuck 4 weeks.",
    )
    assert "Cross-Day Memory" in prompt
    assert "apex" in prompt


def test_build_prompt_omits_memory_section_when_empty():
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary
    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        memory_context="",
    )
    assert "Cross-Day Memory" not in prompt


def test_brief_includes_project_section(tmp_path):
    from lib.storage import LocalStorage
    from lib.projects import add_project
    from lib.tasks import add_task
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary

    storage = LocalStorage(str(tmp_path))
    project = add_project(storage, canonical_name="Vero AI Launch", status="active")
    add_task(storage, title="Write launch email", project_id=project["id"])

    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        storage=storage,
    )

    assert "Vero AI Launch" in prompt
    assert "Write launch email" in prompt
    assert "Structured Projects" in prompt


def test_brief_omits_project_section_when_no_projects(tmp_path):
    from lib.storage import LocalStorage
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary

    storage = LocalStorage(str(tmp_path))

    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        storage=storage,
    )

    assert "Structured Projects" not in prompt


def test_brief_omits_project_section_when_storage_is_none():
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary

    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        storage=None,
    )

    assert "Structured Projects" not in prompt


@pytest.fixture
def mock_anthropic():
    with patch("processors.brief.anthropic.Anthropic") as mock:
        yield mock
