"""Tool definitions and executors for the P9 Claude tool use loop."""

import base64
import json
import os
import re
from datetime import date
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from collectors.gmail import fetch_threads_needing_attention
from lib.captures import append_capture, complete_project_next
from lib.tasks import add_task, complete_task as complete_task_record, get_open_tasks, get_recent_completions
from lib.google_auth import build_gmail_service
from processors.issues import load_issues, save_issues


SAFE_CONFIG_KEYS = {
    "issue_auto_resolve_days",
    "pipeline.enabled",
    "memory.retrieval_token_budget",
    "unread_email_max",
}

CHANGE_WHITELIST = frozenset({
    "processors/query_tools.py",
    "processors/query.py",
    "main.py",
    "config.json",
})

PENDING_CHANGE_PATH = "data/pending_change.json"

# Buyer's-story program: interview-guide template inside the Notion DB.
BUYER_STORY_TEMPLATE_URL = "https://app.notion.com/p/3a724bca36d781c59753f174d9f0e2d6"
BUYER_STORY_LEAD_DAYS = 14  # days after signing to send the interview request


def _sync_canvas(config: dict) -> None:
    """Push current task state to the Slack canvas. Non-fatal.
    Tasks are read from the git-anchored registry store."""
    import os
    canvas_cfg = config.get("slack_canvas", {})
    canvas_id = canvas_cfg.get("canvas_id")
    token = os.environ.get("SLACK_USER_TOKEN", "")
    if not canvas_id or not token:
        return
    try:
        from lib.slack_canvas import sync_task_canvas
        from lib.storage import registry_storage
        from lib.tasks import get_open_tasks, get_recent_completions
        reg = registry_storage(config)
        sync_task_canvas(token, canvas_id, get_open_tasks(reg), get_recent_completions(reg))
    except Exception as e:
        import sys
        print(f"WARNING: canvas sync failed: {e}", file=sys.stderr)


def _tool_add_capture(capture_type: str, text: str, storage, config: dict, due_date: str = "") -> str:
    valid = {"todo", "idea", "note", "flag"}
    if capture_type not in valid:
        return f"Invalid capture type '{capture_type}'. Must be one of: {', '.join(sorted(valid))}."
    if capture_type == "todo":
        # tasks.jsonl is git-anchored (Slack /task, Registry UI) — captures.md stays on runtime storage (R2)
        from lib.storage import registry_storage
        task = add_task(registry_storage(config), text, source="telegram", due_date=due_date or None)
        _sync_canvas(config)
        return f"Task added [{task['id']}]: {text}"
    append_capture(storage, capture_type, None, text)
    return f"Captured [{capture_type}]: {text}"


def _tool_schedule_buyer_story(account: str, config: dict, signed_date: str = "") -> str:
    """Queue a post-signing buyer's-story interview for a newly signed account.

    Creates a git-anchored registry task whose horizon is BUYER_STORY_LEAD_DAYS
    after signing. It stays de-emphasized in the Work UI until then, and the
    daily brief's "Surfaced Today" section announces it on the horizon date —
    that day-14 callout is the whole point. Signing date defaults to today."""
    from datetime import datetime, timedelta
    from lib.storage import registry_storage

    account = (account or "").strip()
    if not account:
        return "Need an account name to schedule a buyer's-story interview."
    try:
        signed = datetime.strptime(signed_date, "%Y-%m-%d").date() if signed_date else date.today()
    except ValueError:
        return f"Couldn't parse signed date '{signed_date}' — use YYYY-MM-DD."

    horizon = (signed + timedelta(days=BUYER_STORY_LEAD_DAYS)).isoformat()
    title = (f"Send {account} the buyer's-story interview request "
             f"(signed {signed.isoformat()}). Template: {BUYER_STORY_TEMPLATE_URL}")
    task = add_task(
        registry_storage(config), title, source="slack",
        due_date=horizon, horizon=horizon,
        metadata={"kind": "buyer_story", "account": account, "signed_date": signed.isoformat()},
    )
    _sync_canvas(config)
    return (f"Buyer's-story interview queued for {account} [{task['id']}] — "
            f"surfaces in your brief on {horizon} ({BUYER_STORY_LEAD_DAYS} days after "
            f"signing on {signed.isoformat()}).")


