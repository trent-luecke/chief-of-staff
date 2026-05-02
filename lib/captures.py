from datetime import datetime
from typing import Optional

_CAPTURES_KEY = "captures.md"
_FEEDBACK_KEY = "brief_feedback.md"


def append_capture(storage, type_: str, target: Optional[str], content: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    target_str = f" {target} —" if target else ""
    line = f"## {timestamp} — [{type_}]{target_str} {content}\n"
    existing = storage.read(_CAPTURES_KEY) or ""
    storage.write(_CAPTURES_KEY, existing + line)


def load_recent_captures(storage, max_chars: int = 2000) -> str:
    content = storage.read(_CAPTURES_KEY) or ""
    return content[-max_chars:] if len(content) > max_chars else content


def complete_capture(storage, match_text: str) -> bool:
    content = storage.read(_CAPTURES_KEY)
    if content is None:
        return False
    lines = content.splitlines(keepends=True)
    match_lower = match_text.lower()
    new_lines = [l for l in lines if match_lower not in l.lower()]
    if len(new_lines) == len(lines):
        return False
    storage.write(_CAPTURES_KEY, "".join(new_lines))
    return True


def load_brief_feedback(storage, token_budget: int = 800) -> str:
    content = storage.read(_FEEDBACK_KEY) or ""
    max_chars = token_budget * 4
    return content[-max_chars:] if len(content) > max_chars else content


def complete_project_next(projects_file: str, match_text: str) -> bool:
    # projects.md is human-authored; keep raw open()
    import os
    if not os.path.exists(projects_file):
        return False
    try:
        with open(projects_file) as f:
            content = f.read()
        match_lower = match_text.lower()
        lines = content.splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            if line.startswith("**Next:**") and match_lower in line.lower():
                lines[i] = f"**Next:** ~~{line[len('**Next:** '):].rstrip()}~~ ✓\n"
                changed = True
                break
            if line.startswith("## Project:") and match_lower in line.lower():
                for j in range(i + 1, min(i + 8, len(lines))):
                    if lines[j].startswith("**Status:**"):
                        lines[j] = "**Status:** Complete\n"
                        changed = True
                        break
                break
        if not changed:
            return False
        with open(projects_file, "w") as f:
            f.writelines(lines)
        return True
    except OSError:
        return False
