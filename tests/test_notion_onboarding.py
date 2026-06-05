# tests/test_notion_onboarding.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from collectors.notion_onboarding import _parse_row, sync, DATABASE_ID


MOCK_ROW = {
    "id": "abc-123-def-456",
    "properties": {
        "Customer Name": {
            "type": "title",
            "title": [{"plain_text": "Acme Strength"}],
        },
        "Customer Email": {
            "type": "email",
            "email": "owner@acmestrength.com",
        },
        "Status": {
            "type": "select",
            "select": {"name": "In Progress"},
        },
        "Current Phase": {
            "type": "select",
            "select": {"name": "Phase 3 — Payment / Stripe Transfer"},
        },
        "Sales Rep": {
            "type": "select",
            "select": {"name": "Chris"},
        },
        "Start Date": {
            "type": "date",
            "date": {"start": "2026-05-15"},
        },
        "Target Go-Live Date": {
            "type": "date",
            "date": {"start": "2026-06-10"},
        },
    },
}


def test_parse_row_extracts_all_fields():
    record = _parse_row(MOCK_ROW)
    assert record["page_id"] == "abc-123-def-456"
    assert record["customer_name"] == "Acme Strength"
    assert record["customer_email"] == "owner@acmestrength.com"
    assert record["status"] == "In Progress"
    assert record["current_phase"] == "Phase 3 — Payment / Stripe Transfer"
    assert record["sales_rep"] == "Chris"
    assert record["start_date"] == "2026-05-15"
    assert record["target_go_live_date"] == "2026-06-10"


def test_parse_row_handles_missing_optional_fields():
    row = {
        "id": "xyz-999",
        "properties": {
            "Customer Name": {"type": "title", "title": []},
            "Customer Email": {"type": "email", "email": None},
            "Status": {"type": "select", "select": None},
            "Current Phase": {"type": "select", "select": None},
            "Sales Rep": {"type": "select", "select": None},
            "Start Date": {"type": "date", "date": None},
            "Target Go-Live Date": {"type": "date", "date": None},
        },
    }
    record = _parse_row(row)
    assert record["customer_name"] == ""
    assert record["customer_email"] is None
    assert record["status"] is None
    assert record["start_date"] is None


def test_database_id_constant_is_set():
    assert DATABASE_ID == "d4904af6-77b0-4507-8655-353ae4eadbd2"


def test_sync_writes_valid_cache_file():
    with patch("collectors.notion_onboarding._query_all", return_value=[MOCK_ROW]):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_path = f.name
        sync("fake-token", cache_path)
        data = json.loads(Path(cache_path).read_text())

    assert "synced_at" in data
    assert isinstance(data["records"], list)
    assert len(data["records"]) == 1
    assert data["records"][0]["customer_name"] == "Acme Strength"
    assert data["records"][0]["status"] == "In Progress"
