from lib.deal_events import DealEvent
from lib.deal_fold import build_deals
from lib.deal_fold import _group_components, _canonical_key

TODAY = "2026-08-18"


def _demo(uuid, email, ts, contacts, reason=None, rep="Luke Martin"):
    return DealEvent(event_id=uuid, email=email, email_raw="", kind="demo", timestamp=ts,
                     rep=rep, source="avoma",
                     payload={"avoma_uuid": uuid, "contact_emails": contacts, "ambiguous_reason": reason})


def test_group_components_one_per_email_without_edges():
    e1 = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"])
    e2 = _demo("b", "y@beta.com", "2026-08-11T00:00:00Z", ["y@beta.com"])
    comps = _group_components([e1, e2])
    keys = sorted(_canonical_key(c) for c in comps)
    assert keys == ["x@acme.com", "y@beta.com"]


def test_canonical_key_is_earliest_demo_primary():
    # two demos, same component (shared contact), different primaries
    e_late = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com", "shared@acme.com"])
    e_early = _demo("b", "z@acme.com", "2026-08-02T00:00:00Z", ["z@acme.com", "shared@acme.com"])
    comps = _group_components([e_late, e_early])
    assert len(comps) == 1
    assert _canonical_key(comps[0]) == "z@acme.com"  # earliest demo's primary


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


def test_cross_demo_same_domain_merges_to_one_deal():
    # jane and bob, same domain, two separate demos → ONE deal
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com"])
    e2 = _demo("d2", "bob@acme.com", "2026-08-12T00:00:00Z", ["bob@acme.com"])
    # they merge only if a shared contact links them; simulate a shared attendee
    e1.payload["contact_emails"] = ["jane@acme.com", "shared@acme.com"]
    e2.payload["contact_emails"] = ["bob@acme.com", "shared@acme.com"]
    deals = build_deals([e1, e2], {}, TODAY)
    assert len(deals) == 1
    d = list(deals.values())[0]
    assert set(d.contact_emails) >= {"jane@acme.com", "bob@acme.com", "shared@acme.com"}
    assert d.review.get("reason") != "account_conflict"  # one account, no conflict


def test_account_conflict_flagged_when_merge_spans_accounts():
    # a shared person bridges two different-domain demos → account_conflict
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com", "consultant@shared.com"])
    e2 = _demo("d2", "bob@beta.com", "2026-08-12T00:00:00Z", ["bob@beta.com", "consultant@shared.com"])
    deals = build_deals([e1, e2], {}, TODAY)
    assert len(deals) == 1
    d = list(deals.values())[0]
    assert d.review["needs"] is True
    assert d.review["kind"] == "ambiguous"
    assert d.review["reason"] == "account_conflict"


def test_cross_demo_merge_is_order_independent():
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com", "shared@acme.com"])
    e2 = _demo("d2", "bob@acme.com", "2026-08-12T00:00:00Z", ["bob@acme.com", "shared@acme.com"])
    fwd = build_deals([e1, e2], {}, TODAY)
    bwd = build_deals([e2, e1], {}, TODAY)
    assert list(fwd) == list(bwd)
    assert sorted(list(fwd.values())[0].contact_emails) == sorted(list(bwd.values())[0].contact_emails)


def test_same_domain_no_shared_contact_stays_two_deals():
    # No shared attendee between these same-domain demos → merge must NOT
    # happen on domain alone. Two separate deals; Queue A's manual merge
    # action is what would join them later.
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z", ["jane@acme.com"])
    e2 = _demo("d2", "bob@acme.com", "2026-08-12T00:00:00Z", ["bob@acme.com"])
    deals = build_deals([e1, e2], {}, TODAY)
    assert len(deals) == 2
    assert set(deals) == {"jane@acme.com", "bob@acme.com"}


def test_group_components_tolerates_null_or_empty_email():
    # A malformed event (no email) must never raise — the fold is total.
    bad_none = DealEvent(event_id="bad1", email=None, email_raw="", kind="demo",
                          timestamp="2026-08-10T00:00:00Z", rep="Luke Martin", source="avoma",
                          payload={"contact_emails": ["x@acme.com"]})
    bad_empty = DealEvent(event_id="bad2", email="", email_raw="", kind="demo",
                           timestamp="2026-08-11T00:00:00Z", rep="Luke Martin", source="avoma",
                           payload={"contact_emails": ["x@acme.com"]})
    good = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"])
    deals = build_deals([bad_none, bad_empty, good], {}, TODAY)
    assert set(deals) == {"x@acme.com"}