def _tool_complete_task(description: str, storage, config: dict) -> str:
    from lib.storage import registry_storage
    projects_file = config.get("projects_file", "data/projects.md")
    task = complete_task_record(registry_storage(config), description)
    hit_project = complete_project_next(projects_file, description)
    if task or hit_project:
        _sync_canvas(config)
        parts = []
        if task:
            parts.append(f"task '{task['title'][:60]}' marked completed")
        if hit_project:
            parts.append("project next-action marked done")
        return f"Completed — {', '.join(parts)}."
    return f"No match found for '{description}' in tasks or projects."


def _tool_list_tasks(storage, include_recent_completions: bool = False) -> str:
    open_tasks = get_open_tasks(storage)
    lines = []
    if open_tasks:
        lines.append("**Open tasks:**")
        for t in open_tasks:
            due = f" (due {t['due_date']})" if t.get("due_date") else ""
            lines.append(f"  [{t['id']}] {t['title']}{due}")
    else:
        lines.append("No open tasks.")
    if include_recent_completions:
        completed = get_recent_completions(storage, days=7)
        if completed:
            lines.append("\n**Completed this week:**")
            for t in completed:
                lines.append(f"  ✓ {t['title']} (completed {t['completed_at']})")
    return "\n".join(lines)


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


def _tool_create_person_profile(
    name: str,
    config: dict,
    email: str = "",
    role: str = "",
    relationship: str = "",
    slack_handle: str = "",
    notes: str = "",
) -> str:
    people_dir = config.get("people_dir", "data/people")
    filename = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    filename = re.sub(r"[\s_]+", "-", filename) + ".md"
    path = Path(people_dir) / filename
    if not path.resolve().is_relative_to(Path(people_dir).resolve()):
        return "Invalid name — path traversal rejected."
    if path.exists():
        return f"Profile already exists: {filename}. Use add_people_note to append notes."
    os.makedirs(people_dir, exist_ok=True)
    content = f"# {name}\n\n"
    if email:
        content += f"**Email:** {email}\n"
    if role:
        content += f"**Role:** {role}\n"
    if slack_handle:
        content += f"**Slack:** {slack_handle}\n"
    content += "\n## Relationship\n"
    if relationship:
        content += f"{relationship}\n"
    content += "\n## Notes\n"
    if notes:
        content += f"- {date.today().isoformat()}: {notes}\n"
    path.write_text(content)
    return f"Profile created: {filename}"


def _tool_get_person_profile(person_name: str, config: dict) -> str:
    people_dir = config.get("people_dir", "data/people")
    path = _find_people_file(people_dir, person_name)
    if not path:
        return f"No profile found matching '{person_name}'."
    try:
        with open(path) as f:
            return f.read()
    except OSError as e:
        return f"Could not read profile: {e}"


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


def _tool_resolve_issue(title_fragment: str, storage, config: dict) -> str:
    log = load_issues(storage)
    fragment_lower = title_fragment.lower()
    matches = [i for i in log.issues if fragment_lower in i.title.lower() and i.status == "open"]
    if not matches:
        return f"No open issue found matching '{title_fragment}'."
    issue = matches[0]
    issue.status = "resolved"
    issue.resolved_date = date.today().isoformat()
    save_issues(log, storage)
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


def _tool_queue_notion_update(
    person: str,
    action: str,
    config: dict,
    note: str = "",
    stage: str = "",
    follow_up_date: str = "",
    reason: str = "",
) -> str:
    import uuid
    from datetime import datetime, timezone

    valid_actions = {"add_note", "update_stage", "set_follow_up", "delete_record"}
    if action not in valid_actions:
        return f"Invalid action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}."
    if action == "delete_record" and not reason:
        return "reason is required for delete_record actions."

    queue_path = config.get("notion_queue_path", "data/notion_updates_queue.json")
    try:
        with open(queue_path) as f:
            queue = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        queue = []

    entry: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "person": person,
        "action": action,
    }
    if note:
        entry["note"] = note
    if stage:
        entry["stage"] = stage
    if follow_up_date:
        entry["follow_up_date"] = follow_up_date
    if reason:
        entry["reason"] = reason

    queue.append(entry)
    os.makedirs(os.path.dirname(queue_path) or ".", exist_ok=True)
    with open(queue_path, "w") as f:
        json.dump(queue, f, indent=2)

    action_desc = {
        "add_note": f"note queued for {person}",
        "update_stage": f"stage update to '{stage}' queued for {person}",
        "set_follow_up": f"follow-up date {follow_up_date} queued for {person}",
        "delete_record": f"delete record queued for {person} (reason: {reason})",
    }[action]
    return f"Notion queue: {action_desc}. Cowork will apply this on its next scheduled run."


