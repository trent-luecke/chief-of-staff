"""User-facing push notifications — one-way Slack DM to the operator.

This is the delivery channel for pre-meeting preps, the weekly digest, reminders,
and observation-resolution pings (migrated off Telegram). Unlike lib/alerts (which
is gated to GitHub Actions and meant for ops failures), notify_user is the real
delivery path, so it sends whenever a Slack token is present — mirroring the old
lib.telegram.send_message behavior. Non-fatal by contract: never raises.
"""

import os
import sys

from lib.slack_post import open_dm, post_message


def _resolve_user_id(config: dict) -> str:
    notif = config.get("notifications", {})
    if notif.get("slack_user_id"):
        return notif["slack_user_id"]
    return config.get("ops_alerts", {}).get("slack_user_id", "")


def notify_user(text: str, config: dict) -> bool:
    """DM the operator a Slack notification. Returns True if a message was sent.

    Returns False (and logs a warning) if SLACK_BOT_TOKEN or the recipient user id
    is missing, or if the Slack call fails. Never raises.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    user_id = _resolve_user_id(config)
    if not token or not user_id:
        print(
            "WARNING: notify_user skipped — SLACK_BOT_TOKEN or slack_user_id missing",
            file=sys.stderr,
        )
        return False
    try:
        channel = open_dm(token, user_id)
        post_message(token, channel, text)
        return True
    except Exception as e:
        print(f"WARNING: notify_user failed (non-fatal): {e}", file=sys.stderr)
        return False
