#!/usr/bin/env python3
"""Hourly watcher: processes all email since last run, routes to pipeline activity and issue log."""

import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from dotenv import load_dotenv

load_dotenv()

from collectors.slack import fetch_channel_messages, resolve_channel_ids, SlackMessage
from collectors.gmail import fetch_threads_needing_attention, filter_automated_threads, EmailThread
from processors.issues import add_or_update_issue, auto_resolve_issues


FLAREUP_KEYWORDS = {
    "down", "outage", "broken", "error", "bug", "slow", "crash",
    "not working", "issue", "problem", "failing", "failed", "timeout",
    "unreachable", "complaint", "can't log in", "can't access",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")


def _extract_email(from_header: str) -> str:
    """Pull bare email address out of a From header like 'Name <email@x.com>'."""
    m = _EMAIL_RE.search(from_header)
    return m.group(0).lower() if m else from_header.lower()


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Last-run tracking
# ---------------------------------------------------------------------------

def load_last_run(state_path: str) -> datetime | None:
    try:
        with open(state_path) as f:
            ts = json.load(f).get("last_run")
        if ts:
            return datetime.fromisoformat(ts)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return None


def save_last_run(state_path: str) -> None:
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump({"last_run": datetime.now(timezone.utc).isoformat()}, f)


# ---------------------------------------------------------------------------
# Pipeline lead index
# ---------------------------------------------------------------------------

def load_lead_email_index(cache_path: str) -> dict[str, str]:
    """Returns {email_lower: lead_name} for all non-closed/lost leads."""
    skip_statuses = {"Closed", "Lost"}
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        r["email"].lower(): r["name"]
        for r in data.get("leads", [])
        if r.get("email") and r.get("status") not in skip_statuses
    }


def load_lead_page_index(cache_path: str) -> dict[str, str]:
    """Returns {email_lower: page_id} for all leads that have a page_id."""
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {
        r["email"].lower(): r["page_id"]
        for r in data.get("leads", [])
        if r.get("email") and r.get("page_id")
    }


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


def patch_pipeline_cache_last_contacted(cache_path: str, email: str, contact_date: str) -> None:
    """Updates last_contacted in the local pipeline cache for immediate brief accuracy."""
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
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
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Pipeline activity file
# ---------------------------------------------------------------------------

def load_pipeline_activity(activity_path: str) -> dict:
    try:
        with open(activity_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"updated_at": None, "leads": {}}


def save_pipeline_activity(activity_path: str, data: dict) -> None:
    Path(activity_path).parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(activity_path, "w") as f:
        json.dump(data, f, indent=2)


def record_lead_contact(activity: dict, email: str, name: str, thread: EmailThread, direction: str = "inbound") -> bool:
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


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_thread(
    thread: EmailThread,
    lead_index: dict[str, str],
) -> tuple[bool, bool]:
    """Returns (is_lead_contact, is_flareup)."""
    sender_email = _extract_email(thread.last_sender)
    is_lead = sender_email in lead_index
    text = (thread.subject + " " + thread.snippet).lower()
    is_flareup = any(kw in text for kw in FLAREUP_KEYWORDS)
    return is_lead, is_flareup


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def is_active_hours(start_hour: int = 7, end_hour: int = 20) -> bool:
    return start_hour <= datetime.now().hour < end_hour


