# lib/projects.py
import json
import re
from datetime import date, timedelta
from typing import Optional

_PROJECTS_KEY = "projects_registry.json"


def _load(storage) -> dict:
    return storage.read_json(_PROJECTS_KEY, default={"version": 1, "projects": []})


def _save(storage, data: dict) -> None:
    storage.write_json(_PROJECTS_KEY, data)


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


def add_project(
    storage,
    canonical_name: str,
    aliases: Optional[list] = None,
    status: str = "active",
    members: Optional[list] = None,
) -> dict:
    data = _load(storage)
    existing_ids = {p["id"] for p in data["projects"]}
    project_id = _unique_id(_slug(canonical_name), existing_ids)
    project = {
        "id": project_id,
        "canonical_name": canonical_name,
        "aliases": aliases or [],
        "status": status,
        "members": members or [],
        "created": date.today().isoformat(),
        "last_seen": date.today().isoformat(),
    }
    data["projects"].append(project)
    _save(storage, data)
    return project


def get_project(storage, project_id: str) -> Optional[dict]:
    for p in _load(storage)["projects"]:
        if p["id"] == project_id:
            return p
    return None


def list_projects(storage, status: Optional[str] = None) -> list:
    projects = _load(storage)["projects"]
    if status is not None:
        projects = [p for p in projects if p.get("status") == status]
    return projects


def find_project_by_alias(storage, alias: str) -> Optional[dict]:
    alias_lower = alias.lower()
    for p in _load(storage)["projects"]:
        if alias_lower == p["canonical_name"].lower():
            return p
        if alias_lower in [a.lower() for a in p.get("aliases", [])]:
            return p
    return None


def update_project(storage, project_id: str, updates: dict) -> Optional[dict]:
    data = _load(storage)
    for p in data["projects"]:
        if p["id"] == project_id:
            safe_updates = {k: v for k, v in updates.items() if k not in ("id", "created")}
            p.update(safe_updates)
            p["last_seen"] = date.today().isoformat()
            _save(storage, data)
            return p
    return None


def project_context_for_brief(storage, observation_days: int = 14) -> list[dict]:
    """Active projects with open tasks and recently linked observations."""
    from lib.tasks import get_open_tasks
    from lib.project_links import get_links_for_project

    active = list_projects(storage, status="active")
    if not active:
        return []

    cutoff = (date.today() - timedelta(days=observation_days)).isoformat()
    all_tasks = get_open_tasks(storage)

    results = []
    for project in active:
        pid = project["id"]
        p_tasks = [t for t in all_tasks if t.get("project_id") == pid]
        all_links = get_links_for_project(storage, pid)
        recent_links = [lk for lk in all_links if lk.get("obs_date", "") >= cutoff]
        results.append({
            "project": project,
            "open_tasks": p_tasks,
            "linked_obs": recent_links,
        })
    return results
