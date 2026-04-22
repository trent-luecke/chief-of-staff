"""Tool definitions and executors for the P9 Claude tool use loop."""

import os
import re
from datetime import date
from typing import Any

from lib.captures import append_capture, complete_capture, complete_project_next


def _tool_add_capture(capture_type: str, text: str, config: dict) -> str:
    valid = {"todo", "idea", "note", "flag"}
    if capture_type not in valid:
        return f"Invalid capture type '{capture_type}'. Must be one of: {', '.join(sorted(valid))}."
    captures_file = config.get("captures_file", "data/captures.md")
    append_capture(captures_file, capture_type, None, text)
    return f"Captured [{capture_type}]: {text}"


def _tool_complete_task(description: str, config: dict) -> str:
    captures_file = config.get("captures_file", "data/captures.md")
    projects_file = config.get("projects_file", "data/projects.md")
    hit_capture = complete_capture(captures_file, description)
    hit_project = complete_project_next(projects_file, description)
    if hit_capture or hit_project:
        parts = []
        if hit_capture:
            parts.append("removed from captures")
        if hit_project:
            parts.append("marked done in projects")
        return f"Completed '{description}' — {', '.join(parts)}."
    return f"No match found for '{description}' in captures or projects."


def _find_people_file(people_dir: str, person_name: str) -> str | None:
    if not os.path.isdir(people_dir):
        return None
    name_parts = person_name.lower().split()
    for fname in sorted(os.listdir(people_dir)):
        if not fname.endswith(".md"):
            continue
        base = fname[:-3].lower()
        # Match whole tokens only — "ryan" matches "ryan_smith" but not "bryanna"
        if any(re.search(rf"(?<![a-z]){re.escape(part)}(?![a-z])", base) for part in name_parts):
            return os.path.join(people_dir, fname)
    return None


def _tool_add_people_note(person_name: str, note: str, config: dict) -> str:
    people_dir = config.get("people_dir", "data/people")
    path = _find_people_file(people_dir, person_name)
    if not path:
        return f"No file found matching '{person_name}'."
    timestamp = date.today().isoformat()
    entry = f"- {timestamp}: {note}\n"
    with open(path, "a") as f:
        f.write(entry)
    return f"Note added to {os.path.basename(path)[:-3]}: {note}"


def _tool_update_project_next_action(project_name: str, next_action: str, config: dict) -> str:
    projects_file = config.get("projects_file", "data/projects.md")
    if not os.path.exists(projects_file):
        return "Projects file not found."
    with open(projects_file) as f:
        lines = f.readlines()
    name_lower = project_name.lower()
    in_section = False
    changed = False
    for i, line in enumerate(lines):
        if line.startswith("## Project:"):
            in_section = name_lower in line.lower()
        if in_section and line.startswith("**Next:**"):
            lines[i] = f"**Next:** {next_action}\n"
            changed = True
            break
    if not changed:
        return f"Project '{project_name}' not found or has no Next field."
    with open(projects_file, "w") as f:
        f.writelines(lines)
    return f"Updated next action for '{project_name}': {next_action}"


def _tool_create_project(name: str, description: str, next_action: str, config: dict) -> str:
    projects_file = config.get("projects_file", "data/projects.md")
    entry = (
        f"\n## Project: {name}\n"
        f"**Status:** In Progress\n"
        f"**Priority:** Medium\n"
        f"**Tier:** core\n"
        f"**Next:** {next_action}\n"
        f"**Notes:** {description}\n"
    )
    os.makedirs(os.path.dirname(projects_file) or ".", exist_ok=True)
    with open(projects_file, "a") as f:
        f.write(entry)
    return f"Project '{name}' created with next action: {next_action}"


def execute_tool(name: str, input_: dict, config: dict) -> str:
    """Dispatch a tool call by name. Always returns a string — errors included."""
    try:
        if name == "add_capture":
            return _tool_add_capture(input_["capture_type"], input_["text"], config)
        elif name == "complete_task":
            return _tool_complete_task(input_["description"], config)
        elif name == "add_people_note":
            return _tool_add_people_note(input_["person_name"], input_["note"], config)
        elif name == "update_project_next_action":
            return _tool_update_project_next_action(input_["project_name"], input_["next_action"], config)
        elif name == "create_project":
            return _tool_create_project(input_["name"], input_["description"], input_["next_action"], config)
        else:
            return f"Unknown tool: '{name}'."
    except KeyError as e:
        return f"Tool '{name}' failed: missing required field {e}."
    except Exception as e:
        return f"Tool '{name}' failed: {e}"
