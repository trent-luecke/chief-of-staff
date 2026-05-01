import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from collectors.notion_bugs import BugTicket, fetch_bugs, _parse_bug_row, DATABASE_ID


MOCK_ROW = {
    "id": "abc-123",
    "properties": {
        "Ticket Name": {
            "type": "title",
            "title": [{"plain_text": "Payment widget crashes on iOS"}],
        },
        "Status": {
            "type": "status",
            "status": {"name": "In progress"},
        },
        "Priority Level": {
            "type": "select",
            "select": {"name": "High"},
        },
        "Technical Area of Issue": {
            "type": "multi_select",
            "multi_select": [
                {"name": "OS Mobile App"},
                {"name": "Payment Processing Error"},
            ],
        },
        "Date Created": {
            "type": "created_time",
            "created_time": "2026-04-19T12:00:00.000Z",
        },
        "Last Update": {
            "type": "last_edited_time",
            "last_edited_time": "2026-04-28T09:00:00.000Z",
        },
        "Date Completed": {
            "type": "date",
            "date": None,
        },
        "Shortcut URL": {
            "type": "url",
            "url": "https://app.shortcut.com/teambuildr/story/123",
        },
    },
}


def test_parse_bug_row_populates_all_fields():
    ticket = _parse_bug_row(MOCK_ROW)
    assert ticket.id == "abc-123"
    assert ticket.title == "Payment widget crashes on iOS"
    assert ticket.status == "In progress"
    assert ticket.priority_level == "High"
    assert ticket.technical_areas == ["OS Mobile App", "Payment Processing Error"]
    assert ticket.date_created == "2026-04-19"
    assert ticket.last_updated == "2026-04-28"
    assert ticket.date_completed is None
    assert ticket.shortcut_url == "https://app.shortcut.com/teambuildr/story/123"
    assert ticket.days_open >= 0


def test_parse_bug_row_handles_missing_optional_fields():
    row = {
        "id": "xyz-999",
        "properties": {
            "Ticket Name": {"type": "title", "title": []},
            "Status": {"type": "status", "status": None},
            "Priority Level": {"type": "select", "select": None},
            "Technical Area of Issue": {"type": "multi_select", "multi_select": []},
            "Date Created": {"type": "created_time", "created_time": "2026-04-01T00:00:00.000Z"},
            "Last Update": {"type": "last_edited_time", "last_edited_time": "2026-04-01T00:00:00.000Z"},
            "Date Completed": {"type": "date", "date": None},
            "Shortcut URL": {"type": "url", "url": None},
        },
    }
    ticket = _parse_bug_row(row)
    assert ticket.title == ""
    assert ticket.status is None
    assert ticket.priority_level is None
    assert ticket.technical_areas == []
    assert ticket.shortcut_url is None


def test_fetch_bugs_returns_bug_tickets():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [MOCK_ROW],
        "has_more": False,
    }
    with patch("collectors.notion_bugs.requests.post", return_value=mock_response):
        tickets = fetch_bugs("fake-token")
    assert len(tickets) == 1
    assert isinstance(tickets[0], BugTicket)
    assert tickets[0].title == "Payment widget crashes on iOS"


def test_fetch_bugs_returns_empty_list_on_api_error():
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    with patch("collectors.notion_bugs.requests.post", return_value=mock_response):
        tickets = fetch_bugs("bad-token")
    assert tickets == []
