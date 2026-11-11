# tests/test_checkins_cli.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd, payload):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "checkins.py"), cmd],
                       input=stdin, capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def _acct(name, join, email):
    return {"name": name, "join_date": join, "email": email,
            "last_checkin_on": None, "support": [], "prior_outcomes": []}


def test_cli_due_mixes_due_and_skipped():
    rc, out = _run("due", {"week_monday": "2026-11-02", "accounts": [
        _acct("FSP", "5/4/2026", "miles@fspbr.com"),
        _acct("Grind Time", "⚠ check date", "will@grindtime.com"),
        _acct("Base Performance", "5/4/2026", "info@baseperformance.org"),
    ]})
    assert rc == 0
    assert [d["name"] for d in out["due"]] == ["FSP", "Base Performance"]
    assert out["due"][0]["generic_email"] is False
    assert out["due"][1]["generic_email"] is True
    assert {d["version"] for d in out["due"]} == {"Early"}
    assert {d["variant"] for d in out["due"]} == {"Intro"}
    assert out["skipped"] == [{"name": "Grind Time", "reason": "bad_join_date"}]


def test_cli_due_applies_support_hold():
    a = _acct("FSP", "5/4/2026", "miles@fspbr.com")
    a["support"] = [{"open": False, "closed_on": "2026-10-25"}]
    rc, out = _run("due", {"week_monday": "2026-11-02", "accounts": [a]})
    assert out["due"] == [] and out["skipped"] == [{"name": "FSP", "reason": "held"}]


def test_cli_malformed_input_exit_2():
    rc, out = _run("due", "not json")
    assert rc == 2 and "error" in out


def test_cli_flags_roundtrip():
    rc, out = _run("flags", {"current": {"platform": 6, "support": 8},
                             "history": [{"platform": 9, "support": 8}]})
    assert rc == 0 and out == {"flags": ["Low score", "Score drop"]}


def test_cli_fr_link_and_match():
    rc, out = _run("fr-link", {"linked": [], "text": "FSP", "count": 1, "account": "Gem Sessions"})
    assert out["count"] == 2 and out["changed"] is True
    rc, out = _run("match", {"raw": "Athlete Standard", "accounts": ["The Athlete Standard"]})
    assert out["matched"][0]["account"] == "The Athlete Standard"


def test_cli_due_respects_program_start_at_kickoff():
    # 28 weeks old: its slot was 2 weeks ago, before the program started -> not due this week
    rc, out = _run("due", {"week_monday": "2026-11-02", "program_start": "2026-11-02",
                           "accounts": [_acct("Off-slot Gym", "4/20/2026", "a@b.com")]})
    assert out["due"] == [] and out["skipped"] == [{"name": "Off-slot Gym", "reason": "not_slot_week"}]
