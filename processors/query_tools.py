"""Tool definitions and executors for the P9 Claude tool use loop."""

import base64
import json
import os
import re
from datetime import date
from email.mime.text import MIMEText
from typing import Any

from collectors.gmail import fetch_threads_needing_attention
from lib.captures import append_capture, complete_capture, complete_project_next
from lib.google_auth import build_gmail_service
from processors.issues import load_issues, save_issues


SAFE_CONFIG_KEYS = {
    "issue_auto_resolve_days",
    "pipeline.enabled",
    "memory.retrieval_token_budget",
    "unread_email_max",
}


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


def _tool_resolve_issue(title_fragment: str, config: dict) -> str:
    issues_file = config.get("issues_file", "data/issues.json")
    log = load_issues(issues_file)
    fragment_lower = title_fragment.lower()
    matches = [i for i in log.issues if fragment_lower in i.title.lower() and i.status == "open"]
    if not matches:
        return f"No open issue found matching '{title_fragment}'."
    issue = matches[0]
    issue.status = "resolved"
    issue.resolved_date = date.today().isoformat()
    save_issues(log, issues_file)
    return f"Resolved issue: '{issue.title}'."


def _tool_update_config(key: str, value, config: dict) -> str:
    if key not in SAFE_CONFIG_KEYS:
        allowed = ", ".join(sorted(SAFE_CONFIG_KEYS))
        return f"Key '{key}' is not in the allowed list. Safe keys: {allowed}."
    config_path = config.get("_config_path", "config.json")
    try:
        with open(config_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return f"Could not read config: {e}"
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        if part not in node:
            return f"Key path '{key}' not found in config."
        node = node[part]
    node[parts[-1]] = value
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)
    return f"Updated config: {key} = {value}"


def _tool_add_to_backlog(description: str, config: dict) -> str:
    backlog_path = config.get("_backlog_path", "BACKLOG.md")
    today = date.today().isoformat()
    entry = f"- {today}: {description}\n"
    try:
        with open(backlog_path) as f:
            content = f.read()
    except FileNotFoundError:
        content = "# Chief of Staff — Backlog\n"
    inbox_header = "## 📥 Inbox\n"
    if inbox_header in content:
        idx = content.index(inbox_header) + len(inbox_header)
        content = content[:idx] + entry + content[idx:]
    else:
        content = content.rstrip("\n") + f"\n\n{inbox_header}{entry}"
    with open(backlog_path, "w") as f:
        f.write(content)
    return f"Added to backlog: {description}"


def _tool_search_gmail(query: str, max_results: int, config: dict) -> str:
    try:
        threads = fetch_threads_needing_attention(
            user_email=config.get("email", ""),
            max_results=max_results,
            query=query,
        )
    except Exception as e:
        return f"Gmail search failed: {e}"
    if not threads:
        return "No matching threads found."
    lines = [f"- [{t.last_sender}] {t.subject} — {t.snippet[:120]}" for t in threads]
    return "\n".join(lines)


def _tool_get_calendar_events(days_ahead: int, config: dict) -> str:
    from collectors.calendar import fetch_today_events
    from datetime import timedelta
    events = []
    for i in range(days_ahead):
        target = date.today() + timedelta(days=i)
        for cal_id in config.get("calendar_ids", ["primary"]):
            try:
                day_events = fetch_today_events(cal_id, target_date=target, user_email=config.get("email", ""))
                for e in day_events:
                    events.append(f"- {target.isoformat()} {e.start.strftime('%H:%M')} {e.summary}")
            except Exception:
                pass
    if not events:
        return "No events found."
    return "\n".join(events)


def _tool_get_pipeline_lead(lead_name: str, config: dict) -> str:
    cache_path = config.get("pipeline", {}).get("cache_path", "data/pipeline_cache.json")
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return "Pipeline cache not available."
    name_lower = lead_name.lower()
    matches = [
        lead for lead in cache.get("leads", [])
        if name_lower in lead.get("name", "").lower()
    ]
    if not matches:
        return f"No lead found matching '{lead_name}'."
    return json.dumps(matches[0], indent=2)


