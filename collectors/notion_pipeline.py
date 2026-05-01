"""Notion pipeline collector — syncs pipeline DB to data/pipeline_cache.json."""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import requests


DATABASE_ID = "22224bca36d7803aa7eaf531fae63fea"

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
    if kind == "rich_text":
        parts = block.get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts) or fallback
    if kind == "select":
        return (block.get("select") or {}).get("name", fallback)
    if kind == "status":
        return (block.get("status") or {}).get("name", fallback)
    if kind == "email":
        return block.get("email", fallback)
    if kind == "number":
        return block.get("number", fallback)
    if kind == "date":
        return (block.get("date") or {}).get("start", fallback)
    if kind == "checkbox":
        return bool(block.get("checkbox", False))
    if kind == "people":
        people = block.get("people", [])
        if not people:
            return fallback
        person = people[0]
        return person.get("name", fallback)
    if kind == "formula":
        f = block.get("formula", {})
        return f.get("string") or f.get("number") or fallback
    return fallback


def _query_all(token: str, database_id: str, filter_body: dict | None = None) -> list[dict]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    results = []
    cursor = None
    while True:
        body = {}
        if filter_body:
            body["filter"] = filter_body
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


def inspect(token: str) -> None:
    """Print raw property schema — run to discover column names."""
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
    resp = requests.get(url, headers=_HEADERS(token))
    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text}")
        return
    db = resp.json()
    print(f"\nDatabase: {db.get('title', [{}])[0].get('plain_text', '?')}\n")
    for name, prop in db.get("properties", {}).items():
        print(f"  {prop['type']:15s} | {name!r}")

    # Also show first row's values
    rows = _query_all(token, DATABASE_ID)
    if rows:
        print(f"\nFirst row properties:\n")
        props = rows[0].get("properties", {})
        for name, block in props.items():
            kind = block.get("type", "?")
            raw = block.get(kind)
            # Truncate for readability
            raw_str = str(raw)[:80] if raw else "null"
            print(f"  {name!r}: [{kind}] {raw_str}")


def sync(token: str, cache_path: str) -> None:
    """Pull all pipeline leads and write cache file."""
    rows = _query_all(token, DATABASE_ID)
    leads = []
    for row in rows:
        props = row.get("properties", {})

        name = _get(props, "Name", "title", "")
        contact = _get(props, "Contact", "rich_text", "")
        email = _get(props, "Email", "email", "")
        status = _get(props, "Status", "status", "")
        priority = _get(props, "Priority", "select")
        last_contacted = _get(props, "Last Contacted", "date")
        estimated_value = _get(props, "Estimated Value", "number")
        source = _get(props, "Source", "select")
        stale_checkbox = _get(props, "Stale Lead", "checkbox", False)

        days_since = None
        if last_contacted:
            try:
                days_since = (date.today() - date.fromisoformat(last_contacted[:10])).days
            except (ValueError, TypeError):
                pass
        stale = stale_checkbox or (days_since is not None and days_since >= 14)

        leads.append({
            "page_id": row["id"],
            "name": name,
            "contact": contact,
            "email": email,
            "status": status,
            "priority": priority,
            "last_contacted": last_contacted,
            "days_since_contact": days_since,
            "estimated_value": estimated_value,
            "source": source,
            "stale": stale,
        })

    out = {
        "synced_at": datetime.utcnow().isoformat() + "Z",
        "leads": leads,
    }
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(leads)} leads to {cache_path}")


if __name__ == "__main__":
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        print("NOTION_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "--inspect":
        inspect(token)
    else:
        cache_path = sys.argv[1] if len(sys.argv) > 1 else "data/pipeline_cache.json"
        sync(token, cache_path)
