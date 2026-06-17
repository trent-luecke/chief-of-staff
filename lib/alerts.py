"""Operational alerts — Slack DM to the operator when a pipeline stage fails.

Centralizes ops alerting so failure sites just call ``send_ops_alert(text, user_id)``.
Non-fatal by contract: never raises, returns a bool so callers can log the outcome.
Only fires inside GitHub Actions (the cloud run) unless ``force=True``, so running
``python main.py`` locally never DMs the operator.
"""

import os
import sys

from lib.slack_post import open_dm, post_message


def send_ops_alert(text: str, slack_user_id: str, *, force: bool = False) -> bool:
    """DM the operator a Slack alert. Returns True if a message was sent.

    No-ops (returns False) outside GitHub Actions unless ``force=True``. Skips and
    returns False if the bot token or user id is missing. Never raises — Slack
    failures are logged to stderr so an alert failure can't crash the caller.
    """
    if not force and not os.environ.get("GITHUB_ACTIONS"):
        return False
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token or not slack_user_id:
        print(
            "WARNING: ops alert skipped — SLACK_BOT_TOKEN or slack_user_id missing",
            file=sys.stderr,
        )
        return False
    try:
        channel = open_dm(token, slack_user_id)
        post_message(token, channel, text)
        return True
    except Exception as e:
        print(f"WARNING: ops alert failed (non-fatal): {e}", file=sys.stderr)
        return False
