from dataclasses import dataclass, field
from lib.deal_normalize import normalize_demo_events


@dataclass
class T:
    uuid: str; title: str; start_at: str; call_type: str; os_interested: bool
    rep_name: str = ""; attendees: list = field(default_factory=list)


def _demo(uuid, attendees, ct="demo", os=True):
    return T(uuid, "Demo", "2026-08-10T15:00:00Z", ct, os, "Luke Martin", attendees)


def test_clean_single_domain_demo():
    ev = normalize_demo_events([_demo("u1", [
        {"name": "Ryan Allwein", "email": "ryan@teambuildr.com"},
        {"name": "Jane", "email": "jane@acme.com"},
        {"name": "Bob", "email": "bob@acme.com"},
    ])])[0]
    assert ev.kind == "demo" and ev.email == "jane@acme.com"
    assert ev.rep == "Luke Martin"
    assert ev.payload["contact_emails"] == ["jane@acme.com", "bob@acme.com"]
    assert ev.payload["ambiguous_reason"] is None


def test_multi_domain_flags_reason():
    ev = normalize_demo_events([_demo("u2", [
        {"name": "A", "email": "a@acme.com"},
        {"name": "B", "email": "b@other.com"},
    ])])[0]
    assert ev.payload["ambiguous_reason"] == "multi_domain"


def test_no_email_is_unresolved():
    ev = normalize_demo_events([_demo("u3", [{"name": "NoEmail Guy", "email": ""}])])[0]
    assert ev.email == "unresolved:u3"
    assert ev.payload["ambiguous_reason"] == "no_email"


def test_generic_inbox_flagged():
    ev = normalize_demo_events([_demo("u4", [{"name": "Front Desk", "email": "info@acme.com"}])])[0]
    assert ev.payload["ambiguous_reason"] == "generic_inbox"


def test_non_demo_and_non_os_skipped():
    assert normalize_demo_events([
        _demo("u5", [{"name": "X", "email": "x@acme.com"}], ct="follow_up"),
        _demo("u6", [{"name": "Y", "email": "y@acme.com"}], os=False),
    ]) == []


def test_automated_sender_only_becomes_unresolved():
    # A meeting whose only external email is an automated sender (no-reply@zoom.us)
    # must NOT become a phantom deal — it drops to unresolved/no_email for review.
    ev = normalize_demo_events([_demo("u7", [{"name": "Zoom", "email": "no-reply@zoom.us"}])])[0]
    assert ev.email == "unresolved:u7"
    assert ev.payload["ambiguous_reason"] == "no_email"
    assert "no-reply@zoom.us" not in ev.payload["contact_emails"]


def test_automated_sender_dropped_real_prospect_kept():
    ev = normalize_demo_events([_demo("u8", [
        {"name": "Zoom", "email": "no-reply@zoom.us"},
        {"name": "Jane", "email": "jane@acme.com"},
    ])])[0]
    assert ev.email == "jane@acme.com"
    assert ev.payload["contact_emails"] == ["jane@acme.com"]
    assert ev.payload["ambiguous_reason"] is None


def test_free_email_prospect_is_flagged():
    # A gmail prospect is still a valid key, but the account isn't derivable —
    # flag free_email so a human names the account.
    ev = normalize_demo_events([_demo("u9", [{"name": "Davin", "email": "davinroach@gmail.com"}])])[0]
    assert ev.email == "davinroach@gmail.com"
    assert ev.payload["ambiguous_reason"] == "free_email"
