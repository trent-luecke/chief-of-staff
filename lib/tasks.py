import uuid
from datetime import date, timedelta
from typing import Optional

_TASKS_KEY = "tasks.json"


def _load(storage) -> dict:
    return storage.read_json(_TASKS_KEY, default={"tasks": []})


def _save(storage, data: dict) -> None:
    storage.write_json(_TASKS_KEY, data)


def add_task(storage, title: str, source: str = "telegram", due_date: Optional[str] = None, metadata: Optional[dict] = None) -> dict:
    data = _load(storage)
    task = {
        "id": f"t-{uuid.uuid4().hex[:6]}",
        "title": title,
        "status": "open",
        "created_at": date.today().isoformat(),
        "due_date": due_date,
        "source": source,
        "completed_at": None,
        "metadata": metadata if metadata is not None else {},
    }
    data["tasks"].append(task)
    _save(storage, data)
    return task


def complete_task(storage, match_text: str) -> Optional[dict]:
    data = _load(storage)
    match_lower = match_text.lower()
    for task in data["tasks"]:
        if task["status"] == "open" and match_lower in task["title"].lower():
            task["status"] = "completed"
            task["completed_at"] = date.today().isoformat()
            _save(storage, data)
            return task
    return None


def get_open_tasks(storage) -> list[dict]:
    data = _load(storage)
    return [t for t in data["tasks"] if t["status"] == "open"]


def get_recent_completions(storage, days: int = 7) -> list[dict]:
    data = _load(storage)
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [
        t for t in data["tasks"]
        if t["status"] == "completed" and (t.get("completed_at") or "") >= cutoff
    ]
