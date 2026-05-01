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
