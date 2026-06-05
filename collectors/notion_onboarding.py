"""Notion onboarding tracker collector — syncs OS Customer Onboarding Tracker to cache."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests


DATABASE_ID = "d4904af6-77b0-4507-8655-353ae4eadbd2"

_HEADERS = lambda token: {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _get(props: dict, key: str, kind: str, fallback=None):
    block = props.get(key, {})
    if kind == "title":
        parts = block.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts) or fallback
    if kind == "select":
        return (block.get("select") or {}).get("name", fallback)
    if kind == "email":
        return block.get("email", fallback)
    if kind == "date":
        return (block.get("date") or {}).get("start", fallback)
    return fallback


def _query_all(token: str, database_id: str) -> list[dict]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    results = []
    cursor = None
    while True:
        body = {}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(url, headers=_HEADERS(token), json=body)
        if resp.status_code != 200:
            print(f"Notion API error {resp.status_code}: {resp.text}", file=sys.stderr)
            break
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _parse_row(row: dict) -> dict:
    props = row.get("properties", {})
    return {
        "page_id": row["id"],
        "customer_name": _get(props, "Customer Name", "title", ""),
        "customer_email": _get(props, "Customer Email", "email"),
        "status": _get(props, "Status", "select"),
        "current_phase": _get(props, "Current Phase", "select"),
        "sales_rep": _get(props, "Sales Rep", "select"),
        "start_date": _get(props, "Start Date", "date"),
        "target_go_live_date": _get(props, "Target Go-Live Date", "date"),
    }


def sync(token: str, cache_path: str) -> None:
    """Pull all onboarding records and write cache file."""
    rows = _query_all(token, DATABASE_ID)
    records = [_parse_row(row) for row in rows]

    out = {
        "synced_at": datetime.utcnow().isoformat() + "Z",
        "records": records,
    }
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(records)} onboarding records to {cache_path}")


if __name__ == "__main__":
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        print("NOTION_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    cache_path = sys.argv[1] if len(sys.argv) > 1 else "data/onboarding_cache.json"
    sync(token, cache_path)
