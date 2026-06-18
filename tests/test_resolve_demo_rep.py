from collectors.avoma import resolve_demo_rep, DEMO_REP_ROSTER


def test_matches_is_rep_speaker_by_full_name():
    speakers = [{"name": "Ryan Allwein", "is_rep": True},
                {"name": "Tristan Coles", "is_rep": False}]
    assert resolve_demo_rep(speakers, [], DEMO_REP_ROSTER) == "Ryan Allwein"


def test_falls_back_to_attendee_name_when_no_is_rep():
    attendees = [{"name": "Jeff Davidson", "email": ""}, {"name": "Prospect Co"}]
    assert resolve_demo_rep([], attendees, DEMO_REP_ROSTER) == "Jeff Davidson"


def test_matches_on_last_name_token():
    speakers = [{"name": "Luke A. Martin", "is_rep": True}]
    assert resolve_demo_rep(speakers, [], DEMO_REP_ROSTER) == "Luke Martin"


def test_quinn_not_in_roster_returns_none():
    speakers = [{"name": "Quinn Smith", "is_rep": True}]
    assert resolve_demo_rep(speakers, [], DEMO_REP_ROSTER) is None


def test_no_match_returns_none():
    assert resolve_demo_rep([{"name": "iPad", "is_rep": False}], [], DEMO_REP_ROSTER) is None
