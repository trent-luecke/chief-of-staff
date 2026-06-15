# Meetings Agenda Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Meetings" tab to the Registry UI where each recurring meeting has one editable doc — a user-owned Agenda, user-owned Open Threads (closable, person-taggable, promote-to-task), and a user+AI Session Log — backed by an event-sourced `data/meetings.jsonl`, with the existing nudge-reply flow switched from full-AI-rewrite to append-into-Session-Log-only.

**Architecture:** Event-sourced `data/meetings.jsonl` (same pattern as `data/notes.jsonl`) replayed by a new `lib/meetings.py`. Per-meeting config (name, people links, calendar pattern, nudge settings) lives in the existing `data/meeting_index.json`. The server (`tools/server.py`) reads from the `origin/main` snapshot and writes via `_write_main`; the UI is vanilla JS in `tools/registry_ui.html`. The brief/prep and nudge-reply code repoint from the old markdown `meeting_memory/*.md` files to `lib/meetings.py`.

**Tech Stack:** Python/Flask (server), vanilla JS/CSS (UI), pytest (tests), JSONL event log with `merge=union`, JSON config registry.

**Design spec:** [docs/superpowers/specs/2026-06-15-meetings-agenda-surface-design.md](../specs/2026-06-15-meetings-agenda-surface-design.md)

---

## File Map

| File | Change |
|------|--------|
| `lib/meetings.py` | **Create** — `replay_meetings_content()`, writer fns (`append_*`), `open_threads()`, `render_for_prep()`, `last_session()` |
| `tests/test_meetings_lib.py` | **Create** — unit tests for replay, writers, render helpers |
| `processors/meeting_memory.py` | **Modify** — extend `MeetingConfig` dataclass with `name`, `people_ids`, `meeting_id` property |
| `tools/server.py` | **Modify** — snapshot fields, bootstrap payload, 10 meeting endpoints |
| `tools/registry_ui.html` | **Modify** — Meetings tab button, view, CSS, JS render + editing + New Meeting modal |
| `data/meeting_index.json` | **Modify** (via migration) — add `name`, `people_ids` to each entry |
| `data/meetings.jsonl` | **Create** (via migration) — seeded create + background-session events |
| `.gitattributes` | **Modify** — add `data/meetings.jsonl merge=union` |
| `scripts/migrate_meeting_memory.py` | **Create** — one-time migration from `meeting_memory/*.md` |
| `reply_collector.py` | **Modify** — replace `rewrite_meeting_memory` with `lib.meetings.append_add_session` |
| `ask.py` | **Modify** — replace `append_session_notes` with `lib.meetings.append_add_session` |
| `pipeline.py` | **Modify** — `build_meeting_prep` uses `lib.meetings.last_session` |
| `processors/meeting_prep.py` | **Modify** — `build_recurring_internal_context` uses `lib.meetings.render_for_prep` |

## Data model — `data/meetings.jsonl` events

All events carry `event`, `id` (meeting slug, e.g. `luke_1on1`), `ts` (UTC `YYYY-MM-DDTHH:MM:SS`).

| `event` | Extra fields | Meaning |
|---------|--------------|---------|
| `create_meeting` | — | meeting doc exists |
| `set_agenda` | `items: [str]` | replace the full ordered agenda list |
| `add_thread` | `thread_id`, `text`, `person_id` | new open thread |
| `update_thread` | `thread_id`, + any of `text`/`person_id`/`task_id`/`closed`/`closed_date` | patch a thread |
| `delete_thread` | `thread_id` | remove a thread |
| `add_session` | `session_id`, `date`, `body` | append a Session Log entry |

**Replayed meeting state** (per slug):
```python
{
  "id": "luke_1on1",
  "agenda": ["talk about X", "..."],          # ordered list of strings
  "threads": [                                  # insertion order
    {"thread_id": "th-abc123", "text": "...", "person_id": "luke-green",
     "task_id": None, "closed": False, "closed_date": None, "created_ts": "..."},
  ],
  "sessions": [                                 # newest first
    {"session_id": "s-abc123", "date": "2026-06-12", "body": "...", "ts": "..."},
  ],
}
```

**Closed-thread display rule:** replay keeps all threads (the log is truth). The UI hides threads where `closed` is true and `closed_date` is more than 7 days old; `render_for_prep` shows open threads only.

---

## Task 1: `lib/meetings.py` — replay + writers + render helpers

**Files:**
- Create: `lib/meetings.py`
- Test: `tests/test_meetings_lib.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_meetings_lib.py
import json
import lib.meetings as m


def _content(events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_replay_empty():
    assert m.replay_meetings_content("") == {}


def test_replay_create_only():
    c = _content([{"event": "create_meeting", "id": "luke_1on1", "ts": "2026-06-01T10:00:00"}])
    state = m.replay_meetings_content(c)
    assert set(state.keys()) == {"luke_1on1"}
    mtg = state["luke_1on1"]
    assert mtg["agenda"] == []
    assert mtg["threads"] == []
    assert mtg["sessions"] == []


def test_replay_set_agenda_replaces():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "set_agenda", "id": "x", "ts": "2026-06-01T11:00:00", "items": ["a", "b"]},
        {"event": "set_agenda", "id": "x", "ts": "2026-06-01T12:00:00", "items": ["c"]},
    ])
    assert m.replay_meetings_content(c)["x"]["agenda"] == ["c"]


def test_replay_thread_lifecycle():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_thread", "id": "x", "ts": "2026-06-01T11:00:00",
         "thread_id": "th-1", "text": "follow up", "person_id": "luke-green"},
        {"event": "update_thread", "id": "x", "ts": "2026-06-01T12:00:00",
         "thread_id": "th-1", "task_id": "t-abc123"},
        {"event": "update_thread", "id": "x", "ts": "2026-06-02T09:00:00",
         "thread_id": "th-1", "closed": True, "closed_date": "2026-06-02"},
    ])
    th = m.replay_meetings_content(c)["x"]["threads"][0]
    assert th["thread_id"] == "th-1"
    assert th["text"] == "follow up"
    assert th["person_id"] == "luke-green"
    assert th["task_id"] == "t-abc123"
    assert th["closed"] is True
    assert th["closed_date"] == "2026-06-02"


def test_replay_delete_thread():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_thread", "id": "x", "ts": "2026-06-01T11:00:00",
         "thread_id": "th-1", "text": "t", "person_id": None},
        {"event": "delete_thread", "id": "x", "ts": "2026-06-01T12:00:00", "thread_id": "th-1"},
    ])
    assert m.replay_meetings_content(c)["x"]["threads"] == []


def test_replay_sessions_newest_first():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "first"},
        {"event": "add_session", "id": "x", "ts": "2026-06-08T10:01:00",
         "session_id": "s-2", "date": "2026-06-08", "body": "second"},
    ])
    sessions = m.replay_meetings_content(c)["x"]["sessions"]
    assert [s["session_id"] for s in sessions] == ["s-2", "s-1"]


def test_open_threads_excludes_closed():
    mtg = {"threads": [
        {"thread_id": "a", "closed": False, "closed_date": None, "text": "open", "person_id": None, "task_id": None},
        {"thread_id": "b", "closed": True, "closed_date": "2026-06-02", "text": "done", "person_id": None, "task_id": None},
    ]}
    assert [t["thread_id"] for t in m.open_threads(mtg)] == ["a"]


def test_render_for_prep_includes_open_threads_and_sessions():
    mtg = {
        "id": "x",
        "agenda": ["prep item"],
        "threads": [{"thread_id": "a", "closed": False, "closed_date": None,
                     "text": "chase invoice", "person_id": None, "task_id": None}],
        "sessions": [{"session_id": "s-1", "date": "2026-06-08", "body": "talked shop", "ts": "2026-06-08T10:00:00"}],
    }
    out = m.render_for_prep(mtg)
    assert "chase invoice" in out
    assert "2026-06-08" in out
    assert "talked shop" in out


def test_last_session_returns_newest_body():
    mtg = {"sessions": [
        {"session_id": "s-2", "date": "2026-06-08", "body": "newer", "ts": "2026-06-08T10:00:00"},
        {"session_id": "s-1", "date": "2026-06-01", "body": "older", "ts": "2026-06-01T10:00:00"},
    ]}
    assert m.last_session(mtg) == "newer"


def test_last_session_empty():
    assert m.last_session({"sessions": []}) == ""


# ── writers (use a fake storage with the append_line/read interface) ──

class _FakeStore:
    def __init__(self):
        self.data = {}
    def read(self, key):
        return self.data.get(key)
    def append_line(self, key, line):
        existing = self.data.get(key) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.data[key] = existing + line + "\n"


def test_append_add_session_writes_event_and_replays():
    store = _FakeStore()
    m.append_create(store, "x")
    ev = m.append_add_session(store, "x", "2026-06-12", "notes here")
    assert ev["event"] == "add_session"
    assert ev["session_id"].startswith("s-")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["sessions"][0]["body"] == "notes here"


def test_append_add_thread_generates_id():
    store = _FakeStore()
    m.append_create(store, "x")
    ev = m.append_add_thread(store, "x", "do the thing", person_id="luke-green")
    assert ev["thread_id"].startswith("th-")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["threads"][0]["text"] == "do the thing"
    assert state["x"]["threads"][0]["person_id"] == "luke-green"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_meetings_lib.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'lib.meetings'`

