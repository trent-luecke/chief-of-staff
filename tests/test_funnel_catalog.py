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


def _valid_asset(**overrides):
    base = {
        "title": "CrossFit ROI calculator",
        "type": "roi_calculator",
        "stage": "BOFU",
        "sub_stage": "evaluation",
        "product": "os",
        "icp": ["crossfit"],
        "status": "planned",
        "source": "campaign_audit",
    }
    base.update(overrides)
    return base


def test_validate_accepts_good_asset():
    assert fc.validate_asset(_valid_asset()) == []


def test_validate_flags_unknown_type():
    errs = fc.validate_asset(_valid_asset(type="tiktok_dance"))
    assert any("type" in e for e in errs)


def test_validate_flags_substage_stage_mismatch():
    errs = fc.validate_asset(_valid_asset(stage="TOFU", sub_stage="evaluation"))
    assert any("sub_stage" in e for e in errs)


def test_validate_flags_unknown_icp_and_empty_icp():
    assert any("icp" in e for e in fc.validate_asset(_valid_asset(icp=["yoga_studio"])))
    assert any("icp" in e for e in fc.validate_asset(_valid_asset(icp=[])))


def test_validate_flags_missing_required_field():
    a = _valid_asset()
    del a["title"]
    assert any("title" in e for e in fc.validate_asset(a))


def test_validate_flags_bad_publish_date():
    assert any("publish_date" in e for e in fc.validate_asset(_valid_asset(publish_date="05/14/2026")))


def test_validate_rejects_non_dashed_and_week_dates():
    # strict YYYY-MM-DD only
    assert any("publish_date" in e for e in fc.validate_asset(_valid_asset(publish_date="20260514")))
    assert any("publish_date" in e for e in fc.validate_asset(_valid_asset(publish_date="2026-W20-1")))
    assert any("added_at" in e for e in fc.validate_asset(_valid_asset(added_at="20260514")))
    # a genuinely valid date still passes
    assert fc.validate_asset(_valid_asset(publish_date="2026-05-14")) == []


def test_stage_type_warning_fires_on_odd_combo():
    w = fc.stage_type_warning(_valid_asset(type="blog", stage="BOFU", sub_stage="decision"))
    assert w is not None and "blog" in w


def test_stage_type_warning_silent_on_expected_and_flexible():
    assert fc.stage_type_warning(_valid_asset(type="roi_calculator", stage="BOFU")) is None
    assert fc.stage_type_warning(
        _valid_asset(type="interactive_tool", stage="TOFU", sub_stage="awareness")
    ) is None


def test_normalize_collapses_case_and_space():
    assert fc._normalize("  Member   Retention ") == "member retention"


def test_find_duplicates_by_title_and_url():
    catalog = [
        _valid_asset(title="Member Retention Guide", url="https://a.co/x"),
        _valid_asset(title="Other"),
    ]
    by_title = fc.find_duplicates(_valid_asset(title="member  retention guide"), catalog)
    assert len(by_title) == 1
    by_url = fc.find_duplicates(_valid_asset(title="Totally New", url="https://a.co/x"), catalog)
    assert len(by_url) == 1
    assert fc.find_duplicates(_valid_asset(title="Nothing Alike"), catalog) == []


def test_similar_themes_matches_fragments():
    catalog = [
        _valid_asset(theme="member retention"),
        _valid_asset(theme="pricing transparency"),
    ]
    hits = fc.similar_themes("retention", catalog)
    assert "member retention" in hits
    assert "pricing transparency" not in hits
    assert fc.similar_themes("brand awareness", catalog) == []


def test_similar_themes_dedupes_repeated_theme():
    catalog = [
        _valid_asset(theme="member retention"),
        _valid_asset(theme="Member  Retention"),  # same normalized theme, different casing
    ]
    hits = fc.similar_themes("retention", catalog)
    # de-duped by normalized form: the theme appears once, not twice
    assert len(hits) == 1


def test_similar_themes_skips_entries_without_theme():
    catalog = [
        _valid_asset(theme="member retention"),
        {"title": "no theme here"},          # missing theme key
        _valid_asset(theme=""),               # empty theme
    ]
    hits = fc.similar_themes("retention", catalog)
    assert hits == ["member retention"]       # only the real theme, no crash on the others


def test_find_duplicates_no_false_positive_from_empty_fields():
    # An existing entry with empty title AND empty url must NOT match a candidate
    # that also has empty title/url — empty strings are not a match signal.
    catalog = [{"title": "", "url": ""}]
    candidate = {"title": "", "url": ""}
    assert fc.find_duplicates(candidate, catalog) == []


import pytest


def test_add_asset_fills_id_and_date_and_appends():
    catalog = []
    stored = fc.add_asset(_valid_asset(), catalog, today="2026-08-26")
    assert stored["id"].startswith("asset-")
    assert stored["added_at"] == "2026-08-26"
    assert catalog == [stored]


def test_add_asset_preserves_existing_id_and_date():
    stored = fc.add_asset(
        _valid_asset(id="asset-fixed1", added_at="2026-01-01"), [], today="2026-08-26"
    )
    assert stored["id"] == "asset-fixed1"
    assert stored["added_at"] == "2026-01-01"


def test_add_asset_raises_on_invalid():
    with pytest.raises(ValueError):
        fc.add_asset(_valid_asset(type="bad_type"), [])


def test_dispersion_counts_axes():
    catalog = [
        _valid_asset(stage="TOFU", sub_stage="awareness", type="blog",
                     icp=["crossfit", "sports_performance"], theme="retention",
                     status="live", product="os"),
        _valid_asset(stage="TOFU", sub_stage="awareness", type="blog",
                     icp=["crossfit"], theme="retention", status="planned", product="os"),
        _valid_asset(stage="MOFU", sub_stage="consideration", type="webinar",
                     icp=["pt_studio"], theme="onboarding", status="planned", product="both"),
    ]
    d = fc.dispersion(catalog)
    assert d["total"] == 3
    assert d["by_stage"] == {"TOFU": 2, "MOFU": 1}
    assert d["by_type"]["blog"] == 2
    assert d["by_icp"]["crossfit"] == 2
    assert d["by_theme"]["retention"] == 2
    assert d["by_product"]["os"] == 2
    assert d["by_stage_status"]["TOFU"] == {"live": 1, "planned": 1}
