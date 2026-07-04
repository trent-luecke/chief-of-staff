#!/usr/bin/env python3
"""Run a routine from the /routine Slack slash command. Called by routine_run.yml.

/routine            -> list routines
/routine <name>     -> fuzzy-match and run; records the nearest upcoming OOO
                       window's trigger_key when the routine has a calendar
                       trigger, so the brief's suggestion goes quiet.
"""
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import LocalStorage
from lib.routines import last_run_date, list_routines, ran_within, run_routine


def _post_json(response_url: str, payload: dict) -> None:
    if not response_url:
        return
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        response_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to post to Slack response_url: {e}", file=sys.stderr)


def post_to_slack(response_url: str, text: str) -> None:
    _post_json(response_url, {"response_type": "ephemeral", "text": text})


def match_routines(query: str, routines: list) -> list:
    """Case-insensitive substring match on name or id, either direction."""
    q = query.lower().strip()
    if not q:
        return []
    return [
        r for r in routines
        if q in r["name"].lower() or r["name"].lower() in q or q == r["id"]
    ]


def format_routine_list(routines: list) -> str:
    if not routines:
        return "No routines defined yet — create one in the Registry UI (Work tab)."
    lines = ["Routines:"]
    for r in routines:
        n = len(r.get("steps") or [])
        trig = " · auto-OOO" if (r.get("trigger") or {}).get("type") == "calendar_ooo" else ""
        lines.append(f"• {r['name']} ({n} step{'s' if n != 1 else ''}{trig}) — `/routine {r['name']}`")
    return "\n".join(lines)


def format_run_confirmation(routine: dict, tasks: list, note: Optional[str] = None) -> str:
    lines = [f"Ran '{routine['name']}' — created {len(tasks)} task{'s' if len(tasks) != 1 else ''}:"]
    lines += [f"• {t['title']}" for t in tasks]
    if note:
        lines.append(note)
    return "\n".join(lines)


def detect_trigger_key(routine: dict) -> Optional[str]:
    """Nearest upcoming OOO window's key for a calendar-triggered routine.

    Non-fatal: any calendar failure returns None and the run proceeds unkeyed.
    """
    trig = routine.get("trigger") or {}
    if trig.get("type") != "calendar_ooo":
        return None
    try:
        from lib.google_auth import build_calendar_service
        from lib.ooo import detect_ooo_windows, trigger_key
        windows = [
            w for w in detect_ooo_windows(build_calendar_service(), int(trig.get("lead_days", 7)))
            if w.start >= date.today()
        ]
        if not windows:
            return None
        return trigger_key(min(windows, key=lambda w: w.start))
    except Exception as e:
        print(f"Warning: trigger detection failed (running without trigger_key): {e}", file=sys.stderr)
        return None


def main():
    query = os.environ.get("ROUTINE_QUERY", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "")
    storage = LocalStorage(base_dir=str(ROOT / "data"))
    routines = list_routines(storage)

    if not query:
        msg = format_routine_list(routines)
        post_to_slack(response_url, msg)
        print(msg)
        return

    matches = match_routines(query, routines)
    if not matches:
        msg = f"No routine matches '{query}'.\n" + format_routine_list(routines)
        post_to_slack(response_url, msg)
        print(msg)
        return
    if len(matches) > 1:
        options = ", ".join(f"`/routine {r['name']}`" for r in matches)
        msg = f"'{query}' matches multiple routines — be more specific: {options}"
        post_to_slack(response_url, msg)
        print(msg)
        return

    routine = matches[0]
    if not routine.get("steps"):
        msg = f"'{routine['name']}' has no steps — edit it in the Registry UI first."
        post_to_slack(response_url, msg)
        print(msg)
        return

    note = None
    if ran_within(routine, days=7):
        note = f"_Note: this routine last ran {last_run_date(routine)}._"

    result = run_routine(storage, routine["id"], source="slack",
                         trigger_key=detect_trigger_key(routine))
    confirmation = format_run_confirmation(result["routine"], result["tasks"], note)
    post_to_slack(response_url, confirmation)
    print(confirmation)


if __name__ == "__main__":
    main()
