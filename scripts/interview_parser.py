#!/usr/bin/env python3
"""Customer-interview parser — Avoma transcript → JTBD notes → tracker row.

Turns a recorded customer interview (in Avoma) into (a) readable JTBD notes and
insights, and (b) a proposed row for the automation-interview tracker. You review
and edit the draft, then `commit` appends the approved row straight to the Google
Sheet. Nothing is written to the sheet until you run `commit`.

Tuned to the OS Workflow Builder discovery: it pulls the job, the struggling
moment, the four forces, the automation signal (tried-and-stopped / didn't-know /
won't-connect), and the platforms a prospect wants connected (feeds the curated
first-connector list).

Commands:
  setup-sheet   Create the tracker spreadsheet (once). Prints + stores its URL.
  parse         Fetch an Avoma interview, extract, write a draft you can edit.
  commit        Append the (edited) draft's row to the tracker.

Auth: AVOMA_API_KEY + ANTHROPIC_API_KEY + GOOGLE_OAUTH_JSON (read from .env).
The Google token needs the read+write `spreadsheets` scope (see scripts/authorize.py).

Examples:
  python3 scripts/interview_parser.py setup-sheet
  python3 scripts/interview_parser.py parse --uuid 5835ccc6-df0e-40d6-98ac-59f9fba03deb
  python3 scripts/interview_parser.py parse --date 2026-07-01 --title "Smith"
  python3 scripts/interview_parser.py commit data/state/interviews/smith-gym.draft.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

BASE_URL = "https://api.avoma.com"
TIMEOUT = 60
MODEL = "claude-opus-4-8"  # interviews are few and high-value — quality over cost
TRANSCRIPT_CHAR_LIMIT = 60_000

STATE_DIR = PROJECT_ROOT / "data" / "state" / "interviews"
SHEET_CONFIG = STATE_DIR / "sheet.json"

SHEET_TITLE = "TeamBuildr OS — Automation JTBD Interviews"
INTERVIEW_HEADERS = [
    "#", "Date", "Gym / interviewee", "Segment", "Core job (JTBD)", "Intensity",
    "Frequency", "Workaround + cost", "Tools to connect", "Forces (P/P/A/H)",
    "Go?", "Avoma UUID",
]
QUOTE_HEADERS = ["Date", "Gym", "Quote", "Theme"]

# Labels in the editable draft block, in tracker-column order (after the auto "#").
ROW_LABELS = [
    "Date", "Gym / interviewee", "Segment", "Core job (JTBD)", "Intensity (1-5)",
    "Frequency", "Workaround + cost", "Tools to connect", "Forces (P/P/A/H)",
    "Go?", "Avoma UUID",
]


# --------------------------------------------------------------------------
# Avoma
# --------------------------------------------------------------------------

def _avoma_key() -> str:
    import os
    k = os.environ.get("AVOMA_API_KEY")
    if not k:
        sys.exit("AVOMA_API_KEY not found in .env or shell env.")
    return k


def _avoma_get(path: str, params: dict | None = None):
    r = requests.get(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {_avoma_key()}"},
                     params=params or {}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _find_uuid(date: str, title: str | None) -> str:
    """Locate a meeting UUID by local day + optional title substring."""
    d = date.split("-")
    nxt = f"{d[0]}-{d[1]}-{int(d[2]) + 1:02d}"
    body = _avoma_get("/v1/meetings", {"from_date": f"{date}T00:00:00Z",
                                       "to_date": f"{nxt}T12:00:00Z"})
    results = body.get("results", body if isinstance(body, list) else [])
    needle = (title or "").lower()
    matches = [m for m in results if needle in (m.get("subject") or "").lower()]
    if not matches:
        sys.exit(f"No meetings on {date}" + (f" matching '{title}'" if title else ""))
    if len(matches) > 1:
        print("Multiple matches — re-run with --uuid <one of these>:", file=sys.stderr)
        for m in matches:
            print(f"  {m.get('uuid')}  {m.get('subject')}  ({m.get('start_at')})", file=sys.stderr)
        sys.exit(1)
    return matches[0]["uuid"]


def _fetch_interview(uuid: str) -> dict:
    meeting = _avoma_get(f"/v1/meetings/{uuid}")
    if not meeting.get("transcript_ready"):
        sys.exit(f"Transcript not ready for {uuid} (Avoma may still be processing it).")
    body = _avoma_get("/v1/transcriptions", {"meeting_uuid": uuid})
    results = body if isinstance(body, list) else body.get("results", [])
    if not results:
        sys.exit(f"No transcript found for {uuid}.")
    data = results[0]
    speaker_map = {}
    for s in data.get("speakers", []):
        sid = str(s.get("id") or s.get("speaker_id", ""))
        speaker_map[sid] = ("Interviewer" if s.get("is_rep") else "Customer") + \
            f" - {s.get('name') or s.get('email', 'Unknown')}"
    lines = []
    for utt in data.get("transcript", []):
        txt = (utt.get("transcript") or "").strip()
        if txt:
            lines.append(f"[{speaker_map.get(str(utt.get('speaker_id', '')), 'Unknown')}]: {txt}")
    attendees = [(a.get("name") or a.get("email")) for a in (meeting.get("attendees") or [])
                 if a.get("name") or a.get("email")]
    return {
        "uuid": uuid, "subject": meeting.get("subject") or "Interview",
        "start_at": meeting.get("start_at") or "", "attendees": attendees,
        "text": "\n".join(lines),
    }


# --------------------------------------------------------------------------
# JTBD extraction
# --------------------------------------------------------------------------

_TOOL = {
    "name": "extract",
    "description": "Extract JTBD structure and tracker fields from a customer interview transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "gym": {"type": "string", "description": "Gym / facility / interviewee name."},
            "segment": {"type": "string", "enum": ["recent adopter", "established", "unclear"],
                        "description": "Recent OS adopter (started recently / describes switching in) vs established user. 'unclear' if not evident."},
            "core_job": {"type": "string", "description": "The job as a JTBD statement: 'When I ___, I want to ___, so I can ___.' Grounded in what they actually struggle with."},
            "struggling_moment": {"type": "string", "description": "The specific recent situation where they needed things connected/automated — what happened, step by step."},
            "workaround": {"type": "string", "description": "What they do today to bridge the gap (manual steps, a person, a tool)."},
            "workaround_cost": {"type": "string", "description": "The cost of that workaround — hours/week, dollars, or a person's time. 'unclear' if not stated."},
            "tools_to_connect": {"type": "array", "items": {"type": "string"},
                                 "description": "Third-party CRM/business-process/automation platforms the CUSTOMER wants connected. Exclude Stripe (native payments), Mailchimp (native), and sports-science hardware/wearables."},
            "automation_signal": {"type": "string", "enum": ["tried_and_stopped", "unaware", "tool_wont_connect", "actively_using", "none"],
                                   "description": "Their relationship to automation tools: tried one and stopped; unaware such tools exist; their tool has no connector; actively using automation; or none discussed."},
            "push": {"type": "string", "description": "What makes the current way painful enough to consider changing."},
            "pull": {"type": "string", "description": "What a working solution would free them to do."},
            "anxiety": {"type": "string", "description": "What worries them about changing (setup, trust, learning)."},
            "habit": {"type": "string", "description": "What keeps them doing it the current way."},
            "intensity": {"type": "integer", "description": "Pain intensity 1-5 based on their language and stakes."},
            "frequency": {"type": "string", "description": "How often the struggle recurs (e.g. daily, weekly, monthly, rarely)."},
            "go_signal": {"type": "string", "enum": ["Y", "N", "?"],
                          "description": "Y if this is a frequent + painful + already-paid-for job worth building for; N if clearly not; ? if borderline."},
            "quotes": {"type": "array", "items": {
                "type": "object",
                "properties": {"quote": {"type": "string"}, "theme": {"type": "string"}},
                "required": ["quote", "theme"]},
                "description": "2-5 verbatim customer quotes that capture the job/pain, each tagged with a short theme."},
            "notes": {"type": "string", "description": "A tight 4-8 sentence narrative synthesis for the rep: the job, the struggle, the automation signal, and the read on whether this supports building the Workflow Builder."},
        },
        "required": ["gym", "segment", "core_job", "struggling_moment", "workaround",
                     "workaround_cost", "tools_to_connect", "automation_signal", "push",
                     "pull", "anxiety", "habit", "intensity", "frequency", "go_signal",
                     "quotes", "notes"],
    },
}

_SYSTEM = """You analyze a recorded TeamBuildr customer interview using the Jobs-to-be-Done framework, to learn whether customers need the planned OS Workflow Builder (a native automation/integration layer that would replace Zapier inside TeamBuildr OS).