- [ ] **Step 3: Create `lib/meetings.py`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_meetings_lib.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/meetings.py tests/test_meetings_lib.py
git commit -m "feat: add lib/meetings.py event replay, writers, and render helpers"
```

---

## Task 2: `processors/meeting_memory.py` — extend `MeetingConfig`

**Files:**
- Modify: `processors/meeting_memory.py:9-23`
- Test: `tests/test_meeting_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meeting_config.py
import json
from processors.meeting_memory import MeetingConfig, load_meeting_index


def test_meeting_config_defaults_and_id():
    cfg = MeetingConfig(
        calendar_pattern="luke / trent",
        memory_file="data/meeting_memory/luke_1on1.md",
        nudge_subject="1:1 notes?",
        nudge_minutes_after=5,
    )
    assert cfg.name == ""
    assert cfg.people_ids == []
    assert cfg.meeting_id == "luke_1on1"


def test_meeting_config_with_new_fields():
    cfg = MeetingConfig(
        calendar_pattern="department heads",
        memory_file="data/meeting_memory/rev_dept_heads.md",
        nudge_subject="Dept heads notes?",
        nudge_minutes_after=5,
        name="Revenue Dept Heads",
        people_ids=["luke-green", "james-peters"],
    )
    assert cfg.name == "Revenue Dept Heads"
    assert cfg.people_ids == ["luke-green", "james-peters"]
    assert cfg.meeting_id == "rev_dept_heads"


def test_load_meeting_index_tolerates_new_fields(tmp_path):
    p = tmp_path / "meeting_index.json"
    p.write_text(json.dumps({"meetings": [
        {"calendar_pattern": "x", "memory_file": "data/meeting_memory/x.md",
         "nudge_subject": "x?", "nudge_minutes_after": 5,
         "name": "X Meeting", "people_ids": ["a"]},
    ]}))
    cfgs = load_meeting_index(str(p))
    assert cfgs[0].name == "X Meeting"
    assert cfgs[0].meeting_id == "x"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_meeting_config.py -v 2>&1 | head -20
```
Expected: FAIL — `MeetingConfig` has no `name` field (TypeError on unexpected keyword / missing attribute).

- [ ] **Step 3: Extend the dataclass**

Replace `processors/meeting_memory.py:9-23` (the `MeetingConfig` dataclass and `load_meeting_index`):

```python
from dataclasses import dataclass, field


@dataclass
class MeetingConfig:
    calendar_pattern: str
    memory_file: str
    nudge_subject: str
    nudge_minutes_after: int
    name: str = ""
    people_ids: list = field(default_factory=list)

    @property
    def meeting_id(self) -> str:
        return self.memory_file.rsplit("/", 1)[-1].removesuffix(".md")


def load_meeting_index(path: str) -> list[MeetingConfig]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [MeetingConfig(**m) for m in data.get("meetings", [])]
```

Ensure the top of the file imports `field` (the line `from dataclasses import dataclass` becomes `from dataclasses import dataclass, field`; remove the now-duplicate import added above if the file already imported `dataclass`).

- [ ] **Step 4: Run test to confirm it passes**

```bash
python -m pytest tests/test_meeting_config.py -v
python -c "from processors.meeting_memory import load_meeting_index; print(len(load_meeting_index('data/meeting_index.json')))"
```
Expected: tests PASS; the second prints `6` (existing entries still load with defaulted `name`/`people_ids`).

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_memory.py tests/test_meeting_config.py
git commit -m "feat: extend MeetingConfig with name, people_ids, meeting_id"
```

---

## Task 3: `.gitattributes` + migration script

**Files:**
- Modify: `.gitattributes`
- Create: `scripts/migrate_meeting_memory.py`

- [ ] **Step 1: Add the merge driver**

Append to `.gitattributes`:

```
data/meetings.jsonl merge=union
```

- [ ] **Step 2: Create the migration script**

```python
# scripts/migrate_meeting_memory.py
"""One-time migration: seed data/meetings.jsonl from the legacy meeting_memory/*.md
files and backfill name/people_ids into data/meeting_index.json.

Idempotent: re-running detects meetings already present in meetings.jsonl and skips
their create/background-session seeding.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import lib.meetings as meetings  # noqa: E402

DATA = ROOT / "data"
INDEX = DATA / "meeting_index.json"
MEETINGS = DATA / "meetings.jsonl"


def _current_state_blurb(md_text: str) -> str:
    """Extract the text under '## Current State' from a legacy memory file."""
    lines = md_text.splitlines()
    out, capture = [], False
    for ln in lines:
        if ln.strip().startswith("## Current State"):
            capture = True
            continue
        if capture and ln.startswith("## "):
            break
        if capture:
            out.append(ln)
    return "\n".join(out).strip()


class _FileStore:
    """Minimal storage over the working-tree data dir for lib.meetings writers."""
    def read(self, key):
        p = DATA / key
        return p.read_text() if p.exists() else None
    def append_line(self, key, line):
        p = DATA / key
        existing = p.read_text() if p.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        p.write_text(existing + line + "\n")


def run():
    index = json.loads(INDEX.read_text())
    store = _FileStore()
    existing = meetings.replay_meetings_content(store.read("meetings.jsonl") or "")

    for entry in index.get("meetings", []):
        mid = entry["memory_file"].rsplit("/", 1)[-1].removesuffix(".md")
        # backfill config fields
        entry.setdefault("name", mid.replace("_", " ").title())
        entry.setdefault("people_ids", [])
        if mid in existing:
            print(f"skip {mid} (already migrated)")
            continue
        meetings.append_create(store, mid)
        md_path = DATA / entry["memory_file"].removeprefix("data/")
        blurb = _current_state_blurb(md_path.read_text()) if md_path.exists() else ""
        if blurb:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            meetings.append_add_session(store, mid, today, f"(background) {blurb}")
        print(f"migrated {mid}")

    INDEX.write_text(json.dumps(index, indent=2) + "\n")
    print("done")


if __name__ == "__main__":
    run()
```

