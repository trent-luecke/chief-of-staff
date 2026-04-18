import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PersonalEmail:
    id: str
    subject: str
    sender: str
    snippet: str
    date: Optional[datetime]


def _sender_email(from_header: str) -> str:
    if "<" in from_header:
        return from_header.split("<")[1].strip().rstrip(">").lower()
    return from_header.strip().lower()


def _run_gws(cmd: list[str]) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print("WARNING: gws not found in PATH — personal gmail fetch skipped.", flush=True)
        return {}
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def fetch_personal_emails(
    profile: str,
    allowed_senders: list[str],
    allowed_domains: list[str],
    max_results: int = 20,
) -> list[PersonalEmail]:
    allowed_senders_lower = {s.lower() for s in allowed_senders}
    allowed_domains_lower = {d.lower() for d in allowed_domains}

    list_params = json.dumps({"userId": "me", "q": "is:unread -in:sent", "maxResults": max_results})
    list_data = _run_gws([
        "gws", "--profile", profile, "gmail", "users", "threads", "list",
        "--params", list_params,
    ])

    emails = []
    for t in list_data.get("threads", []):
        thread_params = json.dumps({
            "userId": "me", "id": t["id"], "format": "metadata",
            "metadataHeaders": ["Subject", "From"],
        })
        thread_data = _run_gws([
            "gws", "--profile", profile, "gmail", "users", "threads", "get",
            "--params", thread_params,
        ])
        if not thread_data:
            continue

        messages = thread_data.get("messages", [])
        if not messages:
            continue

        last_msg = messages[-1]
        headers = last_msg.get("payload", {}).get("headers", [])

        def get_header(name: str) -> str:
            return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")

        sender_raw = get_header("From")
        sender_email = _sender_email(sender_raw)
        sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""

        if sender_email not in allowed_senders_lower and sender_domain not in allowed_domains_lower:
            continue

        internal_date = last_msg.get("internalDate")
        date = datetime.fromtimestamp(int(internal_date) / 1000) if internal_date else None

        emails.append(PersonalEmail(
            id=t["id"],
            subject=get_header("Subject") or "(no subject)",
            sender=sender_email,
            snippet=t.get("snippet", ""),
            date=date,
        ))
    return emails
