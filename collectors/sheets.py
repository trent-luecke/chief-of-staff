"""Google Sheets data fetcher for Dept Heads KPI context."""

import re
from datetime import date, datetime


def month_label(offset: int = 0) -> str:
    """Return a tab name like 'April 2026'. offset=-1 gives prior month."""
    today = date.today()
    month = today.month + offset
    year = today.year
    if month <= 0:
        month += 12
        year -= 1
    elif month > 12:
        month -= 12
        year += 1
    return datetime(year, month, 1).strftime("%B %Y")


def _parse_dollar(val: str) -> float:
    try:
        return float(re.sub(r"[$,]", "", val.strip()))
    except (ValueError, AttributeError):
        return 0.0


def fetch_sales_mtd(service, spreadsheet_id: str, tab_label: str) -> dict:
    """Fetch OS sales entries from the named monthly tab."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_label}'!A1:F200",
        ).execute()
    except Exception:
        return {"count": 0, "revenue": 0.0, "entries": []}

    rows = result.get("values", [])
    entries = []
    for row in rows:
        if not row:
            continue
        date_val = row[0]
        if not re.match(r"\d+/\d+", str(date_val)):
            continue
        total = _parse_dollar(row[3]) if len(row) > 3 else 0.0
        entries.append({
            "date": date_val,
            "total": total,
            "customer": row[4] if len(row) > 4 else "",
            "salesperson": row[5] if len(row) > 5 else "",
            "sale_type": row[2] if len(row) > 2 else "",
        })

    revenue = sum(e["total"] for e in entries)
    return {"count": len(entries), "revenue": revenue, "entries": entries}


def fetch_demos_mtd(service, spreadsheet_id: str, tab_label: str) -> dict:
    """Fetch demo entries from the named monthly tab."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_label}'!A1:E200",
        ).execute()
    except Exception:
        return {"count": 0, "entries": []}

    rows = result.get("values", [])
    entries = []
    for row in rows[1:]:  # skip header row
        if not row or not row[0]:
            continue
        entries.append({
            "date": row[1] if len(row) > 1 else "",
            "title": row[2] if len(row) > 2 else "",
            "salesperson": row[3] if len(row) > 3 else "",
        })

    return {"count": len(entries), "entries": entries}


def fetch_cancellations_mtd(
    service, spreadsheet_id: str, tab_name: str, month: int | None = -1
) -> dict:
    """Fetch cancellation entries from the MONTHLY Cancellations tab.

    Args:
        month: Filter to this month number (1-12). Pass None to return all rows.
               Defaults to -1 which resolves to the current month.
    """
    if month == -1:
        month = date.today().month

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1:N300",
        ).execute()
    except Exception:
        return {"count": 0, "entries": []}

    rows = result.get("values", [])
    entries = []

    for row in rows[1:]:  # skip header
        date_str = row[1].strip() if len(row) > 1 else ""
        if not date_str or "/" not in date_str:
            continue
        try:
            row_month = int(date_str.split("/")[0])
        except (ValueError, IndexError):
            continue
        if month is not None and row_month != month:
            continue
        entries.append({
            "date": date_str,
            "account_name": row[2] if len(row) > 2 else "",
            "months_paid": row[3] if len(row) > 3 else "",
            "reason": row[4] if len(row) > 4 else "",
            "base_plan_type": row[5] if len(row) > 5 else "",
            "base_plan": row[6] if len(row) > 6 else "",
            "monetary_value": row[8] if len(row) > 8 else "",
            "customer_note": row[9] if len(row) > 9 else "",
            "customer_returned": row[10] if len(row) > 10 else "",
            "lifetime_value": row[12] if len(row) > 12 else "",
        })

    return {"count": len(entries), "entries": entries}
