"""Phase 0: Avoma must preserve prospect emails as structured attendee data.

The email-keyed deal spine depends on demos carrying real prospect emails.
Previously `fetch_recent_meetings`/`fetch_meeting_by_uuid` collapsed attendees
into a name-preferred `participants` list, silently dropping every email, so the
downstream `invitee_emails` was almost always empty.
"""

from unittest.mock import patch, MagicMock


def test_extract_attendees_preserves_name_and_email():
    from collectors.avoma import _extract_attendees
    raw = [
        {"name": "Jane Prospect", "email": "jane@acme.com"},
        {"name": "Ryan Allwein", "email": "ryan@teambuildr.com"},
        {"email": "noname@acme.com"},
        {"name": "No Email"},
        {},
    ]
    out = _extract_attendees(raw)
    assert {"name": "Jane Prospect", "email": "jane@acme.com"} in out
    assert {"name": "", "email": "noname@acme.com"} in out
    assert {"name": "No Email", "email": ""} in out
    assert len(out) == 4  # the empty {} is skipped


def _mock_meeting():
    return {
        "uuid": "u-1",
        "subject": "OS Demo - Acme",
        "start_at": "2026-06-02T14:00:00Z",
        "transcript_ready": True,
        "attendees": [
            {"name": "John Smith", "email": "john@acme.com"},
            {"name": "Trent Luecke", "email": "trent@teambuildr.com"},
        ],
    }


def _analysis():
    return {
        "os_interested": True, "call_type": "demo", "summary": "s",
        "features_covered": [], "gaps": [], "objections": [], "buying_signals": [],
        "competitors": [], "onboarding_completed": [], "onboarding_next_steps": [],
        "action_items": [],
    }


def test_fetch_meeting_by_uuid_captures_attendee_emails():
    from collectors.avoma import fetch_meeting_by_uuid
    with patch("collectors.avoma.requests.get") as mg, \
         patch("collectors.avoma._fetch_transcript",
               return_value=([], [{"speaker_id": "1", "transcript": "hi"}])), \
         patch("collectors.avoma._analyze_with_claude", return_value=_analysis()):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = _mock_meeting()
        mg.return_value = resp
        t = fetch_meeting_by_uuid("k", "ak", "model", "u-1")

    assert t is not None
    assert {"name": "John Smith", "email": "john@acme.com"} in t.attendees
    assert {"name": "Trent Luecke", "email": "trent@teambuildr.com"} in t.attendees
