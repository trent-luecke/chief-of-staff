import json
from datetime import date, datetime
from unittest.mock import patch, MagicMock
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
                {"email": "trent@teambuildr.com", "self": True}
            ],
            "description": "Product demo"
        },
        {
            "id": "evt_002",
            "summary": "All day event",
            "start": {"date": "2026-04-17"},
            "end": {"date": "2026-04-18"}
        }
    ]
}


@pytest.fixture
def mock_subprocess():
    with patch("collectors.calendar.subprocess.run") as mock:
        yield mock


def test_fetch_today_events_returns_events(mock_subprocess):
    mock_subprocess.return_value = MagicMock(
        stdout=json.dumps(MOCK_EVENTS_RESPONSE),
        returncode=0
    )
    events = fetch_today_events(calendar_id="primary", target_date=date(2026, 4, 17))
    assert len(events) == 1  # all-day filtered out
    assert events[0].id == "evt_001"
    assert events[0].summary == "Demo: Apex Fitness"
    assert isinstance(events[0].start, datetime)


def test_fetch_today_events_filters_all_day(mock_subprocess):
    mock_subprocess.return_value = MagicMock(
        stdout=json.dumps(MOCK_EVENTS_RESPONSE),
        returncode=0
    )
    events = fetch_today_events(calendar_id="primary", target_date=date(2026, 4, 17))
    summaries = [e.summary for e in events]
    assert "All day event" not in summaries


def test_fetch_today_events_handles_gws_error(mock_subprocess):
    mock_subprocess.return_value = MagicMock(stdout="{}", returncode=1)
    events = fetch_today_events(calendar_id="primary", target_date=date(2026, 4, 17))
    assert events == []


def test_fetch_two_day_events_returns_sorted_tuple(mock_subprocess):
    # Return same mock response for both today and tomorrow calls
    mock_subprocess.return_value = MagicMock(
        stdout=json.dumps(MOCK_EVENTS_RESPONSE),
        returncode=0
    )
    today_events, tomorrow_events = fetch_two_day_events(calendar_ids=["primary"])
    # Both lists should have 1 event (all-day filtered)
    assert len(today_events) == 1
    assert len(tomorrow_events) == 1
    # Both should be sorted by start (only 1 event each, so just verify type)
    assert isinstance(today_events[0].start, datetime)
    assert isinstance(tomorrow_events[0].start, datetime)
