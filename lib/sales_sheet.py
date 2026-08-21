"""Read the current-month tab of the Sales Tracker sheet into raw sale rows.

Two in-scope sections delimited by label rows: OS-only (rows after the column
header, source="os_only") and bundle (after a "Bundle Sales" label,
source="bundle"). Everything at/after a "Trent TB Sales" label is ignored.
Column positions are resolved by header name, not letter.
"""
from __future__ import annotations

from datetime import date

_HEADER_FIELDS = {
    "date": "date",
    "total sale": "total_sale",
    "customer name": "customer_name",
    "customer email": "customer_email",
    "salesperson": "salesperson",
}
_BUNDLE_HEADER = "bundle sales"
_STOP_HEADER = "trent tb sales"


def _split_sections(values: list[list]) -> list[dict]:
    if not values:
        return []
    header = values[0]
    col_field: dict[int, str] = {}
    for idx, cell in enumerate(header):
        key = str(cell).strip().lower()
        if key in _HEADER_FIELDS:
            col_field[idx] = _HEADER_FIELDS[key]

    rows: list[dict] = []
    section = "os_only"
    for raw in values[1:]:
        joined = " ".join(str(c).strip().lower() for c in raw if str(c).strip())
        if _STOP_HEADER in joined:
            break
        if _BUNDLE_HEADER in joined:
            section = "bundle"
            continue
        rec = {
            field: (str(raw[idx]).strip() if idx < len(raw) and raw[idx] is not None else "")
            for idx, field in col_field.items()
        }
        if not rec.get("customer_email") and not rec.get("date"):
            continue  # blank / non-data row
        rec["source"] = section
        rows.append(rec)
    return rows


def fetch_sale_rows(config: dict, today: str, service=None) -> list[dict]:
    sid = (
        config.get("meeting_prep", {})
        .get("sheets", {})
        .get("sales_spreadsheet_id", "")
    )
    if not sid:
        return []
    tab = date.fromisoformat(today[:10]).strftime("%B %Y")
    try:
        if service is None:
            from lib.google_auth import build_sheets_service
            service = build_sheets_service()
        resp = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sid, range=f"'{tab}'!A1:G200")
            .execute()
        )
    except Exception as e:
        import sys
        print(f"⚠️  Sales sheet read failed (non-fatal): {e}", file=sys.stderr)
        return []
    return _split_sections(resp.get("values", []))
