from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from lib.google_auth import build_gmail_service


@dataclass
class EmailThread:
    id: str
    subject: str
    last_sender: str
    snippet: str
    last_message_date: Optional[datetime]
    needs_reply: bool = True
    label: str = "unread"
    last_recipient: str = ""


def _build_service(user_email: str):
    return build_gmail_service(user_email)


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
    recipient = _get_header(headers, "To")
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
        last_recipient=recipient,
    )


def fetch_threads_needing_attention(
    user_email: str,
    max_results: int = 15,
    query: str = "is:unread OR is:starred -in:sent",
) -> list[EmailThread]:
    try:
        service = _build_service(user_email)
        list_data = service.users().threads().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
    except Exception as e:
        print(f"WARNING: Gmail fetch failed: {e}", flush=True)
        return []

    threads = []
    for t in list_data.get("threads", []):
        try:
            thread_data = service.users().threads().get(
                userId="me",
                id=t["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            ).execute()
        except Exception:
            continue
        thread_data.setdefault("snippet", t.get("snippet", ""))
        parsed = _parse_thread(thread_data, user_email)
        if parsed:
            threads.append(parsed)
    return threads
