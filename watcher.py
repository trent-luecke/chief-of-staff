#!/usr/bin/env python3
"""Hourly watcher: processes all email since last run, routes to pipeline activity and issue log."""

import json
import math
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from collectors.slack import fetch_channel_messages, resolve_channel_ids, SlackMessage
from collectors.gmail import fetch_threads_needing_attention, filter_automated_threads, EmailThread
from processors.issues import add_or_update_issue, auto_resolve_issues
from lib.pipeline_activity import (
    extract_email as _extract_email,
    load_lead_email_index,
    load_lead_page_index,
    load_pipeline_activity,
    save_pipeline_activity,
    record_lead_contact,
    patch_pipeline_cache_last_contacted,
    update_notion_last_contacted,
)


FLAREUP_KEYWORDS = {
    "down", "outage", "broken", "error", "bug", "slow", "crash",
    "not working", "issue", "problem", "failing", "failed", "timeout",
    "unreachable", "complaint", "can't log in", "can't access",
}


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Last-run tracking
# ---------------------------------------------------------------------------

_WATCHER_STATE_KEY = "watcher_state.json"


def load_last_run(storage) -> datetime | None:
    data = storage.read_json(_WATCHER_STATE_KEY)
    if data is None:
        return None
    try:
        ts = data.get("last_run")
        if ts:
            return datetime.fromisoformat(ts)
    except ValueError:
        pass
    return None


def save_last_run(storage) -> None:
    storage.write_json(_WATCHER_STATE_KEY, {"last_run": datetime.now(timezone.utc).isoformat()})


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
    from lib.storage import build_storage
    storage = build_storage(config)
    pipeline_cfg = config.get("pipeline", {})

    # --- Determine lookback window ---
    last_run = load_last_run(storage)
    if last_run:
        hours_since = math.ceil((datetime.now(timezone.utc) - last_run).total_seconds() / 3600)
        lookback_hours = max(hours_since + 1, 2)  # +1 buffer to avoid gaps
    else:
        lookback_hours = 24
    gmail_query = f"is:unread newer_than:{lookback_hours}h"

    # --- Load pipeline lead index ---
    lead_index = load_lead_email_index(storage) if pipeline_cfg.get("enabled") else {}
    activity = load_pipeline_activity(storage)
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
                storage,
                source="gmail",
                source_ref=thread.id,
                channel="gmail",
                title=thread.subject[:120],
            )
            print(f"   Flare-up flagged: {thread.subject[:60]}")

    # --- Sent mail scan (outbound pipeline tracking) ---
    if lead_index:
        page_index = load_lead_page_index(storage)
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
                    patch_pipeline_cache_last_contacted(storage, recipient_email, contact_date)
                    # Write back to Notion (non-fatal)
                    page_id = page_index.get(recipient_email)
                    if page_id:
                        ok = update_notion_last_contacted(page_id, contact_date)
                        print(f"   Notion updated for {lead_name}: {ok}")
                    else:
                        print(f"   WARNING: no page_id for {lead_name} — run pipeline sync to pick up page IDs")
                    pipeline_updated = True

    if pipeline_updated:
        save_pipeline_activity(storage, activity)

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
                    storage,
                    source="slack",
                    source_ref=f"{channel_id}:{msg.thread_ts}",
                    channel=channel_name,
                    title=title,
                )
    else:
        print("  SLACK_BOT_TOKEN not set — skipping Slack scan.")

    # --- Cleanup and state ---
    print("🔄 Auto-resolving stale issues...")
    auto_resolve_issues(storage, resolve_after_days=config.get("issue_auto_resolve_days", 3))
    save_last_run(storage)
    print("✅ Watcher run complete.")


if __name__ == "__main__":
    run()
