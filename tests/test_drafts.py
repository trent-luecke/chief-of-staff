# tests/test_drafts.py
import json
from unittest.mock import patch, MagicMock
import pytest
from processors.drafts import generate_demo_followup, generate_lead_outreach, generate_trial_followup, Draft
from collectors.calendar import CalendarEvent
from datetime import datetime


def make_mock_claude(text: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


MOCK_DRAFT = json.dumps({
    "subject": "Great connecting today",
    "body": "Hi,\n\nThanks for taking the time today...",
    "to": "contact@example.com",
})


def make_event(summary: str, attendees: list[str]) -> CalendarEvent:
    dt = datetime(2026, 4, 18, 10, 0)
    return CalendarEvent(id="e1", summary=summary, start=dt, end=dt, attendees=attendees)


def test_generate_demo_followup_returns_draft(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(MOCK_DRAFT)
    event = make_event("Demo: Apex Fitness", ["contact@apexfitness.com"])
    draft = generate_demo_followup(api_key="sk-test", model="claude-haiku-4-5-20251001", event=event)
    assert draft is not None
    assert draft.subject == "Great connecting today"
    assert draft.to == "contact@apexfitness.com"
    assert draft.draft_type == "demo_followup"


def test_generate_demo_followup_no_attendees_returns_none(mock_anthropic):
    event = make_event("Demo: Apex Fitness", [])
    draft = generate_demo_followup(api_key="sk-test", model="claude-haiku-4-5-20251001", event=event)
    assert draft is None


def test_generate_lead_outreach_returns_draft(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(MOCK_DRAFT)
    draft = generate_lead_outreach(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        lead_name="John Smith", lead_email="john@crossfitgym.com",
        gym_name="CrossFit Denver", snippet="30 athletes, comp team",
    )
    assert draft is not None
    assert draft.draft_type == "lead_outreach"


def test_generate_trial_followup_returns_draft(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(MOCK_DRAFT)
    draft = generate_trial_followup(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        lead_name="Jane Doe", lead_email="jane@gym.com", days_in_trial=7,
    )
    assert draft is not None
    assert draft.draft_type == "trial_followup"


@pytest.fixture
def mock_anthropic():
    with patch("processors.drafts.anthropic.Anthropic") as m:
        yield m
