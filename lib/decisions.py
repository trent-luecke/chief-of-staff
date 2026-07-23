"""Write primitive for the durable decisions log (data/memory/decisions.md).

Format: one line per entry, "YYYY-MM-DD: <text>". Storage is anything with
.read(key) and .append_line(key, line) rooted at data/ (LocalStorage or
MainStorage). Caller is responsible for committing.
"""
from __future__ import annotations

DECISIONS_KEY = "memory/decisions.md"


def append_decision(storage, text: str, date_str: str) -> str:
    line = f"{date_str}: {text}"
    storage.append_line(DECISIONS_KEY, line)
    return line