TeamBuildr OS is a business-operations platform for gyms/facilities (scheduling, billing, memberships, CRM). Strength and AMS are its other products.

Extract the underlying JOB, not a feature wish list. Ground everything in the specific struggle the customer describes. Distinguish what the CUSTOMER raised from what the interviewer suggested. For tools_to_connect, count CRM / business-process / automation platforms the customer wants connected — EXCLUDE Stripe (OS's native payment processor), Mailchimp (native email), and sports-science hardware/wearables (force plates, VBT, timing gates, GPS/tracking, Whoop, Garmin, etc.). Be honest and conservative on intensity and go_signal — these feed a build decision."""


def _extract(rec: dict) -> dict:
    import os
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or sys.exit("ANTHROPIC_API_KEY not set"))
    resp = client.messages.create(
        model=MODEL, max_tokens=2000, system=_SYSTEM,
        tools=[_TOOL], tool_choice={"type": "tool", "name": "extract"},
        messages=[{"role": "user", "content":
                   f"Interview: {rec['subject']}\nParticipants: {', '.join(rec['attendees'])}\n\n"
                   f"Transcript:\n{rec['text'][:TRANSCRIPT_CHAR_LIMIT]}"}],
    )
    out = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if out is None:
        sys.exit("Extraction returned no structured output.")
    return out


