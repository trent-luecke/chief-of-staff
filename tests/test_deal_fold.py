from lib.deal_events import DealEvent
from lib.deal_fold import build_deals

TODAY = "2026-08-18"


def _demo(uuid, email, ts, contacts, reason=None, rep="Luke Martin"):
    return DealEvent(event_id=uuid, email=email, email_raw="", kind="demo", timestamp=ts,
                     rep=rep, source="avoma",
                     payload={"avoma_uuid": uuid, "contact_emails": contacts, "ambiguous_reason": reason})


def test_dedup_by_email_takes_earliest_demo_date():
    events = [_demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"]),
              _demo("b", "x@acme.com", "2026-08-02T00:00:00Z", ["x@acme.com", "y@acme.com"])]
    deals = build_deals(events, {}, TODAY)
    assert set(deals) == {"x@acme.com"}
    d = deals["x@acme.com"]
    assert d.demo_date == "2026-08-02T00:00:00Z"
    assert d.cycle_start == "2026-08-02T00:00:00Z"
    assert d.outcome == "open" and d.stage == "demoed"
    assert "y@acme.com" in d.contact_emails


def test_fold_is_order_independent():
    e1 = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"])
    e2 = _demo("b", "x@acme.com", "2026-08-02T00:00:00Z", ["x@acme.com"])
    assert build_deals([e1, e2], {}, TODAY)["x@acme.com"].demo_date == \
           build_deals([e2, e1], {}, TODAY)["x@acme.com"].demo_date


def test_ambiguous_reason_sets_identity_review():
    d = build_deals([_demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"], reason="multi_domain")], {}, TODAY)["x@acme.com"]
    assert d.review["needs"] is True and d.review["kind"] == "ambiguous"
    assert d.review["reason"] == "multi_domain"


def test_aged_open_deal_sets_stale_review():
    d = build_deals([_demo("a", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])], {}, TODAY, stale_days=45)["x@acme.com"]
    assert d.review["needs"] is True and d.review["kind"] == "stale_check"


def test_recent_clean_deal_needs_no_review():
    d = build_deals([_demo("a", "x@acme.com", "2026-08-15T00:00:00Z", ["x@acme.com"])], {}, TODAY)["x@acme.com"]
    assert d.review["needs"] is False


def test_account_name_from_crosswalk_then_domain():
    deals = build_deals([_demo("a", "x@acme.com", "2026-08-15T00:00:00Z", ["x@acme.com"])],
                        {"x@acme.com": "Acme Barbell"}, TODAY)
    assert deals["x@acme.com"].account_name == "Acme Barbell"
    deals2 = build_deals([_demo("b", "y@acme.com", "2026-08-15T00:00:00Z", ["y@acme.com"])], {}, TODAY)
    assert deals2["y@acme.com"].account_name == "Acme"


def test_unresolved_key_has_blank_account():
    d = build_deals([_demo("u1", "unresolved:u1", "2026-08-15T00:00:00Z", [], reason="no_email")], {}, TODAY)["unresolved:u1"]
    assert d.account_name == ""
    assert d.review["kind"] == "ambiguous"
