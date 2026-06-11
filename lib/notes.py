# lib/notes.py
"""Notes replay and brief-loading utilities."""
from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def replay_notes(path: Path) -> list[dict]:
    """Replay notes.jsonl events from a file and return current state (see replay_notes_content)."""
    if not path.exists():
        return []
    return replay_notes_content(path.read_text())


def replay_notes_content(content: str) -> list[dict]:
    """Replay notes events from raw JSONL content and return current state for every
    non-deleted note.

    Each returned note includes a derived `brief_flagged_date` field (ISO date string
    or None): the calendar date of the most recent event that set brief=True.
    """
    notes: dict[str, dict] = {}
    brief_flagged_dates: dict[str, str] = {}
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nid = ev["id"]
        etype = ev["event"]
        if etype == "create":
            notes[nid] = {
                "id": nid,
                "ts": ev["ts"],
                "body": ev["body"],
                "tags": ev.get("tags", []),
                "person_id": ev.get("person_id"),
                "task_id": ev.get("task_id"),
                "project_id": ev.get("project_id"),
                "brief": ev.get("brief", False),
                "pinned": ev.get("pinned", False),
            }
            if ev.get("brief"):
                brief_flagged_dates[nid] = ev["ts"][:10]
        elif etype == "update" and nid in notes:
            patch = {k: v for k, v in ev.items() if k not in ("event", "id", "ts")}
            notes[nid].update(patch)
            if ev.get("brief") is True:
                brief_flagged_dates[nid] = ev["ts"][:10]
            elif ev.get("brief") is False:
                brief_flagged_dates.pop(nid, None)
        elif etype == "pin" and nid in notes:
            notes[nid]["pinned"] = ev.get("pinned", True)
        elif etype == "delete":
            notes.pop(nid, None)
            brief_flagged_dates.pop(nid, None)
    result = []
    for nid, note in notes.items():
        n = dict(note)
        n["brief_flagged_date"] = brief_flagged_dates.get(nid)
        result.append(n)
    return result


def add_note(
    storage,
    body: str,
    tags: list | None = None,
    person_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    brief: bool = False,
    pinned: bool = False,
) -> dict:
    """Append a create event to notes.jsonl and return the event dict.

    Mirrors the create path in tools/server.py so Slack-created notes match
    UI-created notes exactly. Caller is responsible for committing the file.
    """
    note_id = "n-" + secrets.token_hex(3)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ev = {
        "event": "create",
        "id": note_id,
        "ts": ts,
        "body": body,
        "tags": tags or [],
        "person_id": person_id,
        "task_id": task_id,
        "project_id": project_id,
        "brief": brief,
        "pinned": pinned,
    }
    storage.append_line("notes.jsonl", json.dumps(ev))
    return ev


def load_notes_for_brief(storage) -> str:
    """Return formatted notes context string for brief, empty string if nothing to show."""
    notes_path = storage.base_dir / "notes.jsonl"
    all_notes = replay_notes(notes_path)
    brief_notes = [n for n in all_notes if n.get("brief") and n.get("brief_flagged_date")]
    if not brief_notes:
        return ""

    brief_date = date.today()
    todays = [
        n for n in brief_notes
        if n["brief_flagged_date"] == (brief_date - timedelta(days=1)).isoformat()
    ]
    yesterdays = [
        n for n in brief_notes
        if n["brief_flagged_date"] == (brief_date - timedelta(days=2)).isoformat()
    ]
    if not todays and not yesterdays:
        return ""

    people_by_id: dict[str, str] = {}
    try:
        registry = json.loads((storage.base_dir / "people_registry.json").read_text())
        people_by_id = {
            p["id"]: p.get("canonical_name", p["id"])
            for p in registry.get("people", [])
        }
    except Exception:
        pass

    projects_by_id: dict[str, str] = {}
    try:
        preg = json.loads((storage.base_dir / "projects_registry.json").read_text())
        projects_by_id = {
            p["id"]: p.get("canonical_name", p["id"])
            for p in preg.get("projects", [])
        }
    except Exception:
        pass

    lines: list[str] = []
    if todays:
        lines.append("### Today's Notes (flagged for today's brief)")
        for n in todays:
            lines.append(_format_note_line(n, people_by_id, projects_by_id))
        lines.append("")
    if yesterdays:
        lines.append("### Yesterday's Notes (flagged for yesterday's brief)")
        for n in yesterdays:
            lines.append(_format_note_line(n, people_by_id, projects_by_id))
        lines.append("")
    return "\n".join(lines)


def _format_note_line(note: dict, people_by_id: dict, projects_by_id: dict | None = None) -> str:
    """Format a single note as a brief-ready bullet line."""
    projects_by_id = projects_by_id or {}
    extras = []
    if note.get("tags"):
        extras.append(f"[{', '.join(note['tags'])}]")
    if note.get("person_id") and note["person_id"] in people_by_id:
        extras.append(f"→ {people_by_id[note['person_id']]}")
    if note.get("project_id") and note["project_id"] in projects_by_id:
        extras.append(f"⊕ {projects_by_id[note['project_id']]}")
    suffix = f"  ({' '.join(extras)})" if extras else ""
    return f"  - {note['body']}{suffix}"
