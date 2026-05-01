"""Notion bug tracker collector — fetches TeamBuildr OS bug tickets."""

import sys
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

DATABASE_ID = "29d24bca36d78065b255cbb693a776da"

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


@dataclass
class BugTicket:
    id: str
    title: str
    status: Optional[str]
    priority_level: Optional[str]
    technical_areas: list
    date_created: str
    last_updated: str
    date_completed: Optional[str]
    shortcut_url: Optional[str]
    days_open: int


def _get(props: dict, key: str, kind: str, fallback=None):
    block = props.get(key, {})
    if kind == "title":
        parts = block.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts) or fallback
    if kind == "select":
        return (block.get("select") or {}).get("name", fallback)
    if kind == "status":
        return (block.get("status") or {}).get("name", fallback)
    if kind == "multi_select":
        return [opt["name"] for opt in block.get("multi_select", [])]
    if kind == "created_time":
        ts = block.get("created_time", "")
        return ts[:10] if ts else fallback
    if kind == "last_edited_time":
        ts = block.get("last_edited_time", "")
        return ts[:10] if ts else fallback
    if kind == "date":
        return (block.get("date") or {}).get("start", fallback)
    if kind == "url":
        return block.get("url", fallback)
    return fallback


def _query_all(token: str, database_id: str) -> list:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    results = []
    cursor = None
    while True:
        body = {}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(url, headers=_headers(token), json=body)
        if resp.status_code != 200:
            print(f"Notion bug tracker API error {resp.status_code}: {resp.text}", file=sys.stderr)
            return []
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _parse_bug_row(row: dict) -> BugTicket:
    props = row.get("properties", {})
    date_created_str = _get(props, "Date Created", "created_time", "")
    date_completed_str = _get(props, "Date Completed", "date")

    today = date.today()
    days_open = 0
    if date_created_str:
        try:
            created = date.fromisoformat(date_created_str[:10])
            if date_completed_str:
                end = date.fromisoformat(date_completed_str[:10])
            else:
                end = today
            days_open = max(0, (end - created).days)
        except (ValueError, TypeError):
            pass

    return BugTicket(
        id=row["id"],
        title=_get(props, "Ticket Name", "title", ""),
        status=_get(props, "Status", "status"),
        priority_level=_get(props, "Priority Level", "select"),
        technical_areas=_get(props, "Technical Area of Issue", "multi_select") or [],
        date_created=date_created_str,
        last_updated=_get(props, "Last Update", "last_edited_time", ""),
        date_completed=date_completed_str,
        shortcut_url=_get(props, "Shortcut URL", "url"),
        days_open=days_open,
    )


def fetch_bugs(token: str) -> list:
    """Fetch all bug tickets from the Notion bug tracker. Returns empty list on error."""
    rows = _query_all(token, DATABASE_ID)
    return [_parse_bug_row(row) for row in rows]
