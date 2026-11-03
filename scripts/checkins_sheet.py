#!/usr/bin/env python3
"""Read-only full-tab reads for the OS check-ins routine.

The Google Drive connector's read_file_content returns only a sample of
sheet rows, so the runbook reads the Client List and the survey responses
through the Sheets API instead:

    python3 scripts/checkins_sheet.py accounts    # Active Customers rows
    python3 scripts/checkins_sheet.py responses   # all 3 survey tabs

Prints JSON to stdout. Exit 2 with {"error": ...} on failure. Never writes.
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

CLIENT_LIST_ID = "1Rxk54_u3w0Llm78Yqv8e2BaKG9ddG4UzTMEvaTCmgzs"
ACCOUNTS_TAB = "Active Customers"
RESPONSES_ID = "1g4UJldueeEKytNolqqP-e8YPa6Xwo0ksKbpOiWiithI"
RESPONSE_TABS = {
    "2-6 mo. Responses": "Early",
    "6-12 mo. Responses": "Settled",
    "12+ mo. Responses": "Mature",
}
# The runbook runs this from a git-archive export, which has no .env.
_ENV_FALLBACK = Path("/Users/trentluecke/dev/Claude-Projects/chief-of-staff/.env")


def rows_to_records(rows):
    """Header row + data rows → list of dicts. Pads short rows; drops blank first columns."""
    if not rows:
        return []
    head = [h.strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not r or not str(r[0]).strip():
            continue
        r = list(r) + [""] * (len(head) - len(r))
        out.append(dict(zip(head, r)))
    return out


def _tab(service, sheet_id, tab):
    resp = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=f"'{tab}'!A1:Z").execute()
    return resp.get("values", [])


def read_accounts(service):
    return rows_to_records(_tab(service, CLIENT_LIST_ID, ACCOUNTS_TAB))


def read_responses(service):
    out = []
    for tab, version in RESPONSE_TABS.items():
        for rec in rows_to_records(_tab(service, RESPONSES_ID, tab)):
            out.append({"version": version, **rec})
    return out


def _service():
    from dotenv import load_dotenv
    env = _ROOT / ".env"
    load_dotenv(env if env.exists() else _ENV_FALLBACK)
    from lib.google_auth import build_sheets_service
    return build_sheets_service()


COMMANDS = {"accounts": read_accounts, "responses": read_responses}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(json.dumps({"error": f"usage: checkins_sheet.py {'|'.join(COMMANDS)}"}))
        return 2
    try:
        rows = COMMANDS[sys.argv[1]](_service())
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 2
    print(json.dumps({"count": len(rows), "rows": rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
