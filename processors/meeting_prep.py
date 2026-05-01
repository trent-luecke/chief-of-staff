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
        "teambuildr.com" not in a.lower() for a in event.attendees
    )

    if event.attendees and (has_external_keyword or has_external_attendee):
        return "external"
    if not event.attendees and has_external_keyword:
        return "external"

    return None
