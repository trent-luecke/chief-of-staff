# tests/test_deal_projection.py
from lib.deal_fold import Deal
from lib.deal_projection import deals_to_pipeline_cache

_CACHE_LEAD_KEYS = {"page_id", "name", "contact", "email", "status", "priority",
                    "last_contacted", "days_since_contact", "estimated_value", "source", "stale"}


def test_projection_matches_cache_schema():
    d = Deal(email="x@acme.com", account_name="Acme", rep="Luke Martin",
             demo_date="2026-08-10T00:00:00Z", cycle_start="2026-08-10T00:00:00Z",
             stage="demoed", contact_emails=["x@acme.com"], last_event_at="2026-08-10T00:00:00Z",
             review={"needs": False})
    out = deals_to_pipeline_cache({"x@acme.com": d}, "2026-08-18T00:00:00Z")
    assert out["fetched_at"] == "2026-08-18T00:00:00Z"
    lead = out["leads"][0]
    assert set(lead.keys()) == _CACHE_LEAD_KEYS
    assert lead["page_id"] == "deal:x@acme.com"
    assert lead["name"] == "Acme" and lead["email"] == "x@acme.com"
    assert lead["status"] == "demoed" and lead["stale"] is False


def test_stale_review_maps_to_stale_flag():
    d = Deal(email="x@acme.com", stage="demoed", review={"needs": True, "kind": "stale_check"})
    assert deals_to_pipeline_cache({"x@acme.com": d}, "t")["leads"][0]["stale"] is True


def test_unresolved_key_blanks_email():
    d = Deal(email="unresolved:u1", stage="demoed", review={"needs": True, "kind": "ambiguous"})
    lead = deals_to_pipeline_cache({"unresolved:u1": d}, "t")["leads"][0]
    assert lead["email"] == ""
