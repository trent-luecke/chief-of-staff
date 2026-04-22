"""Tool definitions and executors for the P9 Claude tool use loop."""

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


def execute_tool(name: str, input_: dict, config: dict) -> str:
    """Dispatch a tool call by name. Always returns a string — errors included."""
    try:
        if name == "add_capture":
            return _tool_add_capture(input_["capture_type"], input_["text"], config)
        elif name == "complete_task":
            return _tool_complete_task(input_["description"], config)
        else:
            return f"Unknown tool: '{name}'."
    except KeyError as e:
        return f"Tool '{name}' failed: missing required field {e}."
    except Exception as e:
        return f"Tool '{name}' failed: {e}"
