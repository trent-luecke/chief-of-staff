from dataclasses import dataclass
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


@dataclass
class SlackMessage:
    channel_id: str
    channel_name: str
    text: str
    user: str
    ts: str
    thread_ts: str
    reply_count: int


def fetch_channel_messages(
    token: str,
    channel_id: str,
    since_hours: int = 1,
    channel_name: str = "",
) -> list[SlackMessage]:
    client = WebClient(token=token)
    oldest = str((datetime.now() - timedelta(hours=since_hours)).timestamp())
    try:
        result = client.conversations_history(channel=channel_id, oldest=oldest, limit=200)
    except SlackApiError:
        return []

    messages = []
    for msg in result.get("messages", []):
        if msg.get("subtype") in ("bot_message", "channel_join", "channel_leave"):
            continue
        if not msg.get("text"):
            continue
        messages.append(SlackMessage(
            channel_id=channel_id,
            channel_name=channel_name,
            text=msg["text"],
            user=msg.get("user", ""),
            ts=msg["ts"],
            thread_ts=msg.get("thread_ts", msg["ts"]),
            reply_count=msg.get("reply_count", 0),
        ))
    return messages


def resolve_channel_ids(token: str, channel_names: list[str]) -> dict[str, str]:
    client = WebClient(token=token)
    name_set = {n.lower() for n in channel_names}
    result = {}
    try:
        response = client.conversations_list(types="public_channel,private_channel", limit=200)
        for ch in response.get("channels", []):
            if ch["name"].lower() in name_set:
                result[ch["name"]] = ch["id"]
    except SlackApiError:
        pass
    return result
