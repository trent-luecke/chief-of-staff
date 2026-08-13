#!/usr/bin/env python3
"""Deterministic helpers for the local Cowork → Notion sync routine.

The routine (an in-app scheduled task) calls these subcommands around the LLM
steps that write to Notion via the updater skills:

  fresh-entries    → JSON list of queue entries not yet applied (reads origin/main)
  mark-seen <id>…  → record ids as applied (laptop-local seen-set)
  record-pending   → hold an unmatched onboarding entry for the confirm loop
  summary          → post the morning Slack summary

Never writes to git. The seen-set and pending store are laptop-local (gitignored
under data/state/).
"""
import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from lib.notion_queue import parse_jsonl  # noqa: E402

QUEUE_REPO_PATH = "data/notion_updates_queue.jsonl"
SEEN_PATH = _ROOT / "data" / "state" / "notion_updates_seen.json"
PENDING_PATH = _ROOT / "data" / "state" / "onboarding_pending_confirm.jsonl"


def fetch_main_ref() -> bool:
    from lib.git_sync import fetch_main
    return fetch_main()


def read_main_queue() -> str:
    from lib.git_sync import show_main
    return show_main(QUEUE_REPO_PATH) or ""


def _load_seen() -> set[str]:
    try:
        return set(json.loads(SEEN_PATH.read_text()))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def fresh_entries() -> list[dict]:
    fetch_main_ref()
    text = read_main_queue()
    seen = _load_seen()
    return [e for e in parse_jsonl(text) if e.get("id") not in seen]


def mark_seen(ids: list[str]) -> int:
    seen = _load_seen()
    before = len(seen)
    seen.update(i for i in ids if i)
    _save_seen(seen)
    return len(seen) - before


def record_pending(entry: dict) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {**entry, "status": "pending"}
    with open(PENDING_PATH, "a") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


def build_summary(payload: dict, today: str) -> str:
    applied = payload.get("applied", [])
    flagged = payload.get("flagged", [])
    pending = payload.get("pending", [])
    if not applied and not pending:
        return ""  # silent no-op
    lines = [f"📥 Notion Sync — {today}"]
    if flagged:
        lines.append("\n*⚠️ Review these:*")
        lines.extend(f"• {f}" for f in flagged)
    if pending:
        lines.append("\n*New onboarding customers with no record (add manually — auto-confirm lands in Phase 2):*")
        lines.extend(f"• {p.get('name')}" for p in pending)
    lines.append(f"\n_Synced {len(applied)} update(s) to Notion._")
    return "\n".join(lines)


def _post_summary(payload: dict, today: str, dry_run: bool) -> None:
    text = build_summary(payload, today)
    if not text:
        print("(nothing synced — no summary posted)")
        return
    if dry_run:
        print(text)
        return
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    with open(_ROOT / "config.json") as f:
        config = json.load(f)
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    user_id = config.get("avoma", {}).get("slack_user_id", "")
    from lib.slack_post import open_dm, post_message
    channel = open_dm(token, user_id)
    post_message(token, channel, text)
    print("Slack summary posted.")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fresh-entries")
    ms = sub.add_parser("mark-seen")
    ms.add_argument("ids", nargs="+")
    rp = sub.add_parser("record-pending")
    rp.add_argument("--json", help="entry JSON; reads stdin if omitted")
    su = sub.add_parser("summary")
    su.add_argument("--today", required=True)
    su.add_argument("--json", help="payload JSON; reads stdin if omitted")
    su.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.cmd == "fresh-entries":
        print(json.dumps(fresh_entries()))
    elif args.cmd == "mark-seen":
        print(f"marked {mark_seen(args.ids)} new id(s) seen")
    elif args.cmd == "record-pending":
        record_pending(json.loads(args.json or sys.stdin.read()))
        print("pending recorded")
    elif args.cmd == "summary":
        _post_summary(json.loads(args.json or sys.stdin.read()), args.today, args.dry_run)


if __name__ == "__main__":
    main()
