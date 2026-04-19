from datetime import datetime
from typing import Optional
import os


def append_capture(captures_file: str, type_: str, target: Optional[str], content: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    target_str = f" {target} —" if target else ""
    line = f"## {timestamp} — [{type_}]{target_str} {content}\n"
    dir_ = os.path.dirname(captures_file)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    with open(captures_file, "a") as f:
        f.write(line)


def load_recent_captures(captures_file: str, max_chars: int = 2000) -> str:
    if not os.path.exists(captures_file):
        return ""
    try:
        with open(captures_file) as f:
            content = f.read()
        return content[-max_chars:] if len(content) > max_chars else content
    except OSError:
        return ""


def load_brief_feedback(feedback_file: str, token_budget: int = 800) -> str:
    if not os.path.exists(feedback_file):
        return ""
    try:
        with open(feedback_file) as f:
            content = f.read()
        max_chars = token_budget * 4
        return content[-max_chars:] if len(content) > max_chars else content
    except OSError:
        return ""
