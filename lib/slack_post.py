"""Slack thread utilities — post messages and fetch thread roots."""

from __future__ import annotations
import sys
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def post_to_thread(bot_token: str, channel_id: str, thread_ts: str, text: str) -> str | None:
    """Post a message to a Slack thread. Returns the message ts, or None on failure."""
    client = WebClient(token=bot_token)
    try:
        resp = client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
        return resp.data.get("ts")
    except SlackApiError as e:
        print(f"WARNING: Slack post failed: {e.response['error']}", file=sys.stderr)
        return None


def get_thread_root_text(bot_token: str, channel_id: str, thread_ts: str) -> str:
    """Return a searchable text blob for the root message of a Slack thread.

    Rich app messages (like Avoma posts) put content in blocks/attachments rather
    than the plain text field. We serialize the full message object so that URLs
    and UUIDs buried in blocks are still findable by regex.
    """
    import json as _json
    client = WebClient(token=bot_token)
    try:
        resp = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=1)
        messages = resp.data.get("messages", [])
        if not messages:
            return ""
        return _json.dumps(messages[0])
    except SlackApiError:
        return ""