- [ ] **Step 3: Run the migration**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python scripts/migrate_meeting_memory.py
```
Expected: `migrated luke_1on1` … (6 lines) then `done`. Re-running prints `skip … (already migrated)` for all 6.

- [ ] **Step 4: Verify the output**

```bash
python -c "import lib.meetings as m; s=m.replay_meetings_content(open('data/meetings.jsonl').read()); print(sorted(s.keys())); print(len(s))"
python -c "import json; idx=json.load(open('data/meeting_index.json')); print([(e['memory_file'].split('/')[-1], e['name'], e['people_ids']) for e in idx['meetings']])"
```
Expected: 6 meeting slugs; each `meeting_index` entry now has `name` and `people_ids` keys.

- [ ] **Step 5: Commit**

```bash
git add .gitattributes scripts/migrate_meeting_memory.py data/meetings.jsonl data/meeting_index.json
git commit -m "feat: migrate legacy meeting_memory to data/meetings.jsonl; backfill index"
```

---

## Task 4: `tools/server.py` — snapshot + GET endpoints

**Files:**
- Modify: `tools/server.py:24` (import), `:33-44` (`_Snapshot`), `:52-67` (`rebuild_snapshot`), `:107-119` (bootstrap), and add a `# --- Meetings ---` section after the Notes Tags section (after line 431).

- [ ] **Step 1: Add the import + snapshot fields + meeting config loader**

After line 24 (`from lib.notes import replay_notes_content`), add:

```python
import lib.meetings as meetings_lib
from processors.meeting_memory import load_meeting_index
```

In `class _Snapshot` (after `self.tags = []`), add:

```python
        self.meetings = {}        # slug -> replayed doc state
        self.meeting_index = []   # list of config dicts from meeting_index.json
```

In `rebuild_snapshot()`, after `SNAPSHOT.tags = store.read_json("notes_tags.json", default=[])`, add:

```python
    SNAPSHOT.meetings = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
    SNAPSHOT.meeting_index = store.read_json("meeting_index.json", default={"meetings": []}).get("meetings", [])
```

- [ ] **Step 2: Add a meetings helper + include in bootstrap**

After `_people_list()` (after line 99), add:

```python
def _meeting_id(entry: dict) -> str:
    return entry["memory_file"].rsplit("/", 1)[-1].removesuffix(".md")


def _meetings_list():
    """Join config (meeting_index) with replayed doc state, keyed by slug."""
    out = []
    for entry in SNAPSHOT.meeting_index:
        mid = _meeting_id(entry)
        doc = SNAPSHOT.meetings.get(mid, {"id": mid, "agenda": [], "threads": [], "sessions": []})
        out.append({
            "id": mid,
            "name": entry.get("name") or mid.replace("_", " ").title(),
            "calendar_pattern": entry.get("calendar_pattern", ""),
            "people_ids": entry.get("people_ids", []),
            "nudge_subject": entry.get("nudge_subject", ""),
            "nudge_minutes_after": entry.get("nudge_minutes_after", 5),
            "agenda": doc["agenda"],
            "threads": doc["threads"],
            "sessions": doc["sessions"],
        })
    return out
```

In `bootstrap()`'s returned dict, add after `"tags": SNAPSHOT.tags,`:

```python
        "meetings": _meetings_list(),
```

- [ ] **Step 3: Add GET endpoints** (after line 431, end of Notes Tags section)

```python
# --- Meetings ---

@app.route("/api/meetings", methods=["GET"])
def list_meetings():
    return jsonify(_meetings_list())


@app.route("/api/meetings/<meeting_id>", methods=["GET"])
def get_meeting(meeting_id: str):
    for mtg in _meetings_list():
        if mtg["id"] == meeting_id:
            return jsonify(mtg)
    return jsonify({"error": "not found"}), 404
```

- [ ] **Step 4: Verify server imports + GET works**

```bash
python -c "from tools.server import app; print('ok')"
```
Expected: `ok`.

Then, with the server running (`python tools/server.py`) in another terminal:

```bash
curl -s http://localhost:8787/api/meetings | python3 -m json.tool | head -30
```
Expected: array of 6 meetings, each with `id`, `name`, `people_ids`, `agenda`, `threads`, `sessions`.

- [ ] **Step 5: Commit**

```bash
git add tools/server.py
git commit -m "feat: meetings snapshot + GET /api/meetings endpoints"
```

---

## Task 5: `tools/server.py` — New Meeting (POST) + config PATCH

**Files:**
- Modify: `tools/server.py` (in the `# --- Meetings ---` section)

- [ ] **Step 1: Add POST + PATCH endpoints** (after the GET endpoints from Task 4)

```python
import re as _re


def _slugify(name: str) -> str:
    s = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "meeting"


@app.route("/api/meetings", methods=["POST"])
def create_meeting():
    body = request.get_json(force=True)
    if not body or not body.get("name"):
        return jsonify({"error": "name is required"}), 400
    name = body["name"]

    def mutate(store):
        existing = store.read_json("meeting_index.json", default={"meetings": []})
        slugs = {_meeting_id(e) for e in existing["meetings"]}
        slug = _slugify(name)
        candidate, i = slug, 2
        while candidate in slugs:
            candidate, i = f"{slug}_{i}", i + 1
        slug = candidate
        entry = {
            "calendar_pattern": body.get("calendar_pattern", ""),
            "memory_file": f"data/meeting_memory/{slug}.md",
            "nudge_subject": body.get("nudge_subject", f"{name} notes?"),
            "nudge_minutes_after": body.get("nudge_minutes_after", 5),
            "name": name,
            "people_ids": body.get("people_ids", []),
        }
        existing["meetings"].append(entry)
        store.write_json("meeting_index.json", existing)
        meetings_lib.append_create(store, slug)
        return slug

    slug, push, status = _write_main(mutate, lambda s: f"data: create meeting {s}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    return jsonify({"id": slug, "push": push}), 201


@app.route("/api/meetings/<meeting_id>", methods=["PATCH"])
def update_meeting(meeting_id: str):
    body = request.get_json(force=True)

    def mutate(store):
        idx = store.read_json("meeting_index.json", default={"meetings": []})
        entry = next((e for e in idx["meetings"] if _meeting_id(e) == meeting_id), None)
        if entry is None:
            return None
        for k in ("name", "calendar_pattern", "people_ids", "nudge_subject", "nudge_minutes_after"):
            if k in body:
                entry[k] = body[k]
        store.write_json("meeting_index.json", idx)
        return entry

    result, push, status = _write_main(mutate, f"data: update meeting {meeting_id} config")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})
```

Move the `import re as _re` to the top of the file with the other imports (line ~10-14) rather than inside the section; it's shown here for locality.