def _tool_set_brief_preference(preference: str, config: dict) -> str:
    prefs_path = config.get("brief_prefs_path", "data/brief_prefs.md")
    today = date.today().isoformat()
    header = f"## {today}"
    try:
        with open(prefs_path) as f:
            content = f.read()
    except FileNotFoundError:
        content = ""

    if header in content:
        idx = content.index(header) + len(header)
        next_section = content.find("\n##", idx)
        if next_section == -1:
            content = content.rstrip("\n") + f"\n- {preference}\n"
        else:
            content = content[:next_section] + f"\n- {preference}" + content[next_section:]
    else:
        content = content.rstrip("\n") + f"\n\n{header}\n- {preference}\n"

    os.makedirs(os.path.dirname(prefs_path) or ".", exist_ok=True)
    with open(prefs_path, "w") as f:
        f.write(content)
    return f"Brief preference set: {preference}. Takes effect in tomorrow's brief."


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


def _tool_propose_code_change(file: str, description: str, new_content: str) -> str:
    import difflib
    import subprocess
    import tempfile as _tempfile
    from datetime import datetime, timezone

    if file not in CHANGE_WHITELIST:
        allowed = ", ".join(sorted(CHANGE_WHITELIST))
        return f"File '{file}' is not on the change whitelist. Allowed: {allowed}."

    if os.path.exists(PENDING_CHANGE_PATH):
        try:
            with open(PENDING_CHANGE_PATH) as f:
                existing = json.load(f)
            return (
                f"Pending change already exists for '{existing.get('file', '?')}': "
                f"{existing.get('description', '?')}. Approve or reject it first."
            )
        except json.JSONDecodeError:
            return (
                f"Pending change file at {PENDING_CHANGE_PATH} is corrupt. "
                "Delete it manually and try again."
            )

    try:
        with open(file) as f:
            old_content = f.read()
    except FileNotFoundError:
        old_content = ""

    if file.endswith(".py"):
        with _tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
            tmp.write(new_content)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["python3", "-m", "py_compile", tmp_path],
                capture_output=True, text=True,
            )
        finally:
            os.unlink(tmp_path)
        if result.returncode != 0:
            error = result.stderr.replace(tmp_path, file)
            return f"Syntax check failed — change not sent:\n{error.strip()}"
    elif file.endswith(".json"):
        try:
            json.loads(new_content)
        except json.JSONDecodeError as e:
            return f"JSON validation failed — change not sent:\n{e}"

    diff_lines = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{file}",
        tofile=f"b/{file}",
    ))
    diff_text = "".join(diff_lines) if diff_lines else "(no changes detected)"

    pending = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file": file,
        "description": description,
        "diff": diff_text,
        "new_content": new_content,
    }
    os.makedirs(os.path.dirname(PENDING_CHANGE_PATH) or ".", exist_ok=True)
    with open(PENDING_CHANGE_PATH, "w") as f:
        json.dump(pending, f, indent=2)

    MAX_DIFF = 3500
    if len(diff_text) > MAX_DIFF:
        return (
            f"Diff for '{file}' is {len(diff_text)} chars — too large to display safely in Telegram "
            f"(limit {MAX_DIFF}). Break the change into smaller pieces."
        )

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("QUERY_CHAT_ID", "")
    if bot_token and chat_id:
        from lib.telegram import send_message
        msg = (
            f"Proposed change to `{file}`:\n"
            f"_{description}_\n\n"
            f"```\n{diff_text}\n```\n\n"
            f"Reply 'approve' or 'reject'."
        )
        send_message(bot_token, chat_id, msg)
        return f"Proposed change to {file} sent to Telegram for your approval. Reply 'approve' or 'reject'."

    return f"Proposed change to {file} saved to pending_change.json. Reply 'approve' or 'reject' to apply."


