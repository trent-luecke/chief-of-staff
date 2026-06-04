# tests/test_leads_collector.py
from datetime import date
from unittest.mock import MagicMock

from collectors.sheets import fetch_leads_mtd


def _mock_service(rows):
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.return_value = {"values": rows}
    return svc


HEADER = ["Date", "Lead Name", "Source"]
CURRENT_MONTH = date.today().month


def test_fetch_leads_mtd_returns_current_month_only():
    rows = [
        HEADER,
        [f"{CURRENT_MONTH}/3", "Acme Strength", "Inbound"],
        [f"{CURRENT_MONTH}/12", "Peak Performance", "Referral"],
        ["1/5", "Old Lead", "Cold outreach"],
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    if CURRENT_MONTH == 1:
        assert result["count"] == 3
    else:
        assert result["count"] == 2
        assert result["entries"][0]["name"] == "Acme Strength"
        assert result["entries"][0]["source"] == "Inbound"


def test_fetch_leads_mtd_returns_empty_on_api_error():
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.side_effect = Exception("API error")
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    assert result == {"count": 0, "entries": []}


def test_fetch_leads_mtd_handles_partial_rows():
    rows = [
        HEADER,
        [f"{CURRENT_MONTH}/10", "Sparse Lead"],  # no source column
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    assert result["count"] == 1
    assert result["entries"][0]["source"] == ""


def test_fetch_leads_mtd_skips_rows_with_no_date():
    rows = [
        HEADER,
        ["", "No Date Lead", "Web"],
        [f"{CURRENT_MONTH}/15", "Has Date Lead", "Inbound"],
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads")
    assert result["count"] == 1
    assert result["entries"][0]["name"] == "Has Date Lead"


def test_fetch_leads_mtd_all_months_when_month_none():
    rows = [
        HEADER,
        ["1/5", "Jan Lead", "Inbound"],
        ["3/12", "Mar Lead", "Referral"],
    ]
    svc = _mock_service(rows)
    result = fetch_leads_mtd(svc, "fake-id", "New Leads", month=None)
    assert result["count"] == 2
