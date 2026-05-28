import json
import pytest
from datetime import date
from lib.storage import LocalStorage


def _storage(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


def test_mark_resolved_writes_entry(tmp_path):
    from lib.resolved_actions import mark_resolved, load_all_resolved
    s = _storage(tmp_path)
    mark_resolved(s, "john-smith", "John Smith", ["Send pricing deck"], "Demo: John Smith")
    store = load_all_resolved(s)
    assert "john-smith" in store
    assert store["john-smith"]["resolved"][0]["text"] == "Send pricing deck"
    assert store["john-smith"]["resolved"][0]["resolved_date"] == date.today().isoformat()


def test_mark_resolved_deduplicates(tmp_path):
    from lib.resolved_actions import mark_resolved, load_all_resolved
    s = _storage(tmp_path)
    mark_resolved(s, "john-smith", "John Smith", ["Send pricing deck"], "Demo")
    mark_resolved(s, "john-smith", "John Smith", ["Send pricing deck"], "Follow-up")
    store = load_all_resolved(s)
    assert len(store["john-smith"]["resolved"]) == 1


def test_mark_resolved_multiple_items(tmp_path):
    from lib.resolved_actions import mark_resolved, load_all_resolved
    s = _storage(tmp_path)
    mark_resolved(s, "ryan-pace", "Ryan Pace", ["Item A", "Item B"], "Demo")
    store = load_all_resolved(s)
    texts = [r["text"] for r in store["ryan-pace"]["resolved"]]
    assert "Item A" in texts
    assert "Item B" in texts


def test_get_resolved_for_tokens_matches_slug(tmp_path):
    from lib.resolved_actions import mark_resolved, get_resolved_for_tokens
    s = _storage(tmp_path)
    mark_resolved(s, "ryan-pace", "Ryan Pace", ["Send contract"], "Demo")
    results = get_resolved_for_tokens(s, ["ryan", "pace"])
    assert len(results) == 1
    assert results[0]["text"] == "Send contract"


def test_get_resolved_for_tokens_no_match(tmp_path):
    from lib.resolved_actions import mark_resolved, get_resolved_for_tokens
    s = _storage(tmp_path)
    mark_resolved(s, "ryan-pace", "Ryan Pace", ["Send contract"], "Demo")
    results = get_resolved_for_tokens(s, ["john", "smith"])
    assert results == []


def test_get_resolved_for_tokens_empty_store(tmp_path):
    from lib.resolved_actions import get_resolved_for_tokens
    s = _storage(tmp_path)
    assert get_resolved_for_tokens(s, ["anyone"]) == []
