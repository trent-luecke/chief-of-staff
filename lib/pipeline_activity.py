"""Utilities for tracking outbound pipeline email contacts.

Shared between watcher.py (hourly local scan) and main.py (daily GHA scan).
"""

import os
import re
from datetime import date, datetime, timezone
from typing import Optional

import requests

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")

_CACHE_KEY = "pipeline_cache.json"
_ACTIVITY_KEY = "pipeline_email_activity.json"


def extract_email(header: str) -> str:
    """Pull bare email address out of a header like 'Name <email@x.com>'."""
    m = _EMAIL_RE.search(header)
    return m.group(0).lower() if m else header.lower()


def load_lead_email_index(storage) -> dict[str, str]:
    """Returns {email_lower: lead_name} for all non-closed/lost leads."""
    skip_statuses = {"Closed", "Lost"}
    data = storage.read_json(_CACHE_KEY, default={})
    return {
        r["email"].lower(): r["name"]
        for r in data.get("leads", [])
        if r.get("email") and r.get("status") not in skip_statuses
    }


def load_lead_page_index(storage) -> dict[str, str]:
    """Returns {email_lower: page_id} for all leads with a page_id."""
    data = storage.read_json(_CACHE_KEY, default={})
    return {
        r["email"].lower(): r["page_id"]
        for r in data.get("leads", [])
        if r.get("email") and r.get("page_id")
    }


def load_pipeline_activity(storage) -> dict:
    return storage.read_json(_ACTIVITY_KEY, default={"updated_at": None, "leads": {}})


def save_pipeline_activity(storage, data: dict) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    storage.write_json(_ACTIVITY_KEY, data)


def record_lead_contact(activity: dict, email: str, name: str, thread, direction: str = "inbound") -> bool:
    """Update activity record if this thread is more recent than what's stored. Returns True if updated."""
    thread_date = thread.last_message_date.date().isoformat() if thread.last_message_date else None
    if not thread_date:
        return False
    existing = activity["leads"].get(email, {})
    if existing.get("last_email_date", "") >= thread_date:
        return False
    activity["leads"][email] = {
        "name": name,
        "last_email_date": thread_date,
        "last_subject": thread.subject[:120],
        "direction": direction,
    }
    return True


def patch_pipeline_cache_last_contacted(storage, email: str, contact_date: str) -> None:
    """Updates last_contacted in the local pipeline cache for immediate brief accuracy."""
    data = storage.read_json(_CACHE_KEY)
    if data is None:
        return
    today = date.today()
    changed = False
    for lead in data.get("leads", []):
        if lead.get("email", "").lower() != email:
            continue
        existing = lead.get("last_contacted", "")
        if existing and existing >= contact_date:
            break
        lead["last_contacted"] = contact_date
        try:
            days = (today - date.fromisoformat(contact_date[:10])).days
        except (ValueError, TypeError):
            days = None
        lead["days_since_contact"] = days
        lead["stale"] = bool(days is not None and days >= 14)
        changed = True
        break
    if changed:
        storage.write_json(_CACHE_KEY, data)


def update_notion_last_contacted(page_id: str, contact_date: str) -> bool:
    """Patches the Last Contacted date on a Notion page. Returns True on success."""
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        return False
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    body = {"properties": {"Last Contacted": {"date": {"start": contact_date}}}}
    try:
        resp = requests.patch(url, headers=headers, json=body, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def reconcile_activity_to_notion(storage) -> int:
    cache = storage.read_json(_CACHE_KEY)
    if cache is None:
        return 0

    activity = load_pipeline_activity(storage)
    activity_leads = activity.get("leads", {})
    page_index = load_lead_page_index(storage)
    updated = 0

    for lead in cache.get("leads", []):
        email = lead.get("email", "").lower()
        cache_date = lead.get("last_contacted") or ""
        activity_record = activity_leads.get(email, {})
        activity_date = activity_record.get("last_email_date", "")
        if not activity_date or activity_date <= cache_date:
            continue
        page_id = page_index.get(email)
        if not page_id:
            continue
        ok = update_notion_last_contacted(page_id, activity_date)
        if ok:
            patch_pipeline_cache_last_contacted(storage, email, activity_date)
            updated += 1

    return updated
