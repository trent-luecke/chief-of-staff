import json
from dataclasses import dataclass
from typing import Optional
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
