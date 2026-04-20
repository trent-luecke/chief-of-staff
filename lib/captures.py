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


def complete_capture(captures_file: str, match_text: str) -> bool:
    if not os.path.exists(captures_file):
        return False
    try:
        with open(captures_file) as f:
            lines = f.readlines()
        match_lower = match_text.lower()
        new_lines = [l for l in lines if match_lower not in l.lower()]
        if len(new_lines) == len(lines):
            return False
        with open(captures_file, "w") as f:
            f.writelines(new_lines)
        return True
    except OSError:
        return False


def complete_project_next(projects_file: str, match_text: str) -> bool:
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
