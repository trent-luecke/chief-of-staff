from lib.sales_sheet import _split_sections, fetch_sale_rows

HEADER = ["Date", "", "", "Total Sale", "Customer Name", "Customer Email", "Salesperson"]


def _data(date, total, name, email, rep):
    return [date, "", "", total, name, email, rep]


def test_split_sections_os_only_and_bundle():
    values = [
        HEADER,
        _data("8/1/2026", "$1,000", "Acme", "a@acme.com", "Luke Martin"),
        _data("8/2/2026", "$2,000", "Beta", "b@beta.com", "Ryan Allwein"),
        ["Bundle Sales"],
        _data("8/3/2026", "$5,000", "Gamma", "g@gamma.com", "Luke Martin"),
        ["Trent TB Sales"],
        _data("8/4/2026", "$9,999", "Ignore", "x@ignore.com", "Trent"),
    ]
    rows = _split_sections(values)
    assert [r["source"] for r in rows] == ["os_only", "os_only", "bundle"]
    assert rows[0]["customer_email"] == "a@acme.com"
    assert rows[2]["customer_name"] == "Gamma"
    assert all(r["customer_email"] != "x@ignore.com" for r in rows)  # below Trent TB stop


def test_split_sections_skips_blank_rows_and_handles_growth():
    values = [
        HEADER,
        _data("8/1/2026", "$1,000", "Acme", "a@acme.com", "Luke Martin"),
        ["", "", "", "", "", "", ""],
        _data("8/2/2026", "$2,000", "Beta", "b@beta.com", "Ryan Allwein"),
        ["Bundle Sales"],
        _data("8/3/2026", "$5,000", "Gamma", "g@gamma.com", "Luke Martin"),
    ]
    rows = _split_sections(values)
    assert len(rows) == 3
    assert [r["source"] for r in rows] == ["os_only", "os_only", "bundle"]


def test_split_sections_empty():
    assert _split_sections([]) == []


def test_split_sections_resolves_columns_by_header_name_not_position():
    # Columns deliberately reordered vs the usual layout.
    values = [
        ["Customer Email", "Salesperson", "Date", "Customer Name", "Total Sale"],
        ["a@acme.com", "Luke Martin", "8/1/2026", "Acme", "$1,000"],
    ]
    rows = _split_sections(values)
    assert rows[0]["customer_email"] == "a@acme.com"
    assert rows[0]["salesperson"] == "Luke Martin"
    assert rows[0]["date"] == "8/1/2026"
    assert rows[0]["customer_name"] == "Acme"
    assert rows[0]["total_sale"] == "$1,000"
    assert rows[0]["source"] == "os_only"


class _FakeService:
    def __init__(self, values):
        self._values = values

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, range):
        self.last_range = range
        return self

    def execute(self):
        return {"values": self._values}


def test_fetch_sale_rows_resolves_current_month_tab():
    cfg = {"meeting_prep": {"sheets": {"sales_spreadsheet_id": "SID"}}}
    svc = _FakeService([HEADER, _data("8/1/2026", "$1,000", "Acme", "a@acme.com", "Luke")])
    rows = fetch_sale_rows(cfg, "2026-08-20", service=svc)
    assert svc.last_range.startswith("'August 2026'!")
    assert rows[0]["customer_email"] == "a@acme.com"


def test_fetch_sale_rows_missing_id_returns_empty():
    assert fetch_sale_rows({}, "2026-08-20", service=object()) == []


def test_fetch_sale_rows_api_error_returns_empty():
    class _Boom:
        def spreadsheets(self):
            raise RuntimeError("no such tab")
    cfg = {"meeting_prep": {"sheets": {"sales_spreadsheet_id": "SID"}}}
    assert fetch_sale_rows(cfg, "2026-08-20", service=_Boom()) == []
