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
    """Return the text of the root message of a Slack thread, or '' on failure."""
    client = WebClient(token=bot_token)
    try:
        resp = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=1)
        messages = resp.data.get("messages", [])
        return messages[0].get("text", "") if messages else ""
    except SlackApiError:
        return ""
