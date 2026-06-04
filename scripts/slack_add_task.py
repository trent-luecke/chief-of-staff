#!/usr/bin/env python3
"""Add a task from a Slack slash command. Called by task_add.yml."""
import json
import os
import sys
import urllib.request
from pathlib import Path

import dateparser
from dateutil import parser as _du_parser

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import LocalStorage
from lib.tasks import add_task

TRENT_ID = "trent-luecke"


def parse_due_date(raw: str):
    """Parse natural language date to YYYY-MM-DD. Returns None if empty or unparseable."""
    if not raw or not raw.strip():
        return None
    result = dateparser.parse(
        raw,
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
    )
    if result is None:
        # Fall back to dateutil for relative phrases like "next monday" that
        # dateparser misses on some platforms.
        try:
            result = _du_parser.parse(raw, fuzzy=True, default=None)
        except Exception:
            return None
    if result is None:
        return None
    return result.strftime("%Y-%m-%d")


def fuzzy_match_all_persons(raw_name: str, registry_path: Path) -> list:
    """Return list of {id, canonical_name} for every person whose name/aliases match raw_name."""
    try:
        with open(registry_path) as f:
            registry = json.load(f)
    except Exception:
        return []
    needle = raw_name.lower()
    matches = []
    for person in registry.get("people", []):
        candidates = [person.get("canonical_name", "")] + person.get("aliases", [])
        if any(needle in c.lower() or c.lower() in needle for c in candidates if c):
            matches.append({"id": person["id"], "canonical_name": person.get("canonical_name", person["id"])})
    return matches


def resolve_owner_name(owner_id: str, registry_path: Path) -> str:
    """Return canonical_name for a person_id, or the id itself if not found."""
    try:
        with open(registry_path) as f:
            registry = json.load(f)
    except Exception:
        return owner_id
    for person in registry.get("people", []):
        if person.get("id") == owner_id:
            return person.get("canonical_name", owner_id)
    return owner_id


def format_confirmation(title: str, due_date, owner_name: str | None = None) -> str:
    parts = [f"Task added: {title}"]
    if owner_name:
        parts.append(f"owner: {owner_name}")
    if due_date:
        parts.append(f"due {due_date}")
    return " — ".join(parts)


def _post_json(response_url: str, payload: dict) -> None:
    if not response_url:
        return
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        response_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to post to Slack response_url: {e}", file=sys.stderr)


def post_to_slack(response_url: str, text: str) -> None:
    _post_json(response_url, {"response_type": "ephemeral", "text": text})


def _open_dm(user_id: str, bot_token: str) -> str | None:
    """Open a DM with user_id via conversations.open and return the channel ID."""
    data = json.dumps({"users": user_id}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/conversations.open",
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {bot_token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                return result["channel"]["id"]
            print(f"Warning: conversations.open failed: {result.get('error')}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: conversations.open error: {e}", file=sys.stderr)
    return None


def post_ambiguous_message(
    user_id: str, bot_token: str, raw_name: str, matches: list, title: str, due_date_raw: str
) -> None:
    """Open a DM with the user and post an interactive message with a button per candidate owner."""
    if not user_id or not bot_token:
        print("Warning: missing user_id or SLACK_BOT_TOKEN — cannot post interactive message", file=sys.stderr)
        return

    dm_channel = _open_dm(user_id, bot_token)
    if not dm_channel:
        return

    # Slack allows max 5 elements per actions block; reserve 1 for "Assign to me"
    capped = matches[:4]
    overflow_note = f"\n_Showing first 4 of {len(matches)} matches._" if len(matches) > 4 else ""

    buttons = []
    for person in capped:
        value = json.dumps({"title": title, "due_date_raw": due_date_raw, "owner_raw": person["canonical_name"]})
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": person["canonical_name"]},
            "action_id": "assign_owner",
            "value": value,
        })

    assign_to_me_value = json.dumps({"title": title, "due_date_raw": due_date_raw, "owner_raw": "Trent Luecke"})
    buttons.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Assign to me"},
        "action_id": "assign_owner",
        "value": assign_to_me_value,
    })

    payload = {
        "channel": dm_channel,
        "text": f"Multiple matches for '{raw_name}' — who did you mean?",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Multiple matches for *{raw_name}* — who did you mean?{overflow_note}",
                },
            },
            {
                "type": "actions",
                "elements": buttons,
            },
        ],
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {bot_token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                print(f"Warning: chat.postMessage failed: {result.get('error')}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: failed to post interactive message: {e}", file=sys.stderr)


def main():
    title = os.environ.get("TASK_TITLE", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "")
    due_date_raw = os.environ.get("DUE_DATE_RAW", "")
    owner_raw = os.environ.get("OWNER_RAW", "").strip()
    user_id = os.environ.get("USER_ID", "").strip()
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()

    if not title:
        print("Error: TASK_TITLE is required", file=sys.stderr)
        sys.exit(1)

    storage = LocalStorage(base_dir=str(ROOT / "data"))
    due_date = parse_due_date(due_date_raw)
    registry_path = ROOT / "data" / "people_registry.json"

    if owner_raw:
        matches = fuzzy_match_all_persons(owner_raw, registry_path)
        if len(matches) == 0:
            print(f"Warning: no match for '{owner_raw}', defaulting to {TRENT_ID}", file=sys.stderr)
            post_to_slack(response_url, f"No match for *{owner_raw}* in registry — task assigned to you.")
            owner_id = TRENT_ID
        elif len(matches) == 1:
            owner_id = matches[0]["id"]
        else:
            # Ambiguous — prompt via buttons; don't create the task yet
            if user_id and bot_token:
                post_ambiguous_message(user_id, bot_token, owner_raw, matches, title, due_date_raw)
                print(f"Ambiguous owner '{owner_raw}': {[m['canonical_name'] for m in matches]} — posted buttons, task not created")
                return
            else:
                # No channel to prompt in; fall back to first match
                print(f"Warning: multiple matches for '{owner_raw}', no user_id/token — using first: {matches[0]['canonical_name']}", file=sys.stderr)
                owner_id = matches[0]["id"]
    else:
        owner_id = TRENT_ID

    owner_name = resolve_owner_name(owner_id, registry_path)
    add_task(storage, title=title, source="slack", due_date=due_date, owner=owner_id)

    # Only surface owner name in confirmation when explicitly assigned to someone else
    display_owner = owner_name if owner_raw else None
    confirmation = format_confirmation(title, due_date, display_owner)
    post_to_slack(response_url, confirmation)
    print(confirmation)


if __name__ == "__main__":
    main()