# --------------------------------------------------------------------------
# Draft rendering + parsing
# --------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "interview").lower()).strip("-")[:50] or "interview"


def _render_draft(rec: dict, x: dict, draft_path: Path) -> str:
    date = (rec.get("start_at") or "")[:10]
    tools = ", ".join(x.get("tools_to_connect") or []) or "(none named)"
    forces = (f"push: {x.get('push','')} / pull: {x.get('pull','')} / "
              f"anxiety: {x.get('anxiety','')} / habit: {x.get('habit','')}")
    quotes_md = "\n".join(f'- "{q["quote"]}"  — _{q["theme"]}_' for q in x.get("quotes", [])) or "- (none captured)"
    return f"""# Interview — {x.get('gym')} · {date}
_Avoma: {rec['uuid']}_

## Notes & insights
{x.get('notes','')}

**The job.** {x.get('core_job','')}

**Struggling moment.** {x.get('struggling_moment','')}

**Workaround today.** {x.get('workaround','')} — _cost: {x.get('workaround_cost','')}_

**Automation signal.** `{x.get('automation_signal','')}`

**Four forces.** {forces}

## Key quotes
{quotes_md}

---
<!-- TRACKER ROW — edit any value below, then:
     python3 scripts/interview_parser.py commit {draft_path} -->
## TRACKER ROW
Date: {date}
Gym / interviewee: {x.get('gym','')}
Segment: {x.get('segment','')}
Core job (JTBD): {x.get('core_job','')}
Intensity (1-5): {x.get('intensity','')}
Frequency: {x.get('frequency','')}
Workaround + cost: {x.get('workaround','')} ({x.get('workaround_cost','')})
Tools to connect: {tools}
Forces (P/P/A/H): {forces}
Go?: {x.get('go_signal','')}
Avoma UUID: {rec['uuid']}
"""


def _parse_draft(text: str) -> tuple[list[str], list[list[str]]]:
    """Return (interview_row_values, quote_rows) from an edited draft."""
    if "## TRACKER ROW" not in text:
        sys.exit("No '## TRACKER ROW' block found — is this a draft produced by `parse`?")
    block = text.split("## TRACKER ROW", 1)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.strip().startswith(("#", "<!--", "-")):
            label, _, val = line.partition(":")
            fields[label.strip()] = val.strip()
    missing = [lab for lab in ROW_LABELS if lab not in fields]
    if missing:
        sys.exit(f"Draft is missing tracker fields: {', '.join(missing)}")
    row = [""] + [fields[lab] for lab in ROW_LABELS]  # leading "#" filled at append time

    # quotes for the Quotes tab
    date = fields.get("Date", "")
    gym = fields.get("Gym / interviewee", "")
    quote_rows = []
    if "## Key quotes" in text:
        qsec = text.split("## Key quotes", 1)[1].split("---", 1)[0]
        for line in qsec.splitlines():
            m = re.match(r'\s*-\s*"(.+?)"\s*(?:—\s*_?(.*?)_?)?\s*$', line)
            if m and m.group(1) and "none captured" not in m.group(1):
                quote_rows.append([date, gym, m.group(1), (m.group(2) or "").strip()])
    return row, quote_rows


# --------------------------------------------------------------------------
# Google Sheets
# --------------------------------------------------------------------------

def _sheets():
    try:
        from lib.google_auth import build_sheets_service
    except Exception as e:
        sys.exit(f"Could not import Google auth: {e}")
    return build_sheets_service()