- [ ] **Step 2: Smoke test**

With the server running:

```bash
curl -s -X POST http://localhost:8787/api/meetings \
  -H "Content-Type: application/json" \
  -d '{"name":"Sales Marketing Weekly","calendar_pattern":"sales sync","people_ids":["luke-green"]}' | python3 -m json.tool
# Expected: {"id":"sales_marketing_weekly","push":{...}} with 201

curl -s http://localhost:8787/api/meetings/sales_marketing_weekly | python3 -m json.tool
# Expected: the meeting with name, calendar_pattern, people_ids=["luke-green"], empty agenda/threads/sessions

curl -s -X PATCH http://localhost:8787/api/meetings/sales_marketing_weekly \
  -H "Content-Type: application/json" -d '{"people_ids":["luke-green","james-peters"]}' | python3 -m json.tool
# Expected: meeting config with both people_ids
```

> Note: these writes commit to `origin/main`. The test meeting can be left (it's harmless) or removed in a later cleanup commit; do not add a UI delete in this plan.

- [ ] **Step 3: Commit**

```bash
git add tools/server.py
git commit -m "feat: POST /api/meetings (new meeting) + PATCH config endpoint"
```

---

## Task 6: `tools/server.py` — agenda + session endpoints

**Files:**
- Modify: `tools/server.py` (in the `# --- Meetings ---` section)

- [ ] **Step 1: Add agenda + session endpoints**

```python
def _meeting_exists(store, meeting_id: str) -> bool:
    idx = store.read_json("meeting_index.json", default={"meetings": []})
    return any(_meeting_id(e) == meeting_id for e in idx["meetings"])


def _meeting_doc_after_write(store, meeting_id: str) -> dict:
    state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
    return state.get(meeting_id, {"id": meeting_id, "agenda": [], "threads": [], "sessions": []})


@app.route("/api/meetings/<meeting_id>/agenda", methods=["PUT"])
def set_meeting_agenda(meeting_id: str):
    body = request.get_json(force=True)
    items = body.get("items", [])
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400

    def mutate(store):
        if not _meeting_exists(store, meeting_id):
            return None
        meetings_lib.append_set_agenda(store, meeting_id, items)
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: set agenda {meeting_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/sessions", methods=["POST"])
def add_meeting_session(meeting_id: str):
    body = request.get_json(force=True)
    if not body or not body.get("body"):
        return jsonify({"error": "body is required"}), 400
    session_date = body.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def mutate(store):
        if not _meeting_exists(store, meeting_id):
            return None
        meetings_lib.append_add_session(store, meeting_id, session_date, body["body"])
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: add session {meeting_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})
```

- [ ] **Step 2: Smoke test**

With the server running (uses the `sales_marketing_weekly` meeting from Task 5; if absent, create it first):

```bash
curl -s -X PUT http://localhost:8787/api/meetings/sales_marketing_weekly/agenda \
  -H "Content-Type: application/json" -d '{"items":["Discuss Q3 launch","Review lead routing"]}' | python3 -m json.tool
# Expected: meeting with agenda=["Discuss Q3 launch","Review lead routing"]

curl -s -X POST http://localhost:8787/api/meetings/sales_marketing_weekly/sessions \
  -H "Content-Type: application/json" -d '{"date":"2026-06-15","body":"Talked launch timing."}' | python3 -m json.tool
# Expected: meeting with one session (date 2026-06-15, body "Talked launch timing.")

curl -s -X POST http://localhost:8787/api/meetings/does-not-exist/sessions \
  -H "Content-Type: application/json" -d '{"body":"x"}' | python3 -m json.tool
# Expected: {"error":"not found"} with 404
```

- [ ] **Step 3: Commit**

```bash
git add tools/server.py
git commit -m "feat: PUT agenda + POST session endpoints for meetings"
```

---

## Task 7: `tools/server.py` — thread CRUD + promote-to-task

**Files:**
- Modify: `tools/server.py` (in the `# --- Meetings ---` section)

- [ ] **Step 1: Add thread endpoints**

```python
@app.route("/api/meetings/<meeting_id>/threads", methods=["POST"])
def add_meeting_thread(meeting_id: str):
    body = request.get_json(force=True)
    if not body or not body.get("text"):
        return jsonify({"error": "text is required"}), 400

    def mutate(store):
        if not _meeting_exists(store, meeting_id):
            return None
        meetings_lib.append_add_thread(store, meeting_id, body["text"], person_id=body.get("person_id"))
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: add thread {meeting_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/threads/<thread_id>", methods=["PATCH"])
def patch_meeting_thread(meeting_id: str, thread_id: str):
    body = request.get_json(force=True)
    patch = {k: v for k, v in body.items() if k in ("text", "person_id", "task_id", "closed")}
    # auto-stamp closed_date when closing
    if patch.get("closed") is True and "closed_date" not in patch:
        patch["closed_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if patch.get("closed") is False:
        patch["closed_date"] = None

    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        if not mtg or not any(t["thread_id"] == thread_id for t in mtg["threads"]):
            return None
        meetings_lib.append_update_thread(store, meeting_id, thread_id, **patch)
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: update thread {thread_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/threads/<thread_id>", methods=["DELETE"])
def delete_meeting_thread(meeting_id: str, thread_id: str):
    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        if not mtg or not any(t["thread_id"] == thread_id for t in mtg["threads"]):
            return None
        meetings_lib.append_delete_thread(store, meeting_id, thread_id)
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: delete thread {thread_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})
```

- [ ] **Step 2: Add the promote-to-task endpoint**

```python
@app.route("/api/meetings/<meeting_id>/threads/<thread_id>/promote", methods=["POST"])
def promote_thread_to_task(meeting_id: str, thread_id: str):
    body = request.get_json(force=True) or {}

    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        thread = next((t for t in (mtg["threads"] if mtg else []) if t["thread_id"] == thread_id), None)
        if thread is None:
            return None
        task = tasks_lib.add_task(
            store,
            title=thread["text"],
            source=f"meeting-{meeting_id}",
            due_date=body.get("due_date"),
            owner=thread.get("person_id"),
            metadata={"meeting_id": meeting_id, "thread_id": thread_id},
        )
        meetings_lib.append_update_thread(store, meeting_id, thread_id, task_id=task["id"])
        return {"task": task, "meeting": _meeting_doc_after_write(store, meeting_id)}

    result, push, status = _write_main(mutate, lambda r: f"data: promote thread {thread_id} -> task {r['task']['id']}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"task": result["task"], "meeting": result["meeting"], "push": push}), 201
```

- [ ] **Step 3: Smoke test**

With the server running (using `sales_marketing_weekly`):

```bash
# add a thread, capture its thread_id from the response
curl -s -X POST http://localhost:8787/api/meetings/sales_marketing_weekly/threads \
  -H "Content-Type: application/json" -d '{"text":"Send Luke the Q3 deck","person_id":"luke-green"}' | python3 -m json.tool
# Expected: meeting with one open thread; note the thread_id (th-xxxxxx)

TID="th-xxxxxx"   # replace with the real id

# promote it to a task
curl -s -X POST "http://localhost:8787/api/meetings/sales_marketing_weekly/threads/$TID/promote" \
  -H "Content-Type: application/json" -d '{}' | python3 -m json.tool
# Expected: {"task":{"id":"t-...","title":"Send Luke the Q3 deck",...}, "meeting":{...thread now has task_id...}}

# close the thread
curl -s -X PATCH "http://localhost:8787/api/meetings/sales_marketing_weekly/threads/$TID" \
  -H "Content-Type: application/json" -d '{"closed":true}' | python3 -m json.tool
# Expected: thread closed=true with closed_date=today

# verify the task landed in the Work tab
curl -s http://localhost:8787/api/tasks | python3 -m json.tool | grep -A2 "Send Luke"
# Expected: the task present with source "meeting-sales_marketing_weekly"
```

- [ ] **Step 4: Commit**

```bash
git add tools/server.py
git commit -m "feat: thread CRUD + promote-to-task endpoints for meetings"
```

---

## Task 8: `tools/registry_ui.html` — Meetings tab (HTML + CSS)

**Files:**
- Modify: `tools/registry_ui.html` — nav tabs, `<main>` views, `<style>` block.

- [ ] **Step 1: Add the tab button + view div**

Find the nav tabs (search for `data-view="notes"`). After the Notes tab button, add:

```html
      <button class="tab" data-view="meetings">Meetings</button>
```

After the `<div id="view-notes" ...>` element, add:

```html
      <div id="view-meetings" class="view hidden"></div>
```

- [ ] **Step 2: Add CSS before `</style>`**

```css
    /* ── Meetings tab ── */
    .mtg-layout { display: flex; gap: 16px; padding: 12px 0; }
    .mtg-list { flex: 0 0 220px; display: flex; flex-direction: column; gap: 4px; }
    .mtg-list-item {
      padding: 8px 10px; border: 1px solid var(--border); border-radius: 4px;
      cursor: pointer; font-size: 13px; color: var(--text); background: var(--surface);
    }
    .mtg-list-item:hover { background: var(--surface2); }
    .mtg-list-item.active { border-color: var(--accent); background: var(--surface2); }
    .mtg-list-item .mtg-list-sub { font-size: 10px; color: var(--muted); margin-top: 2px; }
    .mtg-new-btn {
      margin-top: 6px; font-size: 12px; color: var(--muted); background: transparent;
      border: 1px dashed var(--border); padding: 6px; border-radius: 4px; cursor: pointer;
    }
    .mtg-new-btn:hover { border-color: var(--accent); color: var(--text); }
    .mtg-doc { flex: 1; min-width: 0; }
    .mtg-doc-header { border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 12px; }
    .mtg-doc-title { font-size: 18px; font-weight: 600; color: var(--text); }
    .mtg-doc-people { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
    .mtg-person-chip {
      font-size: 11px; padding: 2px 8px; border-radius: 12px; cursor: pointer;
      border: 1px solid var(--border); color: var(--muted); background: transparent;
    }
    .mtg-person-chip:hover { color: var(--text); border-color: var(--accent); }
    .mtg-zone { margin-bottom: 20px; }
    .mtg-zone-title {
      font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase;
      letter-spacing: .06em; margin-bottom: 8px;
    }
    .mtg-agenda-item, .mtg-thread {
      display: flex; align-items: flex-start; gap: 8px; padding: 5px 0;
      border-bottom: 1px solid var(--border);
    }
    .mtg-agenda-item .mtg-text, .mtg-thread .mtg-text {
      flex: 1; font-size: 13px; color: var(--text); line-height: 1.4;
    }
    .mtg-thread.closed .mtg-text { text-decoration: line-through; color: var(--muted); }
    .mtg-row-btn {
      font-size: 11px; color: var(--muted); background: transparent; border: none;
      cursor: pointer; padding: 1px 5px; border-radius: 3px;
    }
    .mtg-row-btn:hover { color: var(--text); background: var(--surface2); }
    .mtg-row-btn.linked { color: var(--accent); cursor: default; }
    .mtg-add-input {
      width: 100%; box-sizing: border-box; background: var(--surface2);
      border: 1px solid var(--border); color: var(--text); padding: 6px 8px;
      border-radius: 3px; font-size: 13px; outline: none; margin-top: 6px; font-family: inherit;
    }
    .mtg-add-input:focus { border-color: var(--accent); }
    .mtg-session { padding: 8px 0; border-bottom: 1px solid var(--border); }
    .mtg-session-date { font-size: 11px; color: var(--muted); margin-bottom: 3px; }
    .mtg-session-body { font-size: 13px; color: var(--text); white-space: pre-wrap; line-height: 1.5; }
    .mtg-thread-owner { font-size: 10px; color: var(--accent); }
    .mtg-empty { color: var(--muted); font-size: 12px; padding: 6px 0; }
```

- [ ] **Step 3: Verify HTML loads with no console errors**

```bash
python tools/server.py
# Open http://localhost:8787, click the "Meetings" tab.
# Expected: a 6th tab appears; clicking it shows an empty container (JS comes next); no console errors.
```

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: Meetings tab HTML structure and CSS"
```

---

## Task 9: `tools/registry_ui.html` — Meetings render + editing JS

**Files:**
- Modify: `tools/registry_ui.html` (inside the `<script type="module">` block, before `</script>`).

> This task wires the tab. It assumes the existing helpers `el(id)`, `esc(str)`, `fetchJSON(url)`, and `API` exist (used by the Notes tab) and that tab-switching calls a render function by view name. Confirm the tab-switch dispatch (search for `view-notes` / `renderNotesView`) and add a `meetings` case that calls `renderMeetingsView()`.

- [ ] **Step 1: Add state + the list/doc renderer**

Add before `</script>`:

```javascript
// ── Meetings tab ──────────────────────────────────────────────────────────────
const meetingsState = { selectedId: null, _people: [] };

async function renderMeetingsView() {
  const view = el('view-meetings');
  view.innerHTML = '<div class="muted" style="padding:20px">Loading…</div>';
  let meetings, people;
  try {
    [meetings, people] = await Promise.all([
      fetchJSON(`${API}/api/meetings`),
      fetchJSON(`${API}/api/people`),
    ]);
  } catch {
    view.innerHTML = `<div class="empty-state"><h3>Server Offline</h3><p>Run: python tools/server.py</p></div>`;
    return;
  }
  meetingsState._people = people;
  if (!meetingsState.selectedId && meetings.length) meetingsState.selectedId = meetings[0].id;
  const selected = meetings.find(m => m.id === meetingsState.selectedId) || null;

  const listHtml = meetings.map(m => {
    const active = m.id === meetingsState.selectedId ? ' active' : '';
    const open = (m.threads || []).filter(t => !t.closed).length;
    return `<div class="mtg-list-item${active}" data-mtg-id="${esc(m.id)}">
      ${esc(m.name)}
      <div class="mtg-list-sub">${open} open thread${open === 1 ? '' : 's'}</div>
    </div>`;
  }).join('');

  view.innerHTML = `
    <div class="mtg-layout">
      <div class="mtg-list">
        ${listHtml || '<div class="mtg-empty">No meetings yet.</div>'}
        <button class="mtg-new-btn" id="mtg-new-btn">+ New Meeting</button>
      </div>
      <div class="mtg-doc" id="mtg-doc">${selected ? renderMeetingDoc(selected) : '<div class="mtg-empty">Select a meeting.</div>'}</div>
    </div>`;

  view.querySelectorAll('.mtg-list-item').forEach(item =>
    item.addEventListener('click', () => { meetingsState.selectedId = item.dataset.mtgId; renderMeetingsView(); }));
  el('mtg-new-btn').addEventListener('click', openNewMeetingModal);
  if (selected) wireMeetingDoc(selected);
}

function _personName(pid) {
  const p = meetingsState._people.find(x => x.id === pid);
  return p ? p.name : pid;
}

function renderMeetingDoc(m) {
  const peopleChips = (m.people_ids || []).map(pid =>
    `<span class="mtg-person-chip" data-person-id="${esc(pid)}">${esc(_personName(pid))}</span>`).join('');

  const agendaHtml = (m.agenda || []).map((item, i) => `
    <div class="mtg-agenda-item">
      <div class="mtg-text">${esc(item)}</div>
      <button class="mtg-row-btn" data-agenda-del="${i}">✕</button>
    </div>`).join('') || '<div class="mtg-empty">No agenda items yet.</div>';

  const today = new Date().toISOString().slice(0, 10);
  const cutoff = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  const visibleThreads = (m.threads || []).filter(t => !t.closed || (t.closed_date && t.closed_date >= cutoff));
  const threadsHtml = visibleThreads.map(t => `
    <div class="mtg-thread${t.closed ? ' closed' : ''}" data-thread-id="${esc(t.thread_id)}">
      <input type="checkbox" data-thread-toggle ${t.closed ? 'checked' : ''} />
      <div class="mtg-text">${esc(t.text)}${t.person_id ? ` <span class="mtg-thread-owner">→ ${esc(_personName(t.person_id))}</span>` : ''}</div>
      ${t.task_id
        ? `<button class="mtg-row-btn linked" title="Linked to ${esc(t.task_id)}">↗ linked</button>`
        : `<button class="mtg-row-btn" data-thread-promote title="Make a task">↗ task</button>`}
      <button class="mtg-row-btn" data-thread-del>✕</button>
    </div>`).join('') || '<div class="mtg-empty">No open threads.</div>';

  const sessionsHtml = (m.sessions || []).map(s => `
    <div class="mtg-session">
      <div class="mtg-session-date">${esc(s.date)}</div>
      <div class="mtg-session-body">${esc(s.body)}</div>
    </div>`).join('') || '<div class="mtg-empty">No sessions logged.</div>';

  return `
    <div class="mtg-doc-header">
      <div class="mtg-doc-title">${esc(m.name)}</div>
      <div class="mtg-doc-people">${peopleChips}</div>
    </div>
    <div class="mtg-zone">
      <div class="mtg-zone-title">Agenda</div>
      ${agendaHtml}
      <input class="mtg-add-input" id="mtg-agenda-add" placeholder="Add a talking point and press Enter…" />
    </div>
    <div class="mtg-zone">
      <div class="mtg-zone-title">Open Threads</div>
      ${threadsHtml}
      <input class="mtg-add-input" id="mtg-thread-add" placeholder="Add an open thread and press Enter…" />
    </div>
    <div class="mtg-zone">
      <div class="mtg-zone-title">Session Log</div>
      <textarea class="mtg-add-input" id="mtg-session-add" rows="2" placeholder="Add today's session notes, then click Save Session…"></textarea>
      <button class="mtg-row-btn" id="mtg-session-save" style="border:1px solid var(--border);padding:4px 10px;margin-top:4px">Save Session</button>
      <div style="margin-top:10px">${sessionsHtml}</div>
    </div>`;
}
```

- [ ] **Step 2: Add the doc wiring (editing actions)**

```javascript
function wireMeetingDoc(m) {
  const doc = el('mtg-doc');

  async function patchMeeting(method, path, payload) {
    const res = await fetch(`${API}/api/meetings/${m.id}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    if (!res.ok) { alert('Save failed (server offline or push error).'); return null; }
    return res.json();
  }

  // person chips → navigate to People tab (best-effort: switch tab if helper exists)
  doc.querySelectorAll('.mtg-person-chip').forEach(chip =>
    chip.addEventListener('click', () => { if (window.openPerson) window.openPerson(chip.dataset.personId); }));

  // Agenda: add on Enter
  const agendaAdd = el('mtg-agenda-add');
  agendaAdd.addEventListener('keydown', async e => {
    if (e.key === 'Enter' && agendaAdd.value.trim()) {
      const items = [...(m.agenda || []), agendaAdd.value.trim()];
      if (await patchMeeting('PUT', '/agenda', { items })) renderMeetingsView();
    }
  });
  // Agenda: delete
  doc.querySelectorAll('[data-agenda-del]').forEach(btn =>
    btn.addEventListener('click', async () => {
      const idx = Number(btn.dataset.agendaDel);
      const items = (m.agenda || []).filter((_, i) => i !== idx);
      if (await patchMeeting('PUT', '/agenda', { items })) renderMeetingsView();
    }));

  // Threads: add on Enter
  const threadAdd = el('mtg-thread-add');
  threadAdd.addEventListener('keydown', async e => {
    if (e.key === 'Enter' && threadAdd.value.trim()) {
      if (await patchMeeting('POST', '/threads', { text: threadAdd.value.trim() })) renderMeetingsView();
    }
  });
  // Threads: toggle closed / promote / delete
  doc.querySelectorAll('.mtg-thread').forEach(row => {
    const tid = row.dataset.threadId;
    const toggle = row.querySelector('[data-thread-toggle]');
    if (toggle) toggle.addEventListener('change', async () => {
      if (await patchMeeting('PATCH', `/threads/${tid}`, { closed: toggle.checked })) renderMeetingsView();
    });
    const promote = row.querySelector('[data-thread-promote]');
    if (promote) promote.addEventListener('click', async () => {
      if (await patchMeeting('POST', `/threads/${tid}/promote`, {})) renderMeetingsView();
    });
    const del = row.querySelector('[data-thread-del]');
    if (del) del.addEventListener('click', async () => {
      if (await patchMeeting('DELETE', `/threads/${tid}`, {})) renderMeetingsView();
    });
  });

  // Session: save
  el('mtg-session-save').addEventListener('click', async () => {
    const body = el('mtg-session-add').value.trim();
    if (!body) return;
    if (await patchMeeting('POST', '/sessions', { body })) renderMeetingsView();
  });
}
```

- [ ] **Step 3: Wire the tab dispatch**

Find where the Notes tab is dispatched on tab switch (search for `renderNotesView`). Add a sibling branch so clicking the Meetings tab calls `renderMeetingsView()`. For example, if the dispatch is a `switch`/`if` on the view name:

```javascript
      else if (view === 'meetings') renderMeetingsView();
```

- [ ] **Step 4: Manual verification**

```bash
python tools/server.py
# Open http://localhost:8787 → Meetings tab.
# Expected: left list of 6 meetings; clicking one shows Agenda / Open Threads / Session Log.
# Add an agenda item (type + Enter) → it appears.
# Add a thread → appears; check its box → it strikes through; ↗ task → creates a task (verify in Work tab).
# Type session notes → Save Session → entry appears under Session Log.
# Reload page → all changes persisted (they committed to origin/main).
```

- [ ] **Step 5: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: Meetings tab render + agenda/thread/session editing JS"
```

---

## Task 10: `tools/registry_ui.html` — New Meeting modal

**Files:**
- Modify: `tools/registry_ui.html` (HTML for the modal + JS).

- [ ] **Step 1: Add the modal HTML before `</body>`**

```html
  <div id="mtg-modal-overlay" class="note-modal-overlay hidden">
    <div class="note-modal">
      <div class="note-modal-header"><span>New Meeting</span>
        <button class="note-modal-close" id="mtg-modal-close">×</button></div>
      <div class="note-modal-body">
        <div class="note-field-label">Name</div>
        <input id="mtg-name-input" class="note-field-input" placeholder="e.g. Sales / Marketing Weekly" />
        <div class="note-field-label" style="margin-top:8px">Calendar match pattern (optional)</div>
        <input id="mtg-pattern-input" class="note-field-input" placeholder="e.g. sales sync (matches calendar event titles)" />
        <div class="note-field-label" style="margin-top:8px">People (optional)</div>
        <div class="note-picker-wrap">
          <input id="mtg-person-input" class="note-field-input" placeholder="Search people…" autocomplete="off" />
          <div id="mtg-person-dropdown" class="note-picker-dropdown hidden"></div>
        </div>
        <div id="mtg-people-chosen" class="note-modal-tag-chips" style="margin-top:6px"></div>
      </div>
      <div class="note-modal-footer">
        <div class="note-modal-footer-left"></div>
        <div class="note-modal-footer-right">
          <button id="mtg-modal-cancel" class="btn-cancel">Cancel</button>
          <button id="mtg-modal-save" class="btn-save">Create</button>
        </div>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Add the modal JS before `</script>`**

```javascript
// ── New Meeting modal ────────────────────────────────────────────────────────
const newMeetingState = { peopleIds: [] };

function openNewMeetingModal() {
  newMeetingState.peopleIds = [];
  el('mtg-name-input').value = '';
  el('mtg-pattern-input').value = '';
  el('mtg-person-input').value = '';
  el('mtg-people-chosen').innerHTML = '';
  el('mtg-person-dropdown').classList.add('hidden');
  el('mtg-modal-overlay').classList.remove('hidden');
  el('mtg-name-input').focus();
}
function closeNewMeetingModal() { el('mtg-modal-overlay').classList.add('hidden'); }

function _renderChosenPeople() {
  el('mtg-people-chosen').innerHTML = newMeetingState.peopleIds.map(pid =>
    `<span class="note-tag-chip-toggle selected" data-remove="${esc(pid)}">${esc(_personName(pid))} ✕</span>`).join('');
  el('mtg-people-chosen').querySelectorAll('[data-remove]').forEach(c =>
    c.addEventListener('click', () => {
      newMeetingState.peopleIds = newMeetingState.peopleIds.filter(p => p !== c.dataset.remove);
      _renderChosenPeople();
    }));
}

function wireNewMeetingModal() {
  el('mtg-modal-close').addEventListener('click', closeNewMeetingModal);
  el('mtg-modal-cancel').addEventListener('click', closeNewMeetingModal);

  const input = el('mtg-person-input');
  const dropdown = el('mtg-person-dropdown');
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase().trim();
    dropdown.innerHTML = ''; dropdown.classList.add('hidden');
    if (!q) return;
    const matches = meetingsState._people
      .filter(p => p.name.toLowerCase().includes(q) && !newMeetingState.peopleIds.includes(p.id))
      .slice(0, 8);
    if (!matches.length) return;
    dropdown.innerHTML = matches.map(p =>
      `<div class="note-picker-option" data-pid="${esc(p.id)}">${esc(p.name)}</div>`).join('');
    dropdown.classList.remove('hidden');
    dropdown.querySelectorAll('[data-pid]').forEach(opt =>
      opt.addEventListener('click', () => {
        newMeetingState.peopleIds.push(opt.dataset.pid);
        input.value = ''; dropdown.classList.add('hidden');
        _renderChosenPeople();
      }));
  });

  el('mtg-modal-save').addEventListener('click', async () => {
    const name = el('mtg-name-input').value.trim();
    if (!name) { el('mtg-name-input').focus(); return; }
    const payload = {
      name,
      calendar_pattern: el('mtg-pattern-input').value.trim(),
      people_ids: newMeetingState.peopleIds,
    };
    const res = await fetch(`${API}/api/meetings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!res.ok) { alert('Create failed (server offline or push error).'); return; }
    const data = await res.json();
    closeNewMeetingModal();
    meetingsState.selectedId = data.id;
    renderMeetingsView();
  });
}
wireNewMeetingModal();
```

> `wireNewMeetingModal()` is called once at load (the modal elements are static). `openNewMeetingModal` is already bound to the `+ New Meeting` button in Task 9 Step 1.

- [ ] **Step 3: Manual verification**

```bash
python tools/server.py
# Open http://localhost:8787 → Meetings → "+ New Meeting".
# Fill name "Test Sync", add a person, Create.
# Expected: modal closes; new meeting is selected and shows empty zones; appears in the left list.
# Reload → still present (committed to origin/main).
```

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat: New Meeting modal with people picker"
```

