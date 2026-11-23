# lib/churn.py
"""Pure rules for syncing the cancellations sheet into the OS Accounts Database.

No I/O. docs/runbooks/churn-sync.md reads the "Non-Renewal/Cancellation
Feedback" sheet (scripts/checkins_sheet.py cancellations) and the Notion
OS Accounts Database, then calls churn_actions (via scripts/checkins.py churn)
to decide which accounts to mark Churned.

Matching is EXACT (case- and whitespace-insensitive, after dropping an
"(ID: 902)"-style suffix). Fuzzy matching is deliberately NOT used to act:
on real data it paired a cancelled gym with a different, live gym that only
shared "Strength & Conditioning", which would churn a live customer. Fuzzy
hits are only reported as near matches for a human to decide.
"""
import re
from datetime import date, timedelta

from lib.account_match import match_accounts

_ID_SUFFIX = re.compile(r"\s*(?:\(\s*(?:id\s*[:#]?\s*)?#?\d+\s*\)|#\s*\d+)\s*$", re.I)
_NO = {"", "no", "n", "false", "-"}
NEAR_MATCH_WINDOW_DAYS = 120


def strip_account_id(raw):
    """'The Example Lab (ID: 902)' → 'The Example Lab'; 'Sample Barbell (692)' → 'Sample Barbell'."""
    return _ID_SUFFIX.sub("", (raw or "").strip()).strip()


def name_key(name):
    """Exact-match key: casefolded, whitespace collapsed."""
    return " ".join(strip_account_id(name).casefold().split())


def has_returned(value):
    return str(value or "").strip().casefold() not in _NO


def churn_actions(cancellations, accounts, today=None):
    """Decide Notion updates from the cancellations sheet.

    cancellations: [{"name", "cancelled_on" (ISO or ""), "returned" (raw cell), "tab"}]
    accounts: [{"name", "status"}] from the OS Accounts Database.

    Returns {"to_churn", "already_churned", "returned_but_churned", "near_matches"}:
      to_churn             Notion Active + cancelled + not returned → set Status Churned.
      already_churned      nothing to do.
      returned_but_churned Notion Churned but the sheet says they came back → human review, never auto-reverted.
      near_matches         no exact match, cancelled within NEAR_MATCH_WINDOW_DAYS of `today`, and the
                           fuzzy matcher found a still-Active candidate → report only. Old cancellations are
                           ignored so the same stale near-miss doesn't repeat every day.
    """
    cutoff = ((today or date.today()) - timedelta(days=NEAR_MATCH_WINDOW_DAYS)).isoformat()
    latest = {}
    for c in cancellations:
        key = name_key(c.get("name"))
        if not key:
            continue
        prev = latest.get(key)
        if prev is None or (c.get("cancelled_on") or "") >= (prev.get("cancelled_on") or ""):
            latest[key] = c

    by_key = {name_key(a["name"]): a for a in accounts if a.get("name")}
    active_names = [a["name"] for a in accounts if a.get("name") and (a.get("status") or "").strip() != "Churned"]
    out = {"to_churn": [], "already_churned": [], "returned_but_churned": [], "near_matches": []}

    for key, c in sorted(latest.items()):
        acct = by_key.get(key)
        returned = has_returned(c.get("returned"))
        if acct is None:
            if returned or (c.get("cancelled_on") or "") < cutoff:
                continue
            m = match_accounts(strip_account_id(c["name"]), active_names)
            cands = sorted({x["account"] for x in m["matched"] + m["uncertain"]})
            if cands:
                out["near_matches"].append({"cancelled_name": c["name"].strip(), "candidates": cands,
                                            "cancelled_on": c.get("cancelled_on", "")})
            continue
        entry = {"account": acct["name"], "cancelled_on": c.get("cancelled_on", ""), "tab": c.get("tab", "")}
        status = (acct.get("status") or "").strip()
        if returned:
            if status == "Churned":
                out["returned_but_churned"].append(entry)
        elif status == "Churned":
            out["already_churned"].append(entry)
        else:
            out["to_churn"].append(entry)
    return out
