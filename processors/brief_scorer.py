"""Handle /brief score commands and manage brief_scores.jsonl."""

import json
import os
import re
from datetime import date, datetime, timezone
from typing import Optional


SCORE_PATTERN = re.compile(
    r"^/brief\s+score\s+(\d+)(?:\s+(.+))?$", re.IGNORECASE
)

SCORES_FILE = "data/state/brief_scores.jsonl"


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
    scores_file: str = SCORES_FILE,
    score_date: Optional[str] = None,
) -> None:
    entry = {
        "date": score_date or date.today().isoformat(),
        "score": score,
        "note": note,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(scores_file) or ".", exist_ok=True)
    with open(scores_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def handle_score_command(text: str, scores_file: str = SCORES_FILE) -> Optional[str]:
    """Process a /brief score command. Returns response text, or None if not a score command."""
    parsed = parse_score_command(text)
    if parsed is None:
        return None

    score, note = parsed

    if score < 1 or score > 5:
        return "Score must be 1-5. Usage: /brief score 3 [optional note]"

    save_score(score, note, scores_file)

    response = f"Logged: {score}/5 for today's brief."
    if note:
        response += f"\nNote: {note}"
    return response