---

## Task 11: Repoint brief + prep to `lib/meetings.py`

**Files:**
- Modify: `pipeline.py:35` (import), `pipeline.py:151-164` (`build_meeting_prep`)
- Modify: `processors/meeting_prep.py:355-362` (`build_recurring_internal_context`)
- Test: `tests/test_meeting_prep_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meeting_prep_integration.py
import json
from pathlib import Path
import lib.meetings as m


class _DirStore:
    """LocalStorage-like store over a tmp data dir (read/append_line only)."""
    def __init__(self, base): self.base = Path(base)
    def read(self, key):
        p = self.base / key
        return p.read_text() if p.exists() else None
    def append_line(self, key, line):
        p = self.base / key
        existing = p.read_text() if p.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        p.write_text(existing + line + "\n")


def test_last_session_from_store(tmp_path):
    store = _DirStore(tmp_path)
    m.append_create(store, "luke_1on1")
    m.append_add_session(store, "luke_1on1", "2026-06-08", "discussed roadmap")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert m.last_session(state["luke_1on1"]) == "discussed roadmap"


def test_render_for_prep_from_store(tmp_path):
    store = _DirStore(tmp_path)
    m.append_create(store, "luke_1on1")
    m.append_add_thread(store, "luke_1on1", "chase hire backfill", person_id="luke-green")
    m.append_add_session(store, "luke_1on1", "2026-06-08", "talked shop")
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    out = m.render_for_prep(state["luke_1on1"])
    assert "chase hire backfill" in out
    assert "talked shop" in out
```

