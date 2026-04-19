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


@dataclass
class SlackDM:
    user_id: str
    display_name: str
    email: str
    messages: list[str]
    channel_id: str


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


def fetch_dm_messages(token: str, since_hours: int = 24) -> list["SlackDM"]:
    client = WebClient(token=token)
    try:
        result = client.conversations_list(types="im", limit=200)
    except SlackApiError:
        return []

    dms = []
    for ch in result.get("channels", []):
        if not ch.get("is_open"):
            continue
        user_id = ch.get("user")
        if not user_id:
            continue

        messages = fetch_channel_messages(token, ch["id"], since_hours=since_hours)
        if not messages:
            continue

        try:
            user_info = client.users_info(user=user_id)
            profile = user_info["user"]["profile"]
            display_name = profile.get("real_name") or profile.get("display_name", user_id)
            email = profile.get("email", "")
        except SlackApiError:
            display_name = user_id
            email = ""

        dms.append(SlackDM(
            user_id=user_id,
            display_name=display_name,
            email=email,
            messages=[m.text for m in messages],
            channel_id=ch["id"],
        ))

    return dms
