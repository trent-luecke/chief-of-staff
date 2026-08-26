from pathlib import Path

from lib import funnel_catalog as fc


def test_load_missing_catalog_returns_empty(tmp_path):
    assert fc.load_catalog(tmp_path / "nope.json") == []


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "sub" / "content_catalog.json"
    assets = [{"id": "asset-abc123", "title": "X"}]
    fc.save_catalog(assets, path)
    assert path.exists()
    assert fc.load_catalog(path) == assets


def test_new_asset_id_shape():
    aid = fc.new_asset_id()
    assert aid.startswith("asset-")
    assert len(aid) == len("asset-") + 6
    assert fc.new_asset_id() != fc.new_asset_id()


def test_vocabularies_present():
    assert fc.STAGES == ["TOFU", "MOFU", "BOFU"]
    assert fc.STAGE_SUBSTAGE["BOFU"] == ["evaluation", "decision"]
    assert "interactive_tool" in fc.TYPES
    assert fc.TYPE_STAGE_HINT["interactive_tool"] is None
    assert fc.TYPE_STAGE_HINT["blog"] == "TOFU"
    assert set(fc.ICPS) == {
        "sports_performance", "crossfit", "pt_studio", "hybrid_clinic_gym", "boutique",
    }
    assert fc.PRODUCTS == ["os", "strength", "both"]
