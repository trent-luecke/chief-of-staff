import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from market_intel import slugify, build_rss_url, parse_classification


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
