from dataclasses import dataclass, field
from lib.demo_detect import detect_demos

COUNTED = {"Ryan Allwein", "Luke Martin", "Chris Reynolds", "Jeff Davidson", "Trent Luecke"}


@dataclass
class T:
    uuid: str; title: str; start_at: str; call_type: str; os_interested: bool
    rep_name: str = ""; participants: list = field(default_factory=list)
    attendees: list = field(default_factory=list)


def test_includes_demo_os_interested_with_rep():
    out = detect_demos([T("u1", "Acme", "2026-06-10T15:00:00Z", "demo", True, "Ryan Allwein",
                          ["Ryan Allwein", "ProspectGuy", "p@acme.com"])], COUNTED)
    assert len(out) == 1
    r = out[0]
    assert r["avoma_uuid"] == "u1" and r["rep"] == "Ryan Allwein"
    assert r["invitee_emails"] == ["p@acme.com"]
    assert "ProspectGuy" in r["invitee_names"]


def test_excludes_non_demo_and_non_os():
    ts = [T("u2", "x", "2026-06-10T15:00:00Z", "follow_up", True, "Ryan Allwein"),
          T("u3", "x", "2026-06-10T15:00:00Z", "demo", False, "Ryan Allwein")]
    assert detect_demos(ts, COUNTED) == []


def test_unmatched_rep_becomes_unassigned_but_counted():
    out = detect_demos([T("u4", "x", "2026-06-10T15:00:00Z", "demo", True, "")], COUNTED)
    assert len(out) == 1 and out[0]["rep"] == "Unassigned"


def test_structured_attendees_take_precedence_and_exclude_internal():
    # Real prospect emails come from the structured `attendees` field; the rep's
    # own @teambuildr.com address must not become a deal key.
    t = T("u5", "Acme", "2026-06-10T15:00:00Z", "demo", True, "Ryan Allwein",
          attendees=[{"name": "Ryan Allwein", "email": "ryan@teambuildr.com"},
                     {"name": "Prospect Guy", "email": "guy@acme.com"},
                     {"name": "Silent Prospect", "email": ""}])
    r = detect_demos([t], COUNTED)[0]
    assert r["invitee_emails"] == ["guy@acme.com"]
    assert r["invitee_names"] == ["Prospect Guy", "Silent Prospect"]


def test_falls_back_to_participants_when_no_structured_attendees():
    # Backward-compat: transcripts without `attendees` still split participants.
    out = detect_demos([T("u6", "Acme", "2026-06-10T15:00:00Z", "demo", True, "Ryan Allwein",
                          ["Ryan Allwein", "ProspectGuy", "p@acme.com"])], COUNTED)
    assert out[0]["invitee_emails"] == ["p@acme.com"]
