# lib/meetings.py
"""Meetings replay, writers, and brief/prep render utilities.

Event-sourced store at data/meetings.jsonl (merge=union). One log holds every
meeting keyed by slug. Mirrors the lib/notes.py pattern.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def replay_meetings_content(content: str) -> dict:
    """Replay meetings events from raw JSONL content. Returns {slug: state}."""
    meetings: dict[str, dict] = {}
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        mid = ev.get("id")
        etype = ev.get("event")
        if mid is None or etype is None:
            continue
        if etype == "create_meeting":
            meetings.setdefault(mid, {"id": mid, "agenda": [], "threads": [], "sessions": []})
            continue
        mtg = meetings.get(mid)
        if mtg is None:
            # tolerate events before create (e.g. log replayed out of order); seed it
            mtg = meetings.setdefault(mid, {"id": mid, "agenda": [], "threads": [], "sessions": []})
        if etype == "set_agenda":
            mtg["agenda"] = list(ev.get("items", []))
        elif etype == "add_thread":
            mtg["threads"].append({
                "thread_id": ev["thread_id"],
                "text": ev.get("text", ""),
                "person_id": ev.get("person_id"),
                "task_id": ev.get("task_id"),
                "closed": False,
                "closed_date": None,
                "created_ts": ev["ts"],
            })
        elif etype == "update_thread":
            for th in mtg["threads"]:
                if th["thread_id"] == ev["thread_id"]:
                    for k in ("text", "person_id", "task_id", "closed", "closed_date"):
                        if k in ev:
                            th[k] = ev[k]
                    break
        elif etype == "delete_thread":
            mtg["threads"] = [t for t in mtg["threads"] if t["thread_id"] != ev["thread_id"]]
        elif etype == "add_session":
            mtg["sessions"].append({
                "session_id": ev["session_id"],
                "date": ev.get("date", ev["ts"][:10]),
                "body": ev.get("body", ""),
                "ts": ev["ts"],
            })
        elif etype == "update_session":
            for s in mtg["sessions"]:
                if s["session_id"] == ev["session_id"]:
                    if "body" in ev:
                        s["body"] = ev["body"]
                    s["edited_ts"] = ev["ts"]
                    break
        elif etype == "delete_session":
            mtg["sessions"] = [s for s in mtg["sessions"] if s["session_id"] != ev["session_id"]]
    for mtg in meetings.values():
        mtg["sessions"].sort(key=lambda s: s["ts"], reverse=True)
    return meetings


def open_threads(meeting: dict) -> list:
    """Threads that are not closed."""
    return [t for t in meeting.get("threads", []) if not t.get("closed")]


def render_for_prep(meeting: dict, max_sessions: int = 5) -> str:
    """Render a meeting's open threads + recent sessions as markdown for a prep prompt."""
    parts = []
    threads = open_threads(meeting)
    if threads:
        lines = ["## Open Threads"]
        for t in threads:
            owner = f" (→ {t['person_id']})" if t.get("person_id") else ""
            lines.append(f"- {t['text']}{owner}")
        parts.append("\n".join(lines))
    sessions = meeting.get("sessions", [])[:max_sessions]
    if sessions:
        lines = ["## Session Log"]
        for s in sessions:
            lines.append(f"### {s['date']}\n{s['body']}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def last_session(meeting: dict) -> str:
    """Body of the most recent session entry, or empty string."""
    sessions = meeting.get("sessions", [])
    return sessions[0]["body"] if sessions else ""


# ── writers (storage = anything with .read(key) and .append_line(key, line)) ──

def append_create(storage, meeting_id: str) -> dict:
    ev = {"event": "create_meeting", "id": meeting_id, "ts": _ts()}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_set_agenda(storage, meeting_id: str, items: list) -> dict:
    ev = {"event": "set_agenda", "id": meeting_id, "ts": _ts(), "items": list(items)}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_add_thread(storage, meeting_id: str, text: str, person_id: str | None = None) -> dict:
    ev = {"event": "add_thread", "id": meeting_id, "ts": _ts(),
          "thread_id": "th-" + secrets.token_hex(3), "text": text, "person_id": person_id}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_update_thread(storage, meeting_id: str, thread_id: str, **patch) -> dict:
    ev = {"event": "update_thread", "id": meeting_id, "ts": _ts(), "thread_id": thread_id}
    for k in ("text", "person_id", "task_id", "closed", "closed_date"):
        if k in patch:
            ev[k] = patch[k]
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_delete_thread(storage, meeting_id: str, thread_id: str) -> dict:
    ev = {"event": "delete_thread", "id": meeting_id, "ts": _ts(), "thread_id": thread_id}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_add_session(storage, meeting_id: str, session_date: str, body: str) -> dict:
    ev = {"event": "add_session", "id": meeting_id, "ts": _ts(),
          "session_id": "s-" + secrets.token_hex(3), "date": session_date, "body": body}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_update_session(storage, meeting_id: str, session_id: str, body: str) -> dict:
    ev = {"event": "update_session", "id": meeting_id, "ts": _ts(),
          "session_id": session_id, "body": body}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_delete_session(storage, meeting_id: str, session_id: str) -> dict:
    ev = {"event": "delete_session", "id": meeting_id, "ts": _ts(), "session_id": session_id}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


# ── local git-working-tree helpers ───────────────────────────────────────────
# In GitHub Actions the working tree IS origin/main at checkout (and is committed
# back), so reading/writing the local data dir keeps meetings on the same git
# store the Registry UI uses — NOT R2. Use these in the brief + reply paths.

def replay_local(data_dir: str = "data") -> dict:
    """Replay meetings.jsonl from the local working tree (the git store)."""
    from lib.storage import LocalStorage
    return replay_meetings_content(LocalStorage(data_dir).read("meetings.jsonl") or "")


def append_session_local(data_dir: str, meeting_id: str, session_date: str, body: str) -> dict:
    """Append a session to the local working-tree meetings.jsonl (git store)."""
    from lib.storage import LocalStorage
    return append_add_session(LocalStorage(data_dir), meeting_id, session_date, body)
