#!/usr/bin/env python3
"""Lightweight Avoma access point for quick lookups — NO analysis pipeline.

Two modes:
  list        List meetings in a date window (subject, start, uuid, attendees).
  transcript  Print the ordered, speaker-labeled transcript for one meeting.

Auth: reads AVOMA_API_KEY from .env (or the shell env) in the project root.

Timezone gotcha: Avoma `start_at` is UTC. Trent is US Central (CDT = UTC-5
in summer, CST = UTC-6 in winter). `--date 2026-06-24` queries a UTC window
padded on both ends so meetings near local midnight aren't missed.

Examples:
  python3 .claude/skills/query-avoma/query_avoma.py list --date 2026-06-24
  python3 .claude/skills/query-avoma/query_avoma.py list --date 2026-06-24 --title "Mark Fisher"
  python3 .claude/skills/query-avoma/query_avoma.py transcript --uuid 5835ccc6-df0e-40d6-98ac-59f9fba03deb
"""
import argparse
import os
import sys
import time

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_URL = "https://api.avoma.com"
TIMEOUT = 60


MAX_PAGES = 200
MAX_RETRIES = 6


def _get(url, params):
    """GET with polite retries on Avoma's rate limit (429) and 5xx, honoring Retry-After."""
    for attempt in range(MAX_RETRIES + 1):
        resp = requests.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        if getattr(resp, "status_code", 200) in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
            wait = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
            time.sleep(min(int(wait) if wait and str(wait).isdigit() else 2 ** attempt * 5, 120))
            continue
        resp.raise_for_status()
        return resp


def _key() -> str:
    key = os.environ.get("AVOMA_API_KEY")
    if not key:
        sys.exit("AVOMA_API_KEY not found in .env or shell env.")
    return key


def _headers() -> dict:
    return {"Authorization": f"Bearer {_key()}"}


def cmd_list(args) -> None:
    if args.date:
        # Pad the window: from 00:00Z of the day to 12:00Z the next day so
        # CDT/CST-shifted meetings near local midnight are still captured.
        from_date = f"{args.date}T00:00:00Z"
        d = args.date.split("-")
        nxt = f"{d[0]}-{d[1]}-{int(d[2]) + 1:02d}"
        to_date = f"{nxt}T12:00:00Z"
    else:
        from_date, to_date = args.from_date, args.to_date
    if not (from_date and to_date):
        sys.exit("Provide --date YYYY-MM-DD, or both --from-date and --to-date (ISO 8601 UTC).")

    # Follow Avoma's `next` links: a multi-week window spans many pages, and reading only the
    # first one silently drops later meetings.
    results, url, params = [], f"{BASE_URL}/v1/meetings", {"from_date": from_date, "to_date": to_date, "page_size": 100}
    for _ in range(MAX_PAGES):
        resp = _get(url, params)
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
            break
        results.extend(data.get("results") or [])
        url, params = data.get("next"), None
        if not url:
            break
    else:
        print(f"(stopped after {MAX_PAGES} pages; narrow the window for a complete list)", file=sys.stderr)

    title_needle = (args.title or "").lower()
    att_needle = (args.attendee or "").lower()

    def _matches(m):
        if title_needle and title_needle not in (m.get("subject") or "").lower():
            return False
        if att_needle:
            blob = " ".join(
                f"{a.get('name') or ''} {a.get('email') or ''}"
                for a in (m.get("attendees") or [])
            ).lower()
            if att_needle not in blob:
                return False
        return True

    matches = [m for m in results if _matches(m)]
    crit = []
    if title_needle:
        crit.append(f'title~"{args.title}"')
    if att_needle:
        crit.append(f'attendee~"{args.attendee}"')
    print(f"{len(matches)} meeting(s) in {from_date} .. {to_date}"
          + (f" matching {', '.join(crit)}" if crit else ""))
    for m in matches:
        print(f"\n  subject : {m.get('subject')}")
        print(f"  start   : {m.get('start_at')}")
        print(f"  uuid    : {m.get('uuid')}")
        att = m.get("attendees") or []
        if att:
            who = ", ".join(f"{a.get('name')} <{a.get('email')}>" for a in att)
            print(f"  with    : {who}")


def cmd_transcript(args) -> None:
    h = _headers()
    meeting = requests.get(
        f"{BASE_URL}/v1/meetings/{args.uuid}", headers=h, timeout=TIMEOUT
    ).json()
    print(f"# {meeting.get('subject')}")
    print(f"# {meeting.get('start_at')} -> {meeting.get('end_at')}")
    att = meeting.get("attendees") or []
    if att:
        print("# attendees: " + ", ".join(
            f"{a.get('name')} <{a.get('email')}>" for a in att))
    print()

    t = requests.get(
        f"{BASE_URL}/v1/transcriptions",
        headers=h,
        params={"meeting_uuid": args.uuid},
        timeout=TIMEOUT,
    )
    data = t.json() if getattr(t, "status_code", 200) == 200 else None
    if not isinstance(data, list):
        print("No transcript for this meeting (not recorded or not processed). Skip it.")
        return
    t = data
    utterances = []
    for seg in t:
        for utt in seg.get("transcript", []):
            ts = (utt.get("timestamps") or [0])[0]
            utterances.append((ts, utt.get("speaker_id"), utt.get("transcript", "")))
    utterances.sort(key=lambda x: x[0])
    for ts, sid, txt in utterances:
        print(f"[{int(ts // 60):02d}:{int(ts % 60):02d}] S{sid}: {txt}")


def main() -> None:
    p = argparse.ArgumentParser(description="Quick Avoma lookups (no analysis pipeline).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="List meetings in a date window.")
    pl.add_argument("--date", help="Local day YYYY-MM-DD (padded UTC window).")
    pl.add_argument("--from-date", help="ISO 8601 UTC, e.g. 2026-06-24T00:00:00Z")
    pl.add_argument("--to-date", help="ISO 8601 UTC, e.g. 2026-06-25T12:00:00Z")
    pl.add_argument("--title", help="Case-insensitive substring filter on subject.")
    pl.add_argument("--attendee", help="Case-insensitive substring filter on attendee name/email.")
    pl.set_defaults(func=cmd_list)

    pt = sub.add_parser("transcript", help="Print one meeting's transcript.")
    pt.add_argument("--uuid", required=True, help="Avoma meeting UUID.")
    pt.set_defaults(func=cmd_transcript)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
