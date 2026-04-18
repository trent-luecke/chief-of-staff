#!/usr/bin/env python3
"""Hourly watcher: scans Slack channels and Gmail for flare-ups, updates issue log."""

import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from collectors.slack import fetch_channel_messages, resolve_channel_ids, SlackMessage
from collectors.gmail import fetch_threads_needing_attention, EmailThread
from processors.issues import add_or_update_issue, auto_resolve_issues

FLAREUP_KEYWORDS = {
    "down", "outage", "broken", "error", "bug", "slow", "crash",
    "not working", "issue", "problem", "failing", "failed", "timeout",
    "unreachable", "complaint", "can't log in", "can't access",
}


def detect_flareups_from_gmail(threads: list[EmailThread]) -> list[EmailThread]:
    flareups = []
    for t in threads:
        text = (t.subject + " " + t.snippet).lower()
        if any(kw in text for kw in FLAREUP_KEYWORDS):
            flareups.append(t)
    return flareups


def is_business_hours() -> bool:
    now = datetime.now()
    return 7 <= now.hour < 16


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def run() -> None:
    if not is_business_hours():
        print("Outside business hours — skipping watcher run.")
        return

    config = load_config()
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    issues_file = config["issues_file"]

    print("🔍 Scanning Slack channels...")
    if slack_token:
        channel_map = resolve_channel_ids(slack_token, config["slack_channels"])
        for channel_name, channel_id in channel_map.items():
            messages = fetch_channel_messages(
                slack_token, channel_id, since_hours=1, channel_name=channel_name
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

    print("📧 Scanning Gmail for flare-up keywords...")
    gmail_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=20,
        profile=config.get("gmail_profile"),
        query="is:unread subject:(down OR outage OR broken OR error OR bug)",
    )
    for thread in detect_flareups_from_gmail(gmail_threads):
        add_or_update_issue(
            issues_file=issues_file,
            source="gmail",
            source_ref=thread.id,
            channel="gmail",
            title=thread.subject[:120],
        )

    print("🔄 Auto-resolving stale issues...")
    auto_resolve_issues(issues_file, resolve_after_days=config.get("issue_auto_resolve_days", 3))

    print("✅ Watcher run complete.")


if __name__ == "__main__":
    run()