- [ ] **Step 2: Run test to confirm it passes** (these exercise lib.meetings only — they should pass already; they lock the contract the integration relies on)

```bash
python -m pytest tests/test_meeting_prep_integration.py -v
```
Expected: PASS.

- [ ] **Step 3: Update `pipeline.py` import + `build_meeting_prep`**

Change `pipeline.py:35` from:
```python
from processors.meeting_memory import load_meeting_index, find_meeting_for_event, load_last_session_summary
```
to:
```python
from processors.meeting_memory import load_meeting_index, find_meeting_for_event
import lib.meetings as meetings_lib
```

Replace `build_meeting_prep` (`pipeline.py:151-164`):

```python
def build_meeting_prep(today_events, meeting_configs, storage) -> list[str]:
    prep = []
    state = meetings_lib.replay_meetings_content(storage.read("meetings.jsonl") or "")
    for event in today_events:
        config = find_meeting_for_event(event, meeting_configs)
        if not config:
            continue
        mtg = state.get(config.meeting_id, {"sessions": []})
        last_summary = meetings_lib.last_session(mtg)
        if last_summary:
            preview = last_summary[:200] + ("..." if len(last_summary) > 200 else "")
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — Last session: {preview}")
        else:
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — No prior session notes")
    return prep
```

- [ ] **Step 4: Update `processors/meeting_prep.py` recurring-internal context**

