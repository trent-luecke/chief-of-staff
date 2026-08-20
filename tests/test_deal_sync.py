from dataclasses import dataclass, field
from unittest.mock import patch
from lib.storage import LocalStorage
from lib.deal_sync import refresh_deal_store


@dataclass
class T:
    uuid: str; title: str; start_at: str; call_type: str; os_interested: bool
    rep_name: str = ""; attendees: list = field(default_factory=list)


def test_refresh_builds_events_cache_and_pushes(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    transcripts = [T("u1", "Demo", "2026-08-15T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Ryan Allwein", "email": "ryan@teambuildr.com"},
                      {"name": "Jane", "email": "jane@acme.com"}])]
    with patch("lib.deal_sync.push_deals", return_value={"inserted": 1}) as mp:
        out = refresh_deal_store(transcripts, s, today="2026-08-18",
                                 fetched_at="2026-08-18T00:00:00Z",
                                 base_url="https://engine", password="pw")
    assert out == {"deals": 1, "appended": 1, "pushed": True}
    cache = s.read_json("deal_pipeline_cache.json")
    assert cache["leads"][0]["email"] == "jane@acme.com"
    assert cache["leads"][0]["status"] == "demoed"
    assert mp.call_count == 1


def test_refresh_is_idempotent_and_skips_push_without_base_url(tmp_path):
    s = LocalStorage(base_dir=str(tmp_path))
    transcripts = [T("u1", "Demo", "2026-08-15T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Jane", "email": "jane@acme.com"}])]
    refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z")
    out = refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z")
    assert out == {"deals": 1, "appended": 0, "pushed": False}


def test_refresh_ingests_sales_when_config_provided(tmp_path, monkeypatch):
    s = LocalStorage(base_dir=str(tmp_path))
    transcripts = [T("u1", "Demo", "2026-08-01T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Jane", "email": "jane@acme.com"}])]
    monkeypatch.setattr(
        "lib.deal_sync.fetch_sale_rows",
        lambda config, today: [{"date": "8/15/2026", "total_sale": "$1,200",
                                "customer_name": "Acme", "customer_email": "jane@acme.com",
                                "salesperson": "Luke Martin", "source": "os_only"}],
    )
    out = refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z",
                             config={"meeting_prep": {"sheets": {"sales_spreadsheet_id": "SID"}}})
    cache = s.read_json("deal_pipeline_cache.json")
    lead = next(l for l in cache["leads"] if l["email"] == "jane@acme.com")
    assert lead["status"] == "won"
    assert out["appended"] == 2  # 1 demo + 1 sale


def test_refresh_without_config_skips_sales(tmp_path, monkeypatch):
    s = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr("lib.deal_sync.fetch_sale_rows",
                        lambda config, today: (_ for _ in ()).throw(AssertionError("must not fetch")))
    transcripts = [T("u1", "Demo", "2026-08-01T15:00:00Z", "demo", True, "Luke Martin",
                     [{"name": "Jane", "email": "jane@acme.com"}])]
    out = refresh_deal_store(transcripts, s, "2026-08-18", "2026-08-18T00:00:00Z")
    assert out["appended"] == 1  # demo only; sale block not entered