def test_single_multi_domain_demo_keeps_multi_domain_reason():
    # ONE demo whose own attendees span >1 domain is already labeled
    # multi_domain by deal_normalize. No cross-demo merge happened here, so
    # account_conflict must NOT clobber that reason.
    e = _demo("a", "jane@acme.com", "2026-08-10T00:00:00Z",
              ["jane@acme.com", "bob@beta.com"], reason="multi_domain")
    d = build_deals([e], {}, TODAY)["jane@acme.com"]
    assert d.review["reason"] == "multi_domain"
    assert d.review["kind"] == "ambiguous"


def test_free_email_bridge_does_not_trigger_account_conflict():
    # Two same-domain demos bridged by a shared FREE-EMAIL contact. Both
    # accounts resolve to the same domain-derived name, and the free-email
    # bridging contact itself resolves to "" (discarded), so no conflict.
    e1 = _demo("d1", "jane@acme.com", "2026-08-10T00:00:00Z",
               ["jane@acme.com", "shared@gmail.com"])
    e2 = _demo("d2", "bob@acme.com", "2026-08-12T00:00:00Z",
               ["bob@acme.com", "shared@gmail.com"])
    deals = build_deals([e1, e2], {}, TODAY)
    assert len(deals) == 1
    d = list(deals.values())[0]
    assert d.review.get("reason") != "account_conflict"


def _status(uuid, email, ts, status, lost_reason="", check_back=""):
    payload = {"status": status}
    if lost_reason:
        payload["lost_reason"] = lost_reason
    if check_back:
        payload["check_back"] = check_back
    return DealEvent(event_id=uuid, email=email, email_raw="", kind="status", timestamp=ts,
                     rep="", source="ui", payload=payload)


def test_status_lost_sets_outcome_and_clears_review():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])  # aged → would be stale
    lost = _status("s1", "x@acme.com", "2026-08-18T00:00:00Z", "lost", lost_reason="went with competitor")
    d = build_deals([demo, lost], {}, TODAY)["x@acme.com"]
    assert d.outcome == "lost"
    assert d.stage == "lost"
    assert d.lost_reason == "went with competitor"
    assert d.review["needs"] is False


def test_rep_and_reason_are_order_independent():
    e1 = _demo("a", "x@acme.com", "2026-08-10T00:00:00Z", ["x@acme.com"],
               reason="multi_domain", rep="Luke Martin")
    e2 = _demo("b", "x@acme.com", "2026-08-12T00:00:00Z", ["x@acme.com"],
               reason="no_email", rep="Trent Luecke")

    forward = build_deals([e1, e2], {}, TODAY)["x@acme.com"]
    backward = build_deals([e2, e1], {}, TODAY)["x@acme.com"]

    assert forward.rep == backward.rep
    assert forward.review == backward.review


def test_status_hold_suppresses_stale_until_check_back():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])  # aged
    hold = _status("s1", "x@acme.com", "2026-08-10T00:00:00Z", "hold", check_back="2026-09-30")
    d = build_deals([demo, hold], {}, TODAY)["x@acme.com"]  # TODAY = 2026-08-18
    assert d.outcome == "open"
    assert d.review["needs"] is False
    assert d.review.get("check_back") == "2026-09-30"


def test_status_hold_resurfaces_after_check_back_date():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])
    hold = _status("s1", "x@acme.com", "2026-07-01T00:00:00Z", "hold", check_back="2026-08-01")
    d = build_deals([demo, hold], {}, TODAY)["x@acme.com"]  # check_back is in the past
    assert d.review["needs"] is True
    assert d.review["kind"] == "stale_check"


def test_status_active_resets_the_45_day_clock():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])  # would be stale
    active = _status("s1", "x@acme.com", "2026-08-15T00:00:00Z", "active")   # 3 days ago
    d = build_deals([demo, active], {}, TODAY, stale_days=45)["x@acme.com"]
    assert d.review["needs"] is False


def test_status_events_are_order_independent():
    demo = _demo("d1", "x@acme.com", "2026-06-01T00:00:00Z", ["x@acme.com"])
    a = _status("s1", "x@acme.com", "2026-07-01T00:00:00Z", "active")
    h = _status("s2", "x@acme.com", "2026-08-10T00:00:00Z", "hold", check_back="2026-09-30")
    fwd = build_deals([demo, a, h], {}, TODAY)["x@acme.com"].review
    bwd = build_deals([h, a, demo], {}, TODAY)["x@acme.com"].review
    assert fwd == bwd
