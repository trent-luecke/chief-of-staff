# lib/routines.py
import re
from datetime import date, timedelta
from typing import Optional

_ROUTINES_KEY = "routines.json"


def _load(storage) -> dict:
    return storage.read_json(_ROUTINES_KEY, default={"version": 1, "routines": []})


def _save(storage, data: dict) -> None:
    storage.write_json(_ROUTINES_KEY, data)


# Private slug helpers duplicated from lib/projects.py — both registries keep
# their own copies rather than importing each other's privates.
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")


def _unique_id(base: str, existing_ids: set) -> str:
    if base not in existing_ids:
        return base
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if candidate not in existing_ids:
            return candidate
    raise ValueError(f"Cannot generate unique ID for slug {base!r}: all candidates taken")


def _normalize_steps(steps) -> list:
    """Accept strings or {'title': ...} dicts; drop blank titles."""
    out = []
    for s in steps or []:
        title = (s.get("title") if isinstance(s, dict) else s or "").strip()
        if title:
            out.append({"title": title})
    return out


def list_routines(storage) -> list:
    return _load(storage)["routines"]


def get_routine(storage, routine_id: str) -> Optional[dict]:
    for r in list_routines(storage):
        if r["id"] == routine_id:
            return r
    return None


def add_routine(storage, name: str, steps: list, trigger: Optional[dict] = None) -> dict:
    data = _load(storage)
    existing_ids = {r["id"] for r in data["routines"]}
    routine = {
        "id": _unique_id(_slug(name), existing_ids),
        "name": name,
        "steps": _normalize_steps(steps),
        "trigger": trigger or None,
        "created": date.today().isoformat(),
        "runs": [],
    }
    data["routines"].append(routine)
    _save(storage, data)
    return routine


def update_routine(storage, routine_id: str, updates: dict) -> Optional[dict]:
    data = _load(storage)
    for r in data["routines"]:
        if r["id"] == routine_id:
            if "name" in updates:
                r["name"] = updates["name"]
            if "steps" in updates:
                r["steps"] = _normalize_steps(updates["steps"])
            if "trigger" in updates:
                r["trigger"] = updates["trigger"] or None
            _save(storage, data)
            return r
    return None


def delete_routine(storage, routine_id: str) -> bool:
    data = _load(storage)
    before = len(data["routines"])
    data["routines"] = [r for r in data["routines"] if r["id"] != routine_id]
    if len(data["routines"]) == before:
        return False
    _save(storage, data)
    return True


def run_routine(storage, routine_id: str, source: str = "ui",
                trigger_key: Optional[str] = None) -> Optional[dict]:
    """Instantiate a routine: one ordinary task per step, tagged so the UI can
    group the batch, plus a run record on the routine itself."""
    from lib.tasks import add_task

    data = _load(storage)
    routine = next((r for r in data["routines"] if r["id"] == routine_id), None)
    if routine is None:
        return None

    today = date.today().isoformat()
    tasks = [
        add_task(
            storage,
            title=step["title"],
            source="routine",
            metadata={"routine": routine_id, "routine_run": today},
        )
        for step in routine["steps"]
    ]
    routine["runs"].append({"date": today, "trigger_key": trigger_key, "source": source})
    _save(storage, data)
    return {"routine": routine, "tasks": tasks}


def last_run_date(routine: dict) -> Optional[str]:
    runs = routine.get("runs") or []
    return max((r["date"] for r in runs), default=None)


def ran_within(routine: dict, days: int, today: Optional[str] = None) -> bool:
    last = last_run_date(routine)
    if not last:
        return False
    today_d = date.fromisoformat(today) if today else date.today()
    return last >= (today_d - timedelta(days=days)).isoformat()
