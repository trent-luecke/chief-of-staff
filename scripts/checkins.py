#!/usr/bin/env python3
"""JSON-in / JSON-out CLI over lib.checkins + lib.account_match.

Called by docs/runbooks/os-quarterly-checkins-runbook.md so the
deterministic rules run the same way every pass:

    echo '<json>' | python3 scripts/checkins.py due|flags|latest|fr-link|match
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from lib.account_match import match_accounts  # noqa: E402
from lib.checkins import (  # noqa: E402
    choose_variant, fr_link_update, hold_until, is_due, parse_join_date,
    pick_latest_response, score_flags, survey_version, tenure_months,
)

GENERIC_LOCAL_PARTS = {"info", "admin", "contact", "hello", "office", "team", "support"}


def _d(s):
    return date.fromisoformat(s) if s else None


def cmd_due(p):
    monday = _d(p["week_monday"])
    due, skipped = [], []
    for a in p["accounts"]:
        join = parse_join_date(a.get("join_date"))
        support = [{"open": bool(s.get("open")), "closed_on": _d(s.get("closed_on"))}
                   for s in a.get("support", [])]
        ok, reason = is_due(join, monday, _d(a.get("last_checkin_on")),
                            hold_until(support, monday))
        if not ok:
            skipped.append({"name": a["name"], "reason": reason})
            continue
        email = (a.get("email") or "").strip()
        due.append({
            "name": a["name"],
            "email": email,
            "version": survey_version(tenure_months(join, monday)),
            "variant": choose_variant(a.get("prior_outcomes", [])),
            "generic_email": email.split("@")[0].lower() in GENERIC_LOCAL_PARTS,
        })
    return {"due": due, "skipped": skipped}


COMMANDS = {
    "due": cmd_due,
    "flags": lambda p: {"flags": score_flags(p["current"], p.get("history", []))},
    "latest": lambda p: {"response": pick_latest_response(p.get("responses", []))},
    "fr-link": lambda p: fr_link_update(p.get("linked", []), p.get("text", ""),
                                        p.get("count"), p["account"]),
    "match": lambda p: match_accounts(p["raw"], p["accounts"]),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=sorted(COMMANDS))
    args = ap.parse_args()
    try:
        payload = json.loads(sys.stdin.read())
        out = COMMANDS[args.cmd](payload)
    except (ValueError, KeyError, TypeError) as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 2
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
