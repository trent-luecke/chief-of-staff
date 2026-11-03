# lib/checkins.py
"""Pure rules for the OS quarterly check-in program.

No I/O. The scheduled-task runbook gathers data from Front/HubSpot/Notion/
Sheets and calls these (via scripts/checkins.py) so who-is-due, version,
variant, holds and score flags come out the same every run.
See docs/superpowers/specs/2026-11-02-os-quarterly-checkins-design.md.
"""
from datetime import date, datetime, timedelta

HOLD_CUSHION_DAYS = 21
CYCLE_WEEKS = 13
RECENT_CHECKIN_DAYS = 70
LOW_SCORE = 6
DROP_POINTS = 2

_IN_FLIGHT = {"Drafted", "Sent"}


def parse_join_date(raw):
    raw = (raw or "").strip().split(" ")[0]  # Sheets exports may carry a time
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def tenure_months(join, today):
    months = (today.year - join.year) * 12 + (today.month - join.month)
    if today.day < join.day:
        months -= 1
    return months


def survey_version(tenure):
    if tenure < 2:
        return None
    if tenure < 6:
        return "Early"
    if tenure < 12:
        return "Settled"
    return "Mature"


def hold_until(support, today):
    if any(s["open"] for s in support):
        return date.max
    closed = [s["closed_on"] for s in support if s.get("closed_on")]
    if not closed:
        return None
    until = max(closed) + timedelta(days=HOLD_CUSHION_DAYS)
    return until if until > today else None


def is_due(join, week_monday, last_checkin_on, hold, program_start=None):
    """Due on the account's slot week (every 13 weeks from join), or later in the
    same cycle if that slot was missed (held) — but never for slots before
    program_start, so kickoff doesn't dump every account into week one."""
    if join is None:
        return False, "bad_join_date"
    if join > week_monday:
        return False, "future_join_date"
    weeks = (week_monday - join).days // 7
    if weeks < CYCLE_WEEKS:
        return False, "too_new"
    if hold is not None and hold > week_monday:
        return False, "held"
    if last_checkin_on is not None and (week_monday - last_checkin_on).days < RECENT_CHECKIN_DAYS:
        return False, "recent_checkin"
    slot_monday = week_monday - timedelta(weeks=weeks % CYCLE_WEEKS)
    if program_start is not None and slot_monday < program_start:
        return False, "not_slot_week"
    if last_checkin_on is None or last_checkin_on < slot_monday:
        return True, "due"
    return False, "not_slot_week"


def choose_variant(prior_outcomes):
    settled = [o for o in prior_outcomes if o != "Skipped" and o not in _IN_FLIGHT]
    if len(settled) >= 2 and settled[-1] == "Silent" and settled[-2] == "Silent":
        return "Different sender"
    if settled and settled[-1] == "Silent":
        return "Give-first"
    return "Standard"


def score_flags(current, history):
    flags = []
    scores = [current.get(k) for k in ("platform", "support")]
    if any(s is not None and s <= LOW_SCORE for s in scores):
        flags.append("Low score")
    prev = next((h for h in reversed(history)
                 if h.get("platform") is not None or h.get("support") is not None), None)
    if prev:
        for k in ("platform", "support"):
            cur, old = current.get(k), prev.get(k)
            if cur is not None and old is not None and old - cur >= DROP_POINTS:
                flags.append("Score drop")
                break
    return flags


def _response_time(raw):
    raw = (raw or "").strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):  # Google Forms "Timestamp"
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(raw)


def pick_latest_response(responses):
    if not responses:
        return None
    return max(responses, key=lambda r: _response_time(r["submitted_at"]))


def fr_link_update(linked, text, count, account):
    if account in linked:
        return {"changed": False, "linked": list(linked), "text": text, "count": count}
    names = [n.strip() for n in (text or "").split(",") if n.strip()]
    if account not in names:
        names.append(account)
    return {"changed": True, "linked": list(linked) + [account],
            "text": ", ".join(names), "count": (count or 0) + 1}
