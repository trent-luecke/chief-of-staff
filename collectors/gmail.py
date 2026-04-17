import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class EmailThread:
    id: str
    subject: str
    last_sender: str
    snippet: str
    last_message_date: Optional[datetime]
    needs_reply: bool = True
    label: str = "unread"


def _run_gws(*cmd_parts: str, params: dict, profile: Optional[str] = None) -> dict:
    cmd = ["gws"] + list(cmd_parts) + ["--params", json.dumps(params)]
    if profile:
        cmd = ["gws", "--profile", profile] + list(cmd_parts) + ["--params", json.dumps(params)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _parse_thread(thread_data: dict, user_email: str) -> Optional[EmailThread]:
    messages = thread_data.get("messages", [])
    if not messages:
        return None
    last_msg = messages[-1]
    headers = last_msg.get("payload", {}).get("headers", [])
    subject = _get_header(headers, "Subject") or "(no subject)"
    sender = _get_header(headers, "From")
    internal_date = last_msg.get("internalDate")
    date = None
    if internal_date:
        try:
            date = datetime.fromtimestamp(int(internal_date) / 1000)
        except (ValueError, OSError):
            pass
    needs_reply = user_email.lower() not in sender.lower()
    return EmailThread(
        id=thread_data["id"],
        subject=subject,
        last_sender=sender,
        snippet=thread_data.get("snippet", ""),
        last_message_date=date,
        needs_reply=needs_reply,
    )


def fetch_threads_needing_attention(
    user_email: str,
    max_results: int = 15,
    profile: Optional[str] = None,
    query: str = "is:unread OR is:starred -in:sent",
) -> list[EmailThread]:
    list_data = _run_gws(
        "gmail", "users", "threads", "list",
        params={"userId": "me", "q": query, "maxResults": max_results},
        profile=profile,
    )
    if not list_data:
        return []

    threads = []
    for t in list_data.get("threads", []):
        thread_data = _run_gws(
            "gmail", "users", "threads", "get",
            params={
                "userId": "me",
                "id": t["id"],
                "format": "metadata",
                "metadataHeaders": ["Subject", "From", "Date"],
            },
            profile=profile,
        )
        if not thread_data:
            continue
        thread_data.setdefault("snippet", t.get("snippet", ""))
        parsed = _parse_thread(thread_data, user_email)
        if parsed:
            threads.append(parsed)
    return threads
