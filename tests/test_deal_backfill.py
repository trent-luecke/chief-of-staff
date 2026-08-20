from lib.deal_backfill import normalize_seed_events

IMPORT_TS = "2026-08-19T12:00:00Z"


def _lead(**kw):
    base = {"page_id": "p1", "name": "Acme Barbell", "contact": "Jane Doe",
            "email": "jane@acme.com", "status": "In-Trial / Post Demo",
            "priority": "High", "last_contacted": "2026-06-24",
            "estimated_value": 2000, "source": "Calendly Demo"}
    base.update(kw)
    return base


def test_email_lead_keys_by_normalized_email():
    ev = normalize_seed_events([_lead()], IMPORT_TS)[0]
    assert ev.kind == "seed"
    assert ev.email == "jane@acme.com"
    assert ev.source == "notion-backfill"
    assert ev.account_name == "Acme Barbell"
    assert ev.timestamp == "2026-06-24"
    assert ev.payload["stage"] == "in_trial"
    assert ev.payload["outcome"] == "open"
    assert ev.payload["import_ts"] == IMPORT_TS
    assert ev.payload["estimated_value"] == 2000
    assert ev.payload["page_id"] == "p1"


def test_emailless_lead_keys_by_notion_page_id():
    ev = normalize_seed_events([_lead(email=None, name="Baxter Pattison")], IMPORT_TS)[0]
    assert ev.email == "notion:p1"
    assert ev.account_name == "Baxter Pattison"


def test_missing_last_contacted_falls_back_to_import_ts():
    ev = normalize_seed_events([_lead(last_contacted=None)], IMPORT_TS)[0]
    assert ev.timestamp == IMPORT_TS
    assert ev.payload["last_contacted"] is None


def test_event_id_is_deterministic_on_page_id_idempotent():
    a = normalize_seed_events([_lead()], IMPORT_TS)[0]
    b = normalize_seed_events([_lead()], "2099-01-01T00:00:00Z")[0]  # different import_ts
    assert a.event_id == b.event_id  # keyed on page_id + key, not import_ts


def test_closed_and_lost_map_to_terminal_outcomes():
    won = normalize_seed_events([_lead(status="Closed")], IMPORT_TS)[0]
    lost = normalize_seed_events([_lead(status="Lost")], IMPORT_TS)[0]
    assert won.payload["stage"] == "won" and won.payload["outcome"] == "won"
    assert lost.payload["stage"] == "lost" and lost.payload["outcome"] == "lost"


def test_lead_without_page_id_is_skipped_not_raised():
    out = normalize_seed_events([{"name": "No Id", "status": "Lost"}], IMPORT_TS)
    assert out == []