Replace the meeting-memory read block (`processors/meeting_prep.py:355-362`):

```python
    meeting_index = load_meeting_index(config.get("meeting_index_file", "data/meeting_index.json"))
    meeting_cfg = find_meeting_for_event(event, meeting_index)

    if meeting_cfg:
        import lib.meetings as meetings_lib
        state = meetings_lib.replay_meetings_content(storage.read("meetings.jsonl") or "")
        mtg = state.get(meeting_cfg.meeting_id)
        if mtg:
            rendered = meetings_lib.render_for_prep(mtg)
            if rendered.strip():
                parts.append(rendered.strip())
```

- [ ] **Step 5: Verify imports + a dry brief run**

```bash
python -c "import pipeline; from processors.meeting_prep import build_recurring_internal_context; print('ok')"
python main.py --no-email 2>&1 | tail -20
```
Expected: `ok`; the dry brief run completes without a traceback (meeting prep lines render from `meetings.jsonl`).

- [ ] **Step 6: Commit**

```bash
git add pipeline.py processors/meeting_prep.py tests/test_meeting_prep_integration.py
git commit -m "feat: brief + prep read meeting docs from lib/meetings"
```

---

## Task 12: Repoint nudge-reply capture (append-only, no AI rewrite)

**Files:**
- Modify: `reply_collector.py:13` (import), `:90-104` (capture block)
- Modify: `ask.py:15` (import), `:95-99` (capture block)

