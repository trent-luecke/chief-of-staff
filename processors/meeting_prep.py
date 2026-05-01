"""Pre-meeting prep: classification, context assembly, Claude call, state I/O."""

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

import anthropic
from collectors.calendar import CalendarEvent

EXTERNAL_KEYWORDS = {"demo", "reconnect", "intro", "pitch", "walkthrough", "onboarding", "call"}


def classify_meeting(event: CalendarEvent, config: dict) -> Optional[str]:
    """Return meeting prep type or None if this meeting should be skipped."""
    title = event.summary.lower()
    prep_cfg = config.get("meeting_prep", {})

    for pattern in prep_cfg.get("dept_heads_patterns", []):
        if pattern.lower() in title:
            return "dept_heads"

    for pattern in prep_cfg.get("recurring_internal_patterns", []):
        if pattern.lower() in title:
            return "recurring_internal"

    PERSONAL_KEYWORDS = {
        "haircut", "doctor", "dentist", "gym", "workout", "therapy",
        "appointment", "birthday", "anniversary", "vacation", "lunch",
        "dinner", "blocked", "focus time", "deep work", "no meetings", "ooo",
    }
    if any(kw in title for kw in PERSONAL_KEYWORDS):
        return None

    has_external_keyword = any(kw in title for kw in EXTERNAL_KEYWORDS)
    has_external_attendee = any(
        "@teambuildr.com" not in a.lower() for a in event.attendees
    )

    if has_external_keyword or (event.attendees and has_external_attendee):
        return "external"

    return None


def make_prep_key(event: CalendarEvent) -> str:
    return f"{event.id}_{date.today().isoformat()}"


def load_prep_state(path: str) -> set:
    try:
        with open(path) as f:
            data = json.load(f)
        return set(data.get("sent_keys", []))
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return set()


def save_prep_state(sent_keys: set, path: str) -> None:
    cutoff = date.today() - timedelta(days=7)

    def _key_date(k: str) -> date:
        try:
            return date.fromisoformat(k.rsplit("_", 1)[-1])
        except ValueError:
            return date.min  # prune malformed keys immediately

    recent = {k for k in sent_keys if _key_date(k) >= cutoff}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({"sent_keys": sorted(recent)}, f, indent=2)
