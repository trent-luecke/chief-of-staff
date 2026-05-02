"""Handle /brief score commands and manage brief_scores.jsonl."""

import json
import re
from datetime import date, datetime, timezone
from typing import Optional


SCORE_PATTERN = re.compile(
    r"^/brief\s+score\s+(\d+)(?:\s+(.+))?$", re.IGNORECASE
)

_SCORES_KEY = "state/brief_scores.jsonl"


def parse_score_command(text: str) -> Optional[tuple[int, Optional[str]]]:
    """Return (score, note) if text is a /brief score command, else None."""
    match = SCORE_PATTERN.match(text.strip())
    if not match:
        return None
    score = int(match.group(1))
    note = match.group(2).strip() if match.group(2) else None
    return score, note


def save_score(
    score: int,
    note: Optional[str] = None,
    storage=None,
) -> None:
    if storage is None:
        return
    entry = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "note": note,
    }
    storage.append_line(_SCORES_KEY, json.dumps(entry))


def handle_score_command(text: str, storage=None) -> Optional[str]:
    """Process a /brief score command. Returns response text, or None if not a score command."""
    result = parse_score_command(text)
    if result is None:
        return None
    score, note = result
    if score < 1 or score > 5:
        return f"Score must be 1–5 (got {score})."
    save_score(score, note, storage)
    msg = f"Score {score}/5 logged."
    if note:
        msg += f" Note: {note}"
    return msg
