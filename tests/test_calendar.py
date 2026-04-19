from unittest.mock import patch, MagicMock
from datetime import date, datetime
import pytest
from collectors.calendar import fetch_today_events, fetch_two_day_events, CalendarEvent

MOCK_EVENTS_RESPONSE = {
    "items": [
        {
            "id": "evt_001",
            "summary": "Demo: Apex Fitness",
            "start": {"dateTime": "2026-04-17T09:00:00-07:00"},
            "end": {"dateTime": "2026-04-17T10:00:00-07:00"},
            "attendees": [
                {"email": "contact@apexfitness.com"},
                {"email": "trent@teambuildr.com", "self": True},
            ],
            "description": "Product demo",
        },
        {
            "id": "evt_002",
            "summary": "All day event",
            "start": {"date": "2026-04-17"},
            "end": {"date": "2026-04-18"},
        },
    ]
}


@pytest.fixture
def mock_calendar_service():
    with patch("collectors.calendar._build_service") as mock:
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = MOCK_EVENTS_RESPONSE
        mock.return_value = service
        yield service


def test_fetch_today_events_returns_events(mock_calendar_service):
    events = fetch_today_events(
        calendar_id="primary", target_date=date(2026, 4, 17), user_email="trent@teambuildr.com"
    )
    assert len(events) == 1
    assert events[0].id == "evt_001"
    assert events[0].summary == "Demo: Apex Fitness"
    assert isinstance(events[0].start, datetime)


def test_fetch_today_events_filters_all_day(mock_calendar_service):
    events = fetch_today_events(
        calendar_id="primary", target_date=date(2026, 4, 17), user_email="trent@teambuildr.com"
    )
    assert "All day event" not in [e.summary for e in events]


def test_fetch_today_events_handles_api_error():
    with patch("collectors.calendar._build_service") as mock:
        mock.side_effect = Exception("API unavailable")
        events = fetch_today_events(
            calendar_id="primary", target_date=date(2026, 4, 17), user_email="trent@teambuildr.com"
        )
        assert events == []


def test_fetch_two_day_events_returns_sorted_tuple(mock_calendar_service):
    today_events, tomorrow_events = fetch_two_day_events(
        calendar_ids=["primary"], user_email="trent@teambuildr.com"
    )
    assert len(today_events) == 1
    assert len(tomorrow_events) == 1
    assert isinstance(today_events[0].start, datetime)
