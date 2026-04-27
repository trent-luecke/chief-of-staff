import json
import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from market_intel import (
    slugify,
    build_rss_url,
    parse_classification,
    load_seen_urls,
    save_seen_urls,
    load_competitors,
    load_queries,
    deduplicate_items,
)


def test_slugify_basic():
    assert slugify("PushPress Launches AI Feature") == "pushpress-launches-ai-feature"


def test_slugify_special_chars():
    assert slugify("ABC/Glofox: New Update!") == "abcglofox-new-update"


def test_slugify_truncates_long_title():
    long_title = "a" * 200
    result = slugify(long_title)
    assert len(result) <= 80


def test_build_rss_url_contains_domain():
    url = build_rss_url("gym management software")
    assert "news.google.com" in url


def test_build_rss_url_contains_query():
    url = build_rss_url("PushPress gym")
    assert "PushPress" in url or "pushpress" in url.lower()


def test_build_rss_url_contains_recency():
    url = build_rss_url("gym software")
    assert "7d" in url


def test_parse_classification_valid():
    raw = '{"category": "feature_launch", "relevance_score": 4, "competitor": "PushPress", "summary": "Test.", "action_flag": true}'
    result = parse_classification(raw)
    assert result["category"] == "feature_launch"
    assert result["relevance_score"] == 4
    assert result["competitor"] == "PushPress"
    assert result["action_flag"] is True


def test_parse_classification_strips_markdown_fences():
    raw = '```json\n{"category": "noise", "relevance_score": 1, "competitor": null, "summary": "nothing", "action_flag": false}\n```'
    result = parse_classification(raw)
    assert result["category"] == "noise"
    assert result["competitor"] is None


def test_parse_classification_invalid_returns_none():
    result = parse_classification("not json at all")
    assert result is None


def test_load_seen_urls_empty(tmp_path):
    f = tmp_path / "seen_urls.json"
    f.write_text('{"seen": []}')
    result = load_seen_urls(f)
    assert result == set()


def test_load_seen_urls_with_entries(tmp_path):
    f = tmp_path / "seen_urls.json"
    f.write_text('{"seen": ["http://a.com", "http://b.com"]}')
    result = load_seen_urls(f)
    assert "http://a.com" in result
    assert len(result) == 2


def test_save_and_reload_seen_urls(tmp_path):
    f = tmp_path / "seen_urls.json"
    urls = {"http://x.com", "http://y.com"}
    save_seen_urls(urls, f)
    data = json.loads(f.read_text())
    assert set(data["seen"]) == urls


def test_load_competitors_count():
    competitors = load_competitors()
    assert len(competitors) == 20


def test_load_competitors_has_required_fields():
    competitors = load_competitors()
    for c in competitors:
        assert "name" in c
        assert "website" in c
        assert "blog_url" in c
    assert any(c["name"] == "PushPress" for c in competitors)


def test_load_queries_count():
    queries = load_queries()
    assert len(queries) == 20


def test_load_queries_has_key_terms():
    queries = load_queries()
    assert "gym management software" in queries
    assert "fitness AI software" in queries


def test_deduplicate_items_filters_seen():
    seen = {"http://already.com"}
    items = [
        {"url": "http://already.com", "title": "Old"},
        {"url": "http://new.com", "title": "New"},
    ]
    new_items, updated = deduplicate_items(items, seen)
    assert len(new_items) == 1
    assert new_items[0]["url"] == "http://new.com"
    assert "http://new.com" in updated
    assert "http://already.com" in updated


def test_deduplicate_items_no_duplicates_within_batch():
    seen = set()
    items = [
        {"url": "http://a.com", "title": "A"},
        {"url": "http://a.com", "title": "A duplicate"},
        {"url": "http://b.com", "title": "B"},
    ]
    new_items, updated = deduplicate_items(items, seen)
    assert len(new_items) == 2
    assert len(updated) == 2