def run() -> None:
    if not is_active_hours():
        print("Outside active hours — skipping watcher run.")
        return

    config = load_config()
    pipeline_cfg = config.get("pipeline", {})
    issues_file = config["issues_file"]
    cache_path = pipeline_cfg.get("cache_path", "data/pipeline_cache.json")
    activity_path = "data/pipeline_email_activity.json"
    state_path = "data/watcher_state.json"

    # --- Determine lookback window ---
    last_run = load_last_run(state_path)
    if last_run:
        hours_since = math.ceil((datetime.now(timezone.utc) - last_run).total_seconds() / 3600)
        lookback_hours = max(hours_since + 1, 2)  # +1 buffer to avoid gaps
    else:
        lookback_hours = 24
    gmail_query = f"is:unread newer_than:{lookback_hours}h"

    # --- Load pipeline lead index ---
    lead_index = load_lead_email_index(cache_path) if pipeline_cfg.get("enabled") else {}
    activity = load_pipeline_activity(activity_path)
    pipeline_updated = False

    automation_filters = config.get("email_automation_filters", {})

    # --- Gmail scan ---
    # Two passes: all recent threads for pipeline matching, unread-only for flare-ups.
    # Split because leads are expected to be read; unread filter would miss them.
    all_query = f"newer_than:{lookback_hours}h -in:sent"
    unread_query = f"is:unread newer_than:{lookback_hours}h -category:promotions -category:updates -category:social -category:forums"

    print(f"📧 Scanning Gmail (last {lookback_hours}h)...")
    all_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=50,
        query=all_query,
    )
    unread_threads = filter_automated_threads(
        fetch_threads_needing_attention(
            user_email=config["email"],
            max_results=50,
            query=unread_query,
        ),
        automation_filters,
    )
    unread_ids = {t.id for t in unread_threads}
    print(f"   {len(all_threads)} total thread(s), {len(unread_ids)} unread")

    for thread in all_threads:
        is_lead, is_flareup = classify_thread(thread, lead_index)
        is_flareup = is_flareup and thread.id in unread_ids

        if is_lead:
            sender_email = _extract_email(thread.last_sender)
            lead_name = lead_index[sender_email]
            updated = record_lead_contact(activity, sender_email, lead_name, thread)
            if updated:
                print(f"   Pipeline contact: {lead_name} — {thread.subject[:60]}")
                pipeline_updated = True

        if is_flareup:
            add_or_update_issue(
                issues_file=issues_file,
                source="gmail",
                source_ref=thread.id,
                channel="gmail",
                title=thread.subject[:120],
            )
            print(f"   Flare-up flagged: {thread.subject[:60]}")

    # --- Sent mail scan (outbound pipeline tracking) ---
    if lead_index:
        page_index = load_lead_page_index(cache_path)
        sent_query = f"in:sent newer_than:{lookback_hours}h"
        print(f"📤 Scanning sent mail for outbound pipeline contacts...")
        sent_threads = fetch_threads_needing_attention(
            user_email=config["email"],
            max_results=50,
            query=sent_query,
        )
        for thread in sent_threads:
            recipient_email = _extract_email(thread.last_recipient)
            if recipient_email in lead_index:
                lead_name = lead_index[recipient_email]
                updated = record_lead_contact(activity, recipient_email, lead_name, thread, direction="outbound")
                if updated:
                    contact_date = thread.last_message_date.date().isoformat()
                    print(f"   Outbound contact: {lead_name} — {thread.subject[:60]}")
                    # Patch local cache immediately so next brief sees updated date
                    patch_pipeline_cache_last_contacted(cache_path, recipient_email, contact_date)
                    # Write back to Notion (non-fatal)
                    page_id = page_index.get(recipient_email)
                    if page_id:
                        ok = update_notion_last_contacted(page_id, contact_date)
                        print(f"   Notion updated for {lead_name}: {ok}")
                    else:
                        print(f"   WARNING: no page_id for {lead_name} — run pipeline sync to pick up page IDs")
                    pipeline_updated = True

    if pipeline_updated:
        save_pipeline_activity(activity_path, activity)

    # --- Slack scan ---
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    print("🔍 Scanning Slack channels...")
    if slack_token:
        channel_map = resolve_channel_ids(slack_token, config["slack_channels"])
        for channel_name, channel_id in channel_map.items():
            messages = fetch_channel_messages(
                slack_token, channel_id, since_hours=lookback_hours, channel_name=channel_name
            )
            for msg in messages:
                title = msg.text[:120] + ("..." if len(msg.text) > 120 else "")
                add_or_update_issue(
                    issues_file=issues_file,
                    source="slack",
                    source_ref=f"{channel_id}:{msg.thread_ts}",
                    channel=channel_name,
                    title=title,
                )
    else:
        print("  SLACK_BOT_TOKEN not set — skipping Slack scan.")

    # --- Cleanup and state ---
    print("🔄 Auto-resolving stale issues...")
    auto_resolve_issues(issues_file, resolve_after_days=config.get("issue_auto_resolve_days", 3))
    save_last_run(state_path)
    print("✅ Watcher run complete.")


if __name__ == "__main__":
    run()
