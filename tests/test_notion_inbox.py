from unittest.mock import patch, MagicMock
import pytest
from collectors.notion_inbox import fetch_inbox_items, InboxItem


MOCK_NOTION_RESPONSE = {
    "results": [
        {
            "id": "page_001",
            "properties": {
                "Name": {"title": [{"plain_text": "Follow up with Sarah on proposal"}]},
                "Type": {"select": {"name": "Follow-up"}},
                "Urgency": {"select": {"name": "High"}},
                "Category": {"select": {"name": "Sales"}},
                "Source": {"select": {"name": "Apple Shortcut"}},
            },
            "created_time": "2026-04-16T20:00:00.000Z",
        }
    ],
    "has_more": False,
}


def test_fetch_inbox_items_returns_items(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: MOCK_NOTION_RESPONSE,
    )
    items = fetch_inbox_items(
        token="secret_test",
        database_id="db_001",
        filter_statuses=["Inbox"],
    )
    assert len(items) == 1
    assert items[0].id == "page_001"
    assert items[0].name == "Follow up with Sarah on proposal"
    assert items[0].urgency == "High"
    assert items[0].item_type == "Follow-up"


def test_fetch_inbox_items_returns_empty_on_auth_error(mock_post):
    mock_post.return_value = MagicMock(status_code=401, json=lambda: {})
    items = fetch_inbox_items(token="bad", database_id="db_001", filter_statuses=["Inbox"])
    assert items == []


def test_fetch_inbox_items_returns_empty_on_empty_results(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"results": [], "has_more": False},
    )
    items = fetch_inbox_items(token="secret_test", database_id="db_001", filter_statuses=["Inbox"])
    assert items == []


def test_fetch_inbox_items_handles_missing_select_fields(mock_post):
    """Items with missing optional select fields should still parse."""
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "results": [
                {
                    "id": "page_002",
                    "properties": {
                        "Name": {"title": [{"plain_text": "Minimal item"}]},
                    },
                    "created_time": "2026-04-16T20:00:00.000Z",
                }
            ]
        },
    )
    items = fetch_inbox_items(token="secret_test", database_id="db_001", filter_statuses=["Inbox"])
    assert len(items) == 1
    assert items[0].name == "Minimal item"
    assert items[0].urgency == ""  # empty string for missing select


@pytest.fixture
def mock_post():
    with patch("collectors.notion_inbox.requests.post") as mock:
        yield mock
