# tests/test_checkins.py
from datetime import date, timedelta
from lib.checkins import (parse_join_date, tenure_months, survey_version, hold_until,
                          is_due, choose_variant, score_flags, pick_latest_response, fr_link_update)

MON = date(2026, 11, 2)  # a Monday

def test_parse_join_date_tolerates_time_and_two_digit_year():
    assert parse_join_date("2/21/2024 0:00:00") == date(2024, 2, 21)
    assert parse_join_date("2/21/24") == date(2024, 2, 21)


def test_pick_latest_response_parses_form_timestamps():
    r = pick_latest_response([{"submitted_at": "11/10/2026 9:00:00"},
                              {"submitted_at": "11/9/2026 17:30:00"}])
    assert r["submitted_at"] == "11/10/2026 9:00:00"


def test_parse_join_date_formats():
    assert parse_join_date("2/21/2024") == date(2024, 2, 21)
    assert parse_join_date("2024-02-21") == date(2024, 2, 21)
    assert parse_join_date("⚠ check date") is None
    assert parse_join_date("") is None

def test_survey_version_buckets():
    assert survey_version(1) is None
    assert survey_version(2) == "Early"
    assert survey_version(5) == "Early"
    assert survey_version(6) == "Settled"
    assert survey_version(11) == "Settled"
    assert survey_version(12) == "Mature"
    assert survey_version(41) == "Mature"

def test_due_on_slot_week():
    join = date(2026, 11, 2) - timedelta(weeks=26)
    assert is_due(join, MON, None, None) == (True, "due")

def test_not_due_off_slot_with_recent_checkin():
    join = MON - timedelta(weeks=27)
    assert is_due(join, MON, date(2026, 10, 1), None) == (False, "recent_checkin")

def test_due_skips_bad_join_date():
    assert is_due(None, MON, None, None) == (False, "bad_join_date")

def test_due_skips_future_join_date():
    assert is_due(date(2026, 12, 1), MON, None, None) == (False, "future_join_date")

def test_too_new():
    assert is_due(date(2026, 9, 1), MON, None, None) == (False, "too_new")

def test_catch_up_after_hold():
    # slot was 2 weeks ago (after program start), account was held then; hold now clear
    join = MON - timedelta(weeks=28)
    assert is_due(join, MON, date(2026, 5, 1), None, program_start=date(2026, 10, 1)) == (True, "due")


def test_no_catch_up_for_slots_before_program_start():
    join = MON - timedelta(weeks=28)
    assert is_due(join, MON, None, None, program_start=MON) == (False, "not_slot_week")


def test_skipped_draft_waits_for_next_slot():
    join = MON - timedelta(weeks=28)
    skipped_on = MON - timedelta(weeks=1)   # draft created after the slot, then deleted
    assert is_due(join, MON, skipped_on, None, program_start=date(2026, 10, 1)) == (False, "recent_checkin")


def test_kickoff_spreads_evenly_over_a_quarter():
    import random
    rng = random.Random(7)
    joins = [MON - timedelta(days=rng.randint(100, 1500)) for _ in range(105)]
    last = {}
    per_week = []
    for w in range(26):
        monday = MON + timedelta(weeks=w)
        due = [j for j in joins if is_due(j, monday, last.get(j), None, program_start=MON)[0]]
        for j in due:
            last[j] = monday
        per_week.append(len(due))
    assert max(per_week) <= 15, per_week
    assert sum(per_week[:13]) == 105   # every account touched once in the first quarter

def test_held_blocks():
    join = MON - timedelta(weeks=26)
    assert is_due(join, MON, None, date(2026, 11, 20)) == (False, "held")

def test_hold_until_rules():
    assert hold_until([{"open": True, "closed_on": None}], MON) == date.max
    assert hold_until([{"open": False, "closed_on": date(2026, 10, 20)}], MON) == date(2026, 11, 10)
    assert hold_until([{"open": False, "closed_on": date(2026, 9, 1)}], MON) is None
    assert hold_until([], MON) is None

def test_variant_progression():
    assert choose_variant([]) == "Intro"
    assert choose_variant(["Survey answered"]) == "Standard"
    assert choose_variant(["Survey answered", "Silent"]) == "Give-first"
    assert choose_variant(["Silent", "Silent"]) == "Different sender"

def test_first_ever_checkin_is_intro():
    # Nothing settled yet (never checked in, or only skipped / in-flight) -> introduce the program.
    assert choose_variant(["Skipped"]) == "Intro"
    assert choose_variant(["Drafted"]) == "Intro"
    # A silent first check-in escalates; it doesn't get the intro again.
    assert choose_variant(["Silent"]) == "Give-first"

def test_variant_skipped_is_transparent():
    assert choose_variant(["Silent", "Skipped", "Silent"]) == "Different sender"
    assert choose_variant(["Silent", "Skipped"]) == "Give-first"

def test_low_score_and_drop():
    hist = [{"platform": 9, "support": 8}]
    assert score_flags({"platform": 6, "support": 8}, hist) == ["Low score", "Score drop"]
    assert score_flags({"platform": 8, "support": 8}, hist) == []
    assert score_flags({"platform": 7, "support": 6}, hist) == ["Low score", "Score drop"]

def test_score_drop_uses_last_scored_checkin():
    hist = [{"platform": 9, "support": 9}, {"platform": None, "support": None}]
    assert score_flags({"platform": 7, "support": 9}, hist) == ["Score drop"]
    assert score_flags({"platform": 7, "support": 7}, []) == []

def test_pick_latest_response_per_checkin():
    r = pick_latest_response([{"submitted_at": "2026-11-03T10:00:00"},
                              {"submitted_at": "2026-11-05T09:00:00"}])
    assert r["submitted_at"] == "2026-11-05T09:00:00"
    assert pick_latest_response([]) is None

def test_fr_link_update_no_double_count():
    up = fr_link_update([], "FSP", 1, "Gem Sessions")
    assert up == {"changed": True, "linked": ["Gem Sessions"], "text": "FSP, Gem Sessions", "count": 2}
    again = fr_link_update(["Gem Sessions"], "FSP, Gem Sessions", 2, "Gem Sessions")
    assert again["changed"] is False and again["count"] == 2
    assert fr_link_update([], "", None, "FSP")["count"] == 1