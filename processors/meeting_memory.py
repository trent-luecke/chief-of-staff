import json
import re
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


def append_session_notes(memory_file: str, session_date: str, notes: str) -> None:
    try:
        with open(memory_file) as f:
            content = f.read()
    except FileNotFoundError:
        content = "# Meeting Memory\n\n## Session Log\n\n"

    entry = f"\n### {session_date}\n{notes.strip()}\n"

    if "## Session Log" in content:
        content = content + entry
    else:
        content = content + "\n## Session Log\n" + entry

    try:
        with open(memory_file, "w") as f:
            f.write(content)
    except OSError as e:
        raise OSError(f"Failed to write meeting memory file {memory_file}: {e}") from e


def load_last_session_summary(memory_file: str) -> str:
    try:
        with open(memory_file) as f:
            content = f.read()
    except FileNotFoundError:
        return ""

    sessions = re.split(r"\n### \d{4}-\d{2}-\d{2}\n", content)
    if len(sessions) < 2:
        return ""
    return sessions[-1].strip()