def execute_tool(name: str, input_: dict, config: dict, storage=None) -> str:
    """Dispatch a tool call by name. Always returns a string — errors included."""
    if storage is None:
        from lib.storage import build_storage
        storage = build_storage(config)
    try:
        if name == "add_capture":
            return _tool_add_capture(input_["capture_type"], input_["text"], storage, config, due_date=input_.get("due_date", ""))
        elif name == "complete_task":
            return _tool_complete_task(input_["description"], storage, config)
        elif name == "schedule_buyer_story":
            return _tool_schedule_buyer_story(input_["account"], config, signed_date=input_.get("signed_date", ""))
        elif name == "list_tasks":
            from lib.storage import registry_storage
            return _tool_list_tasks(registry_storage(config), include_recent_completions=input_.get("include_recent_completions", False))
        elif name == "add_people_note":
            return _tool_add_people_note(input_["person_name"], input_["note"], config)
        elif name == "create_person_profile":
            return _tool_create_person_profile(
                name=input_["name"],
                config=config,
                email=input_.get("email", ""),
                role=input_.get("role", ""),
                relationship=input_.get("relationship", ""),
                slack_handle=input_.get("slack_handle", ""),
                notes=input_.get("notes", ""),
            )
        elif name == "get_person_profile":
            return _tool_get_person_profile(input_["person_name"], config)
        elif name == "update_project_next_action":
            return _tool_update_project_next_action(input_["project_name"], input_["next_action"], config)
        elif name == "create_project":
            return _tool_create_project(input_["name"], input_["description"], input_["next_action"], config)
        elif name == "resolve_issue":
            return _tool_resolve_issue(input_["title_fragment"], storage, config)
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
        elif name == "set_reminder":
            from processors.reminders import set_reminder
            return set_reminder(storage, input_["message"], input_["fire_at"], config)
        elif name == "queue_notion_update":
            return _tool_queue_notion_update(
                person=input_["person"],
                action=input_["action"],
                config=config,
                note=input_.get("note", ""),
                stage=input_.get("stage", ""),
                follow_up_date=input_.get("follow_up_date", ""),
                reason=input_.get("reason", ""),
            )
        elif name == "set_brief_preference":
            return _tool_set_brief_preference(input_["preference"], config)
        elif name == "propose_code_change":
            return _tool_propose_code_change(
                file=input_["file"],
                description=input_["description"],
                new_content=input_["new_content"],
            )
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
        "description": "Add a todo, idea, note, or flag. Todos go to the task ledger (persistent, with optional due date). Ideas, notes, and flags go to the captures file. After calling, include a receipt entry in your response naming the destination and content written.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capture_type": {"type": "string", "enum": ["todo", "idea", "note", "flag"], "description": "Type of capture"},
                "text": {"type": "string", "description": "Content of the capture"},
                "due_date": {"type": "string", "description": "Optional due date in YYYY-MM-DD format (todos only)"},
            },
            "required": ["capture_type", "text"],
        },
    },
    {
        "name": "schedule_buyer_story",
        "description": "Queue a post-signing buyer's-story interview for a newly SIGNED account. Use when Trent reports a new signed customer and wants the buyer's-story follow-up (e.g. 'we just signed Baxter — schedule the buyer's story', 'log the Acme signing', 'set up a buyer's-story interview for X'). Creates a registry task that surfaces in the daily brief 14 days after signing, prompting him to send the interview request email. Defaults the signing date to today; pass signed_date if it signed earlier. Do NOT use this for generic to-dos — that's add_capture.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Name of the newly signed account / customer."},
                "signed_date": {"type": "string", "description": "Signing date YYYY-MM-DD. Defaults to today if omitted."},
            },
            "required": ["account"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task as complete. The task is moved to the completed ledger with a timestamp — not deleted. Also checks project next-actions. After calling, include a receipt entry in your response.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Exact or approximate text of the task to complete"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Return all open tasks. Optionally include tasks completed in the last 7 days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_recent_completions": {"type": "boolean", "description": "If true, also return tasks completed in the last 7 days"},
            },
            "required": [],
        },
    },
    {
        "name": "add_people_note",
        "description": "Add a note to a contact's people profile file. After calling, include a receipt entry in your response naming the destination and content written.",
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
        "name": "create_person_profile",
        "description": "Create a new people profile file for a contact who doesn't have one yet. Use add_people_note instead if a profile already exists. After calling, include a receipt entry in your response naming the destination and content written.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Full name of the person"},
                "email": {"type": "string", "description": "Email address (optional)"},
                "role": {"type": "string", "description": "Their role or title (optional)"},
                "relationship": {"type": "string", "description": "Short description of your relationship or how you know them (optional)"},
                "slack_handle": {"type": "string", "description": "Slack handle e.g. @username (optional)"},
                "notes": {"type": "string", "description": "Initial note to add (optional)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_person_profile",
        "description": "Read the full profile file for a contact, including Activity, Notes, and Relationship sections.",
        "input_schema": {
            "type": "object",
            "properties": {
                "person_name": {"type": "string", "description": "Name or partial name of the contact"},
            },
            "required": ["person_name"],
        },
    },
    {
        "name": "update_project_next_action",
        "description": "Update the next action field for a project in projects.md. After calling, include a receipt entry in your response naming the destination and content written.",
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
        "description": "Create a new project entry in projects.md. After calling, include a receipt entry in your response naming the destination and content written.",
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
        "description": "Mark an open issue as resolved in the issues log. After calling, include a receipt entry in your response naming the destination and content written.",
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
        "description": "Update a system configuration value. Only safe keys are allowed: issue_auto_resolve_days, pipeline.enabled, memory.retrieval_token_budget, unread_email_max. After calling, include a receipt entry in your response naming the destination and content written.",
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
        "description": "Add an item to the chief-of-staff backlog inbox for future consideration. After calling, include a receipt entry in your response naming the destination and content written.",
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
        "description": "Create a draft email in Gmail. The draft is saved but NOT sent — review and send from Gmail. After calling, include a receipt entry in your response naming the destination and content written.",
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
    {
        "name": "set_reminder",
        "description": (
            "Set a timed reminder that fires via Telegram. The reminder system checks every "
            "15 minutes (:00, :15, :30, :45), so fire_at must land on a 15-minute boundary. "
            "Before calling this tool, check if the target time is on a boundary — if not, "
            "do NOT call this tool; ask the user which surrounding mark they prefer. "
            "Only offer boundaries that are in the future. After calling, include a receipt entry in your response naming the destination and content written."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The reminder text to send to the user",
                },
                "fire_at": {
                    "type": "string",
                    "description": (
                        "UTC ISO 8601 datetime on a 15-minute boundary with seconds set to :00 "
                        "(e.g. 2026-05-05T21:00:00Z, 2026-05-05T21:15:00Z)"
                    ),
                },
            },
            "required": ["message", "fire_at"],
        },
    },
    {
        "name": "queue_notion_update",
        "description": (
            "Queue an update to a Notion pipeline record. Cowork applies queued updates on its next scheduled run. "
            "Supported actions: add_note (append note to record), update_stage (change deal stage), "
            "set_follow_up (set a follow-up date), delete_record (delete the record — requires reason field). "
            "After calling, include a receipt entry naming the person, action queued, and that Cowork will apply it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person": {"type": "string", "description": "Name of the person whose Notion pipeline record to update"},
                "action": {
                    "type": "string",
                    "enum": ["add_note", "update_stage", "set_follow_up", "delete_record"],
                    "description": "Action to queue",
                },
                "note": {"type": "string", "description": "Note text (for add_note)"},
                "stage": {"type": "string", "description": "New deal stage (for update_stage)"},
                "follow_up_date": {"type": "string", "description": "Follow-up date YYYY-MM-DD (for set_follow_up)"},
                "reason": {"type": "string", "description": "Reason for deletion — required for delete_record"},
            },
            "required": ["person", "action"],
        },
    },
    {
        "name": "set_brief_preference",
        "description": (
            "Set a preference that controls what appears in the morning brief. Preferences are freeform text "
            "and take effect in the next brief run. Examples: 'skip gym scout section this week', "
            "'always lead with pipeline follow-ups', 'remind me about Jake Torres tomorrow'. "
            "To clear or override a preference, call this with a correcting statement "
            "e.g. 'remove the gym scout skip'. "
            "After calling, include a receipt entry naming the preference set and when it takes effect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preference": {"type": "string", "description": "Freeform preference instruction for the morning brief"},
            },
            "required": ["preference"],
        },
    },
    {
        "name": "propose_code_change",
        "description": (
            "Propose a change to a whitelisted system file. Reads the current file, runs a Python syntax check "
            "on the new content (for .py files), and sends the unified diff to Telegram for approval. "
            "You must provide the COMPLETE new file content — not a partial patch. "
            "Whitelisted files: processors/query_tools.py, processors/query.py, main.py, config.json. "
            "Only one pending change is allowed at a time. The user replies 'approve' or 'reject' to proceed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Relative path to the file (must be on the whitelist)"},
                "description": {"type": "string", "description": "One-sentence description of what the change does"},
                "new_content": {"type": "string", "description": "Complete new content for the file (full file, not a patch)"},
            },
            "required": ["file", "description", "new_content"],
        },
    },
]
