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
