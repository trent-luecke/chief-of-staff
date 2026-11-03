# tests/test_checkins_sheet.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.checkins_sheet import read_accounts, read_responses, rows_to_records  # noqa: E402


class _FakeSheets:
    """Minimal stand-in for the Sheets v4 service: values().get(...).execute()."""

    def __init__(self, tabs):
        self.tabs, self.ranges = tabs, []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range):
        self.ranges.append((spreadsheetId, range))
        tab = range.split("!")[0].strip("'")
        self._out = {"values": self.tabs.get(tab, [])}
        return self

    def execute(self):
        return self._out


def test_rows_to_records_keys_by_header_and_pads_short_rows():
    rows = [["Account Name", "Join Date", "Email"], ["FSP", "5/4/2026"], ["", "", ""], ["Gem", "1/1/2024", "a@b.com"]]
    assert rows_to_records(rows) == [
        {"Account Name": "FSP", "Join Date": "5/4/2026", "Email": ""},
        {"Account Name": "Gem", "Join Date": "1/1/2024", "Email": "a@b.com"},
    ]


def test_read_accounts_returns_every_row_with_a_name():
    rows = [["Account Name", "Join Date", "POC", "Email"]] + [[f"Gym {i}", "1/1/2025", "Pat", f"g{i}@x.com"] for i in range(100)]
    svc = _FakeSheets({"Active Customers": rows})
    out = read_accounts(svc)
    assert len(out) == 100 and out[99]["Account Name"] == "Gym 99"
    assert svc.ranges[0][1].startswith("'Active Customers'!")


def test_read_responses_tags_each_row_with_its_version():
    head = ["Timestamp", "Facility/Gym Name", "How would you rate TeamBuildr OS overall? "]
    svc = _FakeSheets({
        "2-6 mo. Responses": [head, ["11/4/2026 9:00:00", "FSP", "8"]],
        "6-12 mo. Responses": [head],
        "12+ mo. Responses": [head, ["11/5/2026 10:00:00", "Gem", "4"]],
    })
    out = read_responses(svc)
    assert [(r["version"], r["Facility/Gym Name"]) for r in out] == [("Early", "FSP"), ("Mature", "Gem")]
