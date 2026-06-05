# tests/test_onboarding_collector.py
import json
import tempfile

from collectors.onboarding import load_onboarding_active


ACTIVE = ["In Progress", "Awaiting Customer", "Ready to Go Live"]

FIXTURE_CACHE = {
    "synced_at": "2026-06-04T12:00:00Z",
    "records": [
        {"page_id": "a1", "customer_name": "Acme Strength", "status": "In Progress",
         "current_phase": "Phase 3", "sales_rep": "Chris", "start_date": "2026-05-01",
         "target_go_live_date": "2026-06-10", "customer_email": "a@acme.com"},
        {"page_id": "a2", "customer_name": "Peak Perf", "status": "Awaiting Customer",
         "current_phase": "Phase 5", "sales_rep": "Jeff", "start_date": "2026-05-10",
         "target_go_live_date": "2026-06-15", "customer_email": "b@peak.com"},
        {"page_id": "a3", "customer_name": "Old Gym", "status": "Live",
         "current_phase": "Phase 7", "sales_rep": "Ryan", "start_date": "2026-04-01",
         "target_go_live_date": "2026-05-01", "customer_email": "c@old.com"},
        {"page_id": "a4", "customer_name": "Warm Lead", "status": "Not Started",
         "current_phase": None, "sales_rep": "Trent", "start_date": None,
         "target_go_live_date": None, "customer_email": "d@warm.com"},
        {"page_id": "a5", "customer_name": "Almost There", "status": "Ready to Go Live",
         "current_phase": "Phase 7", "sales_rep": "Martin", "start_date": "2026-05-20",
         "target_go_live_date": "2026-06-05", "customer_email": "e@almost.com"},
    ],
}


def _write_fixture(data: dict) -> str:
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    json.dump(data, f)
    f.close()
    return f.name


def test_load_onboarding_active_filters_to_active_statuses():
    path = _write_fixture(FIXTURE_CACHE)
    result = load_onboarding_active(path, ACTIVE)
    assert len(result) == 3
    names = {r["customer_name"] for r in result}
    assert names == {"Acme Strength", "Peak Perf", "Almost There"}


def test_load_onboarding_active_excludes_live_and_not_started():
    path = _write_fixture(FIXTURE_CACHE)
    result = load_onboarding_active(path, ACTIVE)
    statuses = {r["status"] for r in result}
    assert "Live" not in statuses
    assert "Not Started" not in statuses


def test_load_onboarding_active_returns_empty_on_missing_file():
    result = load_onboarding_active("/nonexistent/path.json", ACTIVE)
    assert result == []


def test_load_onboarding_active_returns_empty_on_corrupt_json():
    f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
    f.write("not json {{{")
    f.close()
    result = load_onboarding_active(f.name, ACTIVE)
    assert result == []


def test_load_onboarding_active_handles_empty_records():
    path = _write_fixture({"synced_at": "2026-06-04T12:00:00Z", "records": []})
    result = load_onboarding_active(path, ACTIVE)
    assert result == []
