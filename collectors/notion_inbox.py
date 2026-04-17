import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class InboxItem:
    id: str
    name: str
    item_type: str
    urgency: str
    category: str
    source: str
    created_time: str


def _extract_select(props: dict, key: str) -> str:
    return (props.get(key, {}).get("select") or {}).get("name", "")


def _extract_title(props: dict, key: str) -> str:
    parts = props.get(key, {}).get("title", [])
    return "".join(p.get("plain_text", "") for p in parts)


def fetch_inbox_items(
    token: str,
    database_id: str,
    filter_statuses: list[str],
) -> list[InboxItem]:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json={})
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    items = []
    for result in response.json().get("results", []):
        props = result.get("properties", {})
        items.append(
            InboxItem(
                id=result["id"],
                name=_extract_title(props, "Name"),
                item_type=_extract_select(props, "Type"),
                urgency=_extract_select(props, "Urgency"),
                category=_extract_select(props, "Category"),
                source=_extract_select(props, "Source"),
                created_time=result.get("created_time", ""),
            )
        )
    return items
