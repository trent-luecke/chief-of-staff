import json
from dataclasses import dataclass
from typing import Optional

import anthropic
from collectors.calendar import CalendarEvent


@dataclass
class MeetingConfig:
    calendar_pattern: str
    memory_file: str
    nudge_subject: str
    nudge_minutes_after: int


def load_meeting_index(path: str) -> list[MeetingConfig]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [MeetingConfig(**m) for m in data.get("meetings", [])]


def find_meeting_for_event(
    event: CalendarEvent, configs: list[MeetingConfig]
) -> Optional[MeetingConfig]:
    summary_lower = event.summary.lower()
    for config in configs:
        if config.calendar_pattern.lower() in summary_lower:
            return config
    return None


def append_session_notes(storage, key: str, session_date: str, notes: str) -> None:
    """key is like 'meeting_memory/standup.md'"""
    content = storage.read(key) or "# Meeting Memory\n\n## Session Log\n\n"
    entry = f"\n### {session_date}\n{notes.strip()}\n"
    if "## Session Log" in content:
        content = content + entry
    else:
        content = content + "\n## Session Log\n" + entry
    storage.write(key, content)


_REWRITE_SYSTEM = """\
You are maintaining a living memory document for a recurring work meeting.
Your job is to rewrite this document incorporating today's new session notes.

Rules:
- Preserve date-stamped session entries (### YYYY-MM-DD format) from the last 30 days. Drop any dated entries older than 30 days with no ongoing threads.
- After the session log, maintain a "Current State" section: a synthesized 3-5 sentence model of the relationship/project/working dynamic as it stands today. Rewrite this section each time.
- Maintain an "Open Threads" section: a bullet list of unresolved items, questions, or action items. Add new ones from today's notes. Remove any that were resolved or went cold (no mention in 2+ sessions).
- Plain markdown. No preamble. No commentary about what you changed.

Document structure:
# [Meeting Name]

## Current State
[synthesized model — 3-5 sentences]

## Open Threads
- [item]
- [item]

## Session Log

### YYYY-MM-DD
[notes]

### YYYY-MM-DD
[notes]"""


def rewrite_meeting_memory(
    storage,
    key: str,
    session_date: str,
    new_notes: str,
    api_key: str,
    model: str = "claude-sonnet-4-6",
) -> None:
    existing_content = storage.read(key) or ""
    meeting_name = key.rsplit("/", 1)[-1].removesuffix(".md").replace("_", " ").title()

    user_message = (
        f"Meeting: {meeting_name}\n"
        f"Today's date: {session_date}\n"
        f"New session notes: {new_notes}\n\n"
        f"Existing document:\n{existing_content or '(no prior sessions)'}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=_REWRITE_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    storage.write(key, response.content[0].text.strip())


def load_last_session_summary(storage, key: str) -> str:
    """key is like 'meeting_memory/standup.md'"""
    content = storage.read(key)
    if not content:
        return ""
    lines = content.splitlines()
    last_header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("### "):
            last_header_idx = i
    if last_header_idx is None:
        return ""
    return "\n".join(lines[last_header_idx + 1:]).strip()