def _load_sheet_id() -> dict:
    if not SHEET_CONFIG.exists():
        sys.exit("No tracker sheet yet. Run:  python3 scripts/interview_parser.py setup-sheet")
    return json.loads(SHEET_CONFIG.read_text())


def cmd_setup_sheet(args) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if SHEET_CONFIG.exists() and not args.force:
        cfg = json.loads(SHEET_CONFIG.read_text())
        print(f"Tracker already exists: {cfg.get('url')}\n(use --force to create a new one)")
        return
    svc = _sheets()
    try:
        created = svc.spreadsheets().create(body={
            "properties": {"title": args.title},
            "sheets": [
                {"properties": {"title": "Interviews", "gridProperties": {"frozenRowCount": 1}}},
                {"properties": {"title": "Quotes", "gridProperties": {"frozenRowCount": 1}}},
            ],
        }).execute()
    except Exception as e:
        sys.exit(f"Sheet create failed — likely the token still lacks the write scope. "
                 f"Re-run authorize.py and update .env / the GitHub Secret.\n  {e}")
    sid = created["spreadsheetId"]
    url = created.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sid}")
    svc.spreadsheets().values().batchUpdate(spreadsheetId=sid, body={
        "valueInputOption": "RAW",
        "data": [
            {"range": "Interviews!A1", "values": [INTERVIEW_HEADERS]},
            {"range": "Quotes!A1", "values": [QUOTE_HEADERS]},
        ],
    }).execute()
    SHEET_CONFIG.write_text(json.dumps({"spreadsheetId": sid, "url": url,
                                        "title": args.title}, indent=2))
    print(f"Created tracker: {url}\nStored id -> {SHEET_CONFIG.relative_to(PROJECT_ROOT)}")


def cmd_parse(args) -> None:
    uuid = args.uuid or _find_uuid(args.date, args.title)
    print(f"Fetching Avoma interview {uuid}...", file=sys.stderr)
    rec = _fetch_interview(uuid)
    print(f"Extracting JTBD structure on {MODEL}...", file=sys.stderr)
    x = _extract(rec)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    draft_path = STATE_DIR / f"{_slug(x.get('gym') or rec['subject'])}.draft.md"
    draft_path.write_text(_render_draft(rec, x, draft_path))
    print(f"\nDraft written -> {draft_path.relative_to(PROJECT_ROOT)}")
    print("Review/edit it, then:")
    print(f"  python3 scripts/interview_parser.py commit {draft_path.relative_to(PROJECT_ROOT)}")


def cmd_commit(args) -> None:
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"Draft not found: {path}")
    row, quote_rows = _parse_draft(path.read_text())
    cfg = _load_sheet_id()
    sid = cfg["spreadsheetId"]
    svc = _sheets()
    # compute the next index number from current data rows
    existing = svc.spreadsheets().values().get(spreadsheetId=sid, range="Interviews!A2:A").execute()
    row[0] = str(len(existing.get("values", [])) + 1)
    svc.spreadsheets().values().append(
        spreadsheetId=sid, range="Interviews!A1", valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()
    if quote_rows:
        svc.spreadsheets().values().append(
            spreadsheetId=sid, range="Quotes!A1", valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS", body={"values": quote_rows}).execute()
    print(f"Appended interview #{row[0]} ({row[2]}) + {len(quote_rows)} quote(s).")
    print(f"  {cfg.get('url')}")


def main() -> None:
    p = argparse.ArgumentParser(description="Customer-interview JTBD parser → Google Sheet tracker.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("setup-sheet", help="Create the tracker spreadsheet (once).")
    ps.add_argument("--title", default=SHEET_TITLE)
    ps.add_argument("--force", action="store_true", help="Create a new sheet even if one is recorded.")
    ps.set_defaults(func=cmd_setup_sheet)

    pp = sub.add_parser("parse", help="Fetch an Avoma interview and write an editable draft.")
    pp.add_argument("--uuid", help="Avoma meeting UUID.")
    pp.add_argument("--date", help="Local day YYYY-MM-DD (with --title) to locate the interview.")
    pp.add_argument("--title", help="Title substring to locate the interview.")
    pp.set_defaults(func=cmd_parse)

    pc = sub.add_parser("commit", help="Append an edited draft's row to the tracker.")
    pc.add_argument("file", help="Path to the .draft.md file.")
    pc.set_defaults(func=cmd_commit)

    args = p.parse_args()
    if args.cmd == "parse" and not args.uuid and not args.date:
        sys.exit("parse needs --uuid, or --date (+ optional --title).")
    args.func(args)


if __name__ == "__main__":
    main()
