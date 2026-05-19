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
    dedup_by_title,
    format_daily_email,
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


def test_dedup_by_title_empty():
    assert dedup_by_title([]) == []


def test_dedup_by_title_single():
    items = [{"title": "Gymdesk Launches WOD Tracker", "relevance_score": 4}]
    assert dedup_by_title(items) == items


def test_dedup_by_title_keeps_distinct():
    items = [
        {"title": "Gymdesk Launches WOD Tracker", "relevance_score": 4},
        {"title": "Gymdesk Launches Mobile App", "relevance_score": 4},
    ]
    result = dedup_by_title(items)
    assert len(result) == 2


def test_dedup_by_title_collapses_near_duplicates():
    items = [
        {"title": "Run Clubs Replace Bars Young Adults Social Fitness", "relevance_score": 3},
        {"title": "Run Clubs Replace Bars Young Adults Dating Scene", "relevance_score": 4},
    ]
    result = dedup_by_title(items)
    assert len(result) == 1
    # keeps the higher-scored item
    assert result[0]["relevance_score"] == 4


def test_dedup_by_title_collapses_exact_duplicate():
    items = [
        {"title": "Gymdesk Launches WOD Tracker", "relevance_score": 4},
        {"title": "Gymdesk Launches WOD Tracker", "relevance_score": 3},
    ]
    result = dedup_by_title(items)
    assert len(result) == 1
    assert result[0]["relevance_score"] == 4


def test_dedup_by_title_threshold_respected():
    # these two titles share only stop words — should NOT be collapsed
    items = [
        {"title": "GLP-1 Drugs Drive Gym Membership Growth", "relevance_score": 4},
        {"title": "Run Clubs Replace Dating Apps for Gen Z", "relevance_score": 4},
    ]
    result = dedup_by_title(items)
    assert len(result) == 2


def _make_record(title, category, score, competitor=None, action_flag=False, summary=None, url="http://example.com"):
    return {
        "title": title,
        "category": category,
        "relevance_score": score,
        "competitor": competitor,
        "action_flag": action_flag,
        "summary": summary or f"First sentence about {title}. Second sentence with more detail. Third sentence.",
        "url": url,
        "date_found": "2026-05-19",
        "source": "Test",
    }


def test_format_daily_email_subject():
    records = [_make_record("Gymdesk WOD Tracker", "feature_launch", 4, "Gymdesk")]
    subject, _ = format_daily_email(records, "2026-05-19")
    assert "2026-05-19" in subject
    assert "Market Intel" in subject


def test_format_daily_email_action_needed_block_present():
    records = [
        _make_record("Urgent Feature", "feature_launch", 5, "Gymdesk", action_flag=True),
        _make_record("Normal Feature", "feature_launch", 4, "Zen Planner"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    assert "ACTION NEEDED" in body


def test_format_daily_email_action_needed_block_absent_when_none():
    records = [_make_record("Normal Feature", "feature_launch", 4, "Gymdesk")]
    _, body = format_daily_email(records, "2026-05-19")
    assert "ACTION NEEDED" not in body


def test_format_daily_email_action_items_excluded_from_category():
    records = [
        _make_record("Urgent Feature", "feature_launch", 5, "Gymdesk", action_flag=True),
        _make_record("Normal Feature", "feature_launch", 4, "Zen Planner"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    assert "Zen Planner" in body
    lines = body.split("\n")
    urgent_count = sum(1 for l in lines if "Urgent Feature" in l)
    assert urgent_count >= 1


def test_format_daily_email_top_two_leads_shown():
    records = [
        _make_record("Gymdesk Launches WOD Tracker", "feature_launch", 5, "CompA", url="http://a.com"),
        _make_record("PushPress Adds Nutrition Tracking", "feature_launch", 4, "CompB", url="http://b.com"),
        _make_record("Zen Planner Updates Mobile App", "feature_launch", 3, "CompC", url="http://c.com"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    assert "[1]" in body
    assert "[2]" in body
    assert "Honorable mentions:" in body
    assert "CompC" in body


def test_format_daily_email_honorable_mention_is_one_liner():
    long_summary = "First sentence. Second sentence. Third sentence."
    records = [
        _make_record("Gymdesk Launches WOD Tracker", "feature_launch", 5, "CompA", summary=long_summary),
        _make_record("PushPress Adds Nutrition Tracking", "feature_launch", 4, "CompB", summary=long_summary),
        _make_record("Zen Planner Updates Mobile App", "feature_launch", 3, "CompC", summary=long_summary, url="http://c.com"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    assert "Second sentence" not in body.split("Honorable mentions:")[1]
    assert "First sentence." in body.split("Honorable mentions:")[1]


def test_format_daily_email_dedup_within_category():
    records = [
        _make_record("Run Clubs Replace Bars Young Adults Social Fitness", "industry_trend", 3, competitor="Source A"),
        _make_record("Run Clubs Replace Bars Young Adults Dating Scene", "industry_trend", 4, competitor="Source B"),
        _make_record("Gymdesk Launches WOD Tracker", "feature_launch", 4, "Gymdesk"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    # Near-duplicate industry_trend articles from different competitors should collapse
    assert body.count("Run Clubs") == 1


def test_format_daily_email_category_label_human_readable():
    records = [_make_record("Some Feature", "feature_launch", 4, "CompA")]
    _, body = format_daily_email(records, "2026-05-19")
    assert "FEATURE LAUNCH" in body
    assert "feature_launch" not in body


def test_format_daily_email_industry_competitor_label():
    records = [_make_record("Industry Article", "industry_trend", 4, competitor=None)]
    _, body = format_daily_email(records, "2026-05-19")
    assert "Industry" in body


def test_first_sentence_single_sentence():
    from market_intel import _first_sentence
    assert _first_sentence("Only one sentence.") == "Only one sentence."


def test_first_sentence_multi_sentence():
    from market_intel import _first_sentence
    result = _first_sentence("First sentence. Second sentence. Third sentence.")
    assert result == "First sentence."


def test_first_sentence_no_period():
    from market_intel import _first_sentence
    result = _first_sentence("No period at end")
    assert result == "No period at end"


def test_format_daily_email_empty_records():
    subject, body = format_daily_email([], "2026-05-19")
    assert "2026-05-19" in subject
    assert "Market Intel" in subject


def test_format_daily_email_single_lead_category():
    records = [_make_record("Only Article", "feature_launch", 4, "CompA")]
    _, body = format_daily_email(records, "2026-05-19")
    assert "[1]" in body
    assert "Honorable mentions:" not in body