- [ ] **Step 1: Update `reply_collector.py`**

Change the import (`reply_collector.py:13`) from:
```python
from processors.meeting_memory import append_session_notes, rewrite_meeting_memory
```
to:
```python
import lib.meetings as meetings_lib
```

Replace the capture block (`reply_collector.py:90-104`). The new behavior appends a session event only — the Option-1 safety change (no full rewrite). The meeting slug comes from the stored `memory_file`:

```python
        reply_text = get_latest_reply_text(thread_id, profile)
        if reply_text.strip():
            meeting_id = memory_file.rsplit("/", 1)[-1].removesuffix(".md")
            meetings_lib.append_add_session(storage, meeting_id, nudge["session_date"], reply_text.strip())
            print(f"  Captured notes for: {nudge['meeting_name']}")
        else:
            still_pending.append(nudge)
```

(The `api_key` / `model` branch is removed; `api_key` may now be unused in `run()` — leave the variable, it is harmless, or remove the line `api_key = os.environ.get("ANTHROPIC_API_KEY", "")` if no other code uses it.)

- [ ] **Step 2: Update `ask.py`**

Change the import (`ask.py:15`) from:
```python
from processors.meeting_memory import append_session_notes
```
to:
```python
import lib.meetings as meetings_lib
```

Replace the append block (`ask.py:95-99`):

```python
            memory_key = nudge.get("memory_file", "")
            if memory_key:
                meeting_id = memory_key.rsplit("/", 1)[-1].removesuffix(".md")
            else:
                meeting_id = nudge["meeting_name"].lower().replace(" ", "_")[:40]
            meetings_lib.append_add_session(storage, meeting_id, nudge["session_date"], query)
```

- [ ] **Step 3: Verify imports**

```bash
python -c "import reply_collector, ask; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Functional check (replay round-trip with a DirStore)**

```bash
python - <<'PY'
import tempfile, lib.meetings as m
from pathlib import Path
class S:
    def __init__(s,b): s.b=Path(b)
    def read(s,k):
        p=s.b/k; return p.read_text() if p.exists() else None
    def append_line(s,k,l):
        p=s.b/k; e=p.read_text() if p.exists() else ""
        if e and not e.endswith("\n"): e+="\n"
        p.write_text(e+l+"\n")
d=tempfile.mkdtemp(); st=S(d)
m.append_create(st,"luke_1on1")
m.append_add_session(st,"luke_1on1","2026-06-15","reply text from nudge")
state=m.replay_meetings_content(st.read("meetings.jsonl"))
assert state["luke_1on1"]["sessions"][0]["body"]=="reply text from nudge"
print("ok: nudge reply appends a session, no rewrite")
PY
```
Expected: `ok: nudge reply appends a session, no rewrite`.

- [ ] **Step 5: Commit**

```bash
git add reply_collector.py ask.py
git commit -m "feat: nudge replies append a session event (no full AI rewrite)"
```

---

## Task 13: Full regression + branch wrap-up

**Files:** none (verification)

- [ ] **Step 1: Run the full test suite**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest -q 2>&1 | tail -25
```
Expected: all tests pass (including the new `test_meetings_lib.py`, `test_meeting_config.py`, `test_meeting_prep_integration.py`).

- [ ] **Step 2: Confirm legacy `rewrite_meeting_memory` is no longer referenced**

```bash
grep -rn "rewrite_meeting_memory\|append_session_notes\|load_last_session_summary" *.py processors/ | grep -v "def "
```
Expected: no remaining call sites (definitions in `processors/meeting_memory.py` may remain unused; that is fine — leave them or remove in a follow-up).

- [ ] **Step 3: End-to-end UI smoke (server running)**

```bash
python tools/server.py
# Meetings tab: create a meeting, add agenda items, add + close threads, promote a thread to a task,
# add a session, reload to confirm persistence. Confirm the promoted task appears in the Work tab.
```

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/meetings-agenda-surface
```

- [ ] **Step 5: Open a PR** (server-side merge keeps local `main` from going ahead of `origin/main`, per CLAUDE.md)

```bash
gh pr create --title "Meetings agenda surface (Project 1)" \
  --body "$(cat <<'EOF'
## Summary
- New Meetings tab in the Registry UI: per-meeting Agenda / Open Threads / Session Log
- Event-sourced data/meetings.jsonl (merge=union); config in meeting_index.json (name, people_ids)
- Promote-to-task into the Work tab; multi-person links
- Nudge replies now append a Session Log entry only (no full AI rewrite) — manual Agenda/Threads are safe
- Brief + meeting prep repointed from meeting_memory/*.md to lib/meetings.py
- One-time migration of the 6 legacy meeting_memory docs

Project 2 (move nudge/reply channel Telegram → Slack) is a separate follow-on.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review notes (for the implementer)

- **Closed-thread window:** enforced in the UI (`renderMeetingDoc` hides threads closed >7 days ago) and in `render_for_prep` (open threads only). Replay keeps everything — the event log is the source of truth.
- **Concurrency:** `data/meetings.jsonl merge=union` (Task 3) makes the AI session-append and live UI edits conflict-free, exactly as `tasks.jsonl`/`notes.jsonl`.
- **Non-fatal AI path:** Task 12 removes the AI rewrite entirely; the reply path now only appends text, so there is no AI call to fail in Project 1.
- **Legacy markdown:** `meeting_memory/*.md` files are left in place but no longer read after Task 11; a follow-up may delete them once the migration is confirmed on `main`.
