from unittest.mock import MagicMock
from datetime import date

import pytest

from collectors.sheets import fetch_cancellations_mtd


def _mock_service(rows):
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.return_value = {"values": rows}
    return svc


HEADER = [
    "Jump to Bottom", "Date", "Account Name and #", "# of Months paid before Cancelation",
    "Reason for Cancelation", "Base Plan Type", "Base Plan", "Additions",
    "Monetary Value", "Answer", "Customer Returned", "Number of Months until Customer Returned",
    "Lifetime Value",
]

CURRENT_MONTH = date.today().month


def test_fetch_cancellations_mtd_returns_current_month_only():
    rows = [
        HEADER,
        ["", f"{CURRENT_MONTH}/14", "Acme Gym", "12", "App Complaints", "", "$150/mo", "", "$1,800", "had issues", "", "", "$1,800"],
        ["", "1/5", "Old Customer", "6", "Business Changes", "", "$100/mo", "", "$600", "old", "", "", "$600"],
    ]
    # Only the second row should match (other row is month 1, which won't match if current month != 1)
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    if CURRENT_MONTH == 1:
        # Both rows match in January
        assert result["count"] == 2
    else:
        assert result["count"] == 1
        assert result["entries"][0]["account_name"] == "Acme Gym"
        assert result["entries"][0]["reason"] == "App Complaints"
        assert result["entries"][0]["monetary_value"] == "$1,800"
        assert result["entries"][0]["customer_note"] == "had issues"


def test_fetch_cancellations_mtd_skips_rows_with_no_date():
    rows = [
        HEADER,
        ["", "", "No Date Row", "3", "reason", "", "$100", "", "$300", "", "", "", ""],
        ["", f"{CURRENT_MONTH}/20", "Has Date", "5", "Price", "", "$150", "", "$750", "", "", "", ""],
    ]
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    assert result["count"] == 1
    assert result["entries"][0]["account_name"] == "Has Date"


def test_fetch_cancellations_mtd_handles_partial_rows():
    rows = [
        HEADER,
        ["", f"{CURRENT_MONTH}/14", "Sparse Row"],  # only 3 columns
    ]
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    assert result["count"] == 1
    assert result["entries"][0]["account_name"] == "Sparse Row"
    assert result["entries"][0]["reason"] == ""


def test_fetch_cancellations_mtd_returns_empty_on_api_error():
    svc = MagicMock()
    svc.spreadsheets().values().get().execute.side_effect = Exception("API error")
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations")
    assert result == {"count": 0, "entries": []}


def test_fetch_cancellations_mtd_all_months_when_month_none():
    rows = [
        HEADER,
        ["", "1/5", "Jan Customer", "6", "App", "", "$150", "", "$900", "", "", "", ""],
        ["", "3/12", "Mar Customer", "4", "Price", "", "$100", "", "$400", "", "", "", ""],
    ]
    svc = _mock_service(rows)
    result = fetch_cancellations_mtd(svc, "fake-id", "MONTHLY Cancellations", month=None)
    assert result["count"] == 2
