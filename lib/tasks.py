# lib/tasks.py
import json
import uuid
from datetime import date, timedelta
from typing import Optional

_KEY = "tasks.jsonl"
_LEGACY_KEY = "tasks.json"


def _migrate_if_needed(storage) -> None:
    """One-time migration: tasks.json → tasks.jsonl create/complete events."""
    if storage.exists(_KEY):
        return
    legacy = storage.read_json(_LEGACY_KEY, default=None)
    if not legacy:
        return
    lines = []
    for t in legacy.get("tasks", []):
        create_event = {
            "event": "create",
            "task_id": t["id"],
            "title": t["title"],
            "source": t.get("source", "telegram"),
            "created_at": t.get("created_at", date.today().isoformat()),
            "due_date": t.get("due_date"),
            "metadata": t.get("metadata") or {},
            "project_id": t.get("project_id"),
            "collaborators": t.get("collaborators") or [],
        }
        lines.append(json.dumps(create_event))
        if t.get("status") == "completed":
            complete_event = {
                "event": "complete",
                "task_id": t["id"],
                "completed_at": t.get("completed_at") or date.today().isoformat(),
            }
            lines.append(json.dumps(complete_event))
    storage.write(_KEY, "\n".join(lines) + ("\n" if lines else ""))


def _replay(storage) -> dict:
    """Replay the event log and return current task state keyed by task_id."""
    _migrate_if_needed(storage)
    content = storage.read(_KEY) or ""
    tasks = {}
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        task_id = event.get("task_id")
        if not task_id:
            continue
        etype = event["event"]
        if etype == "create":
            tasks[task_id] = {
                "id": task_id,
                "title": event["title"],
                "status": "open",
                "created_at": event["created_at"],
                "due_date": event.get("due_date"),
                "source": event.get("source", "telegram"),
                "completed_at": None,
                "metadata": event.get("metadata") or {},
                "project_id": event.get("project_id"),
                "collaborators": event.get("collaborators") or [],
            }
        elif etype == "complete" and task_id in tasks:
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["completed_at"] = event["completed_at"]
        elif etype == "edit" and task_id in tasks:
            tasks[task_id].update(event.get("patch", {}))
    return tasks


def _append(storage, event: dict) -> None:
    storage.append_line(_KEY, json.dumps(event))


def add_task(
    storage,
    title: str,
    source: str = "telegram",
    due_date: Optional[str] = None,
    metadata: Optional[dict] = None,
    project_id: Optional[str] = None,
    collaborators: Optional[list] = None,
) -> dict:
    _migrate_if_needed(storage)
    task_id = f"t-{uuid.uuid4().hex[:6]}"
    today = date.today().isoformat()
    event = {
        "event": "create",
        "task_id": task_id,
        "title": title,
        "source": source,
        "created_at": today,
        "due_date": due_date,
        "metadata": metadata if metadata is not None else {},
        "project_id": project_id,
        "collaborators": collaborators or [],
    }
    _append(storage, event)
    return {
        "id": task_id,
        "title": title,
        "status": "open",
        "created_at": today,
        "due_date": due_date,
        "source": source,
        "completed_at": None,
        "metadata": metadata if metadata is not None else {},
        "project_id": project_id,
        "collaborators": collaborators or [],
    }


def complete_task(storage, match_text: str) -> Optional[dict]:
    tasks = _replay(storage)
    match_lower = match_text.lower()
    for task in tasks.values():
        if task["status"] == "open" and match_lower in task["title"].lower():
            today = date.today().isoformat()
            _append(storage, {"event": "complete", "task_id": task["id"], "completed_at": today})
            task["status"] = "completed"
            task["completed_at"] = today
            return task
    return None


def edit_task(storage, task_id: str, patch: dict) -> Optional[dict]:
    tasks = _replay(storage)
    if task_id not in tasks:
        return None
    _PROTECTED = {"id", "task_id", "status", "created_at", "completed_at", "source"}
    safe_patch = {k: v for k, v in patch.items() if k not in _PROTECTED}
    if not safe_patch:
        return tasks[task_id]
    _append(storage, {"event": "edit", "task_id": task_id, "patch": safe_patch})
    tasks[task_id].update(safe_patch)
    return tasks[task_id]


def get_open_tasks(storage) -> list:
    return [t for t in _replay(storage).values() if t["status"] == "open"]


def get_recent_completions(storage, days: int = 7) -> list:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [
        t for t in _replay(storage).values()
        if t["status"] == "completed" and (t.get("completed_at") or "") >= cutoff
    ]