def _tool_create_email_draft(to: str, subject: str, body: str, config: dict) -> str:
    try:
        service = build_gmail_service()
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()
        return f"Draft created: '{subject}' to {to}. Review in Gmail drafts before sending."
    except Exception as e:
        return f"Failed to create draft: {e}"


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
        elif name == "resolve_issue":
            return _tool_resolve_issue(input_["title_fragment"], config)
        elif name == "update_config":
            return _tool_update_config(input_["key"], input_["value"], config)
        elif name == "add_to_backlog":
            return _tool_add_to_backlog(input_["description"], config)
        elif name == "search_gmail":
            return _tool_search_gmail(input_["query"], input_.get("max_results", 5), config)
        elif name == "get_calendar_events":
            return _tool_get_calendar_events(input_.get("days_ahead", 7), config)
        elif name == "get_pipeline_lead":
            return _tool_get_pipeline_lead(input_["lead_name"], config)
        elif name == "create_email_draft":
            return _tool_create_email_draft(input_["to"], input_["subject"], input_["body"], config)
        else:
            return f"Unknown tool: '{name}'."
    except KeyError as e:
        return f"Tool '{name}' failed: missing required field {e}."
    except Exception as e:
        return f"Tool '{name}' failed: {e}"


# ---------------------------------------------------------------------------
# Tool schemas (Anthropic API format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "add_capture",
        "description": "Add a todo, idea, note, or flag to the captures file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capture_type": {"type": "string", "enum": ["todo", "idea", "note", "flag"], "description": "Type of capture"},
                "text": {"type": "string", "description": "Content of the capture"},
            },
            "required": ["capture_type", "text"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a capture or project next-action as complete and remove it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Exact or approximate text of the item to complete"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "add_people_note",
        "description": "Add a note to a contact's people profile file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "person_name": {"type": "string", "description": "Name or partial name of the contact"},
                "note": {"type": "string", "description": "Note to append to their profile"},
            },
            "required": ["person_name", "note"],
        },
    },
    {
        "name": "update_project_next_action",
        "description": "Update the next action field for a project in projects.md.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Name or partial name of the project"},
                "next_action": {"type": "string", "description": "New next action text"},
            },
            "required": ["project_name", "next_action"],
        },
    },
    {
        "name": "create_project",
        "description": "Create a new project entry in projects.md.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "description": {"type": "string", "description": "Brief description of the project"},
                "next_action": {"type": "string", "description": "First next action"},
            },
            "required": ["name", "description", "next_action"],
        },
    },
    {
        "name": "resolve_issue",
        "description": "Mark an open issue as resolved in the issues log.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title_fragment": {"type": "string", "description": "Partial text of the issue title to resolve"},
            },
            "required": ["title_fragment"],
        },
    },
    {
        "name": "update_config",
        "description": "Update a system configuration value. Only safe keys are allowed: issue_auto_resolve_days, pipeline.enabled, memory.retrieval_token_budget, unread_email_max.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Config key (dot notation for nested, e.g. memory.retrieval_token_budget)"},
                "value": {"description": "New value"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "add_to_backlog",
        "description": "Add an item to the chief-of-staff backlog inbox for future consideration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Description of the backlog item"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "search_gmail",
        "description": "Search Gmail threads using a Gmail search query string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query (e.g. 'from:john@apex.com', 'subject:onboarding newer_than:7d')"},
                "max_results": {"type": "integer", "description": "Maximum threads to return (default 5)", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_calendar_events",
        "description": "Fetch upcoming calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {"type": "integer", "description": "Number of days ahead to fetch (default 7)", "default": 7},
            },
            "required": [],
        },
    },
    {
        "name": "get_pipeline_lead",
        "description": "Look up a pipeline lead by name and return their full record from the pipeline cache.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_name": {"type": "string", "description": "Name or partial name of the lead/company"},
            },
            "required": ["lead_name"],
        },
    },
    {
        "name": "create_email_draft",
        "description": "Create a draft email in Gmail. The draft is saved but NOT sent — review and send from Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Plain text email body"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]
