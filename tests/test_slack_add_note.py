import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.slack_add_note import (
    fuzzy_match_people,
    best_match_project,
    resolve_tag,
    format_confirmation,
)


def _write_people(tmp_path, people):
    p = tmp_path / "people_registry.json"
    p.write_text(json.dumps({"version": 1, "people": people}))
    return p


def _write_projects(tmp_path, projects):
    p = tmp_path / "projects_registry.json"
    p.write_text(json.dumps({"version": 1, "projects": projects}))
    return p


def _write_tags(tmp_path, tags):
    p = tmp_path / "notes_tags.json"
    p.write_text(json.dumps(tags))
    return p


# ── fuzzy_match_people ────────────────────────────────────────────────────────

def test_fuzzy_match_people_single(tmp_path):
    reg = _write_people(tmp_path, [
        {"id": "jane-doe", "canonical_name": "Jane Doe", "aliases": []},
        {"id": "bob-smith", "canonical_name": "Bob Smith", "aliases": []},
    ])
    matches = fuzzy_match_people("jane", reg)
    assert len(matches) == 1
    assert matches[0]["id"] == "jane-doe"


def test_fuzzy_match_people_ambiguous(tmp_path):
    reg = _write_people(tmp_path, [
        {"id": "jane-doe", "canonical_name": "Jane Doe", "aliases": []},
        {"id": "jane-roe", "canonical_name": "Jane Roe", "aliases": []},
    ])
    matches = fuzzy_match_people("jane", reg)
    assert len(matches) == 2


def test_fuzzy_match_people_none(tmp_path):
    reg = _write_people(tmp_path, [{"id": "bob", "canonical_name": "Bob", "aliases": []}])
    assert fuzzy_match_people("zzz", reg) == []


def test_fuzzy_match_people_exact_wins_over_substring(tmp_path):
    # "Jon" is a substring of "Jon Smith"; an exact match on the full name must
    # resolve to exactly one person so the disambiguation loop terminates.
    reg = _write_people(tmp_path, [
        {"id": "jon", "canonical_name": "Jon", "aliases": []},
        {"id": "jon-smith", "canonical_name": "Jon Smith", "aliases": []},
    ])
    matches = fuzzy_match_people("Jon Smith", reg)
    assert len(matches) == 1
    assert matches[0]["id"] == "jon-smith"


# ── best_match_project ────────────────────────────────────────────────────────

def test_best_match_project_hit(tmp_path):
    reg = _write_projects(tmp_path, [
        {"id": "acme-onboarding", "canonical_name": "Acme Onboarding", "aliases": []},
        {"id": "beta-launch", "canonical_name": "Beta Launch", "aliases": []},
    ])
    match = best_match_project("acme", reg)
    assert match is not None
    assert match["id"] == "acme-onboarding"


def test_best_match_project_miss(tmp_path):
    reg = _write_projects(tmp_path, [{"id": "beta-launch", "canonical_name": "Beta Launch", "aliases": []}])
    assert best_match_project("acme", reg) is None


def test_best_match_project_empty_raw(tmp_path):
    reg = _write_projects(tmp_path, [{"id": "beta-launch", "canonical_name": "Beta Launch", "aliases": []}])
    assert best_match_project("", reg) is None


# ── resolve_tag ───────────────────────────────────────────────────────────────

def test_resolve_tag_known(tmp_path):
    tags = _write_tags(tmp_path, [{"id": "SALES", "color": "#2a6b3a"}])
    resolved, dropped = resolve_tag("sales", tags)
    assert resolved == "SALES"
    assert dropped is None


def test_resolve_tag_unknown_is_dropped(tmp_path):
    tags = _write_tags(tmp_path, [{"id": "SALES", "color": "#2a6b3a"}])
    resolved, dropped = resolve_tag("zzz", tags)
    assert resolved is None
    assert dropped == "ZZZ"


def test_resolve_tag_empty(tmp_path):
    tags = _write_tags(tmp_path, [{"id": "SALES", "color": "#2a6b3a"}])
    assert resolve_tag("", tags) == (None, None)


# ── format_confirmation ───────────────────────────────────────────────────────

def test_format_confirmation_plain():
    assert format_confirmation("call Acme", None, None, None, None) == "Note added: call Acme"


def test_format_confirmation_with_links():
    out = format_confirmation("call Acme", "Jane Doe", "Acme Onboarding", "SALES", None)
    assert "Note added: call Acme" in out
    assert "Jane Doe" in out
    assert "Acme Onboarding" in out
    assert "SALES" in out


def test_format_confirmation_with_dropped_tag():
    out = format_confirmation("call Acme", None, None, None, "ZZZ")
    assert "ZZZ" in out
    assert "not found" in out.lower()


def test_format_confirmation_no_project_match_note():
    out = format_confirmation("call Acme", None, None, None, None, project_missed="acme")
    assert "acme" in out
    assert "no project" in out.lower()
