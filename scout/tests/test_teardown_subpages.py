"""Link-guided sub-page selection for teardowns (pure logic, no network)."""
from scout import teardown


def test_ranks_pricing_and_features_over_about():
    base = "https://coachway.io/"
    links = [
        "https://coachway.io/about",
        "https://coachway.io/features",
        "https://coachway.io/pricing",
    ]
    # pricing (tier 3) and features (tier 2) beat about (tier 1); capped at 2
    assert teardown.select_subpages(base, links, limit=2) == [
        "https://coachway.io/pricing",
        "https://coachway.io/features",
    ]


def test_discovers_nonstandard_paths():
    base = "https://coachway.io/"
    links = ["https://coachway.io/plans", "https://coachway.io/how-it-works"]
    result = teardown.select_subpages(base, links, limit=3)
    assert "https://coachway.io/plans" in result
    assert "https://coachway.io/how-it-works" in result


def test_filters_external_domains():
    base = "https://coachway.io/"
    links = [
        "https://twitter.com/coachway",
        "https://coachway.io/pricing",
        "https://medium.com/pricing",  # external even though it says 'pricing'
    ]
    assert teardown.select_subpages(base, links, limit=3) == ["https://coachway.io/pricing"]


def test_keeps_same_registrable_domain_subdomains():
    base = "https://coachway.io/"
    links = ["https://app.coachway.io/pricing"]
    assert teardown.select_subpages(base, links, limit=3) == ["https://app.coachway.io/pricing"]


def test_skips_homepage_and_dedups_trailing_slash():
    base = "https://coachway.io/"
    links = [
        "https://coachway.io/",
        "https://coachway.io",
        "https://coachway.io/pricing",
        "https://coachway.io/pricing/",  # dup of pricing
    ]
    assert teardown.select_subpages(base, links, limit=5) == ["https://coachway.io/pricing"]


def test_drops_irrelevant_paths():
    base = "https://coachway.io/"
    links = [
        "https://coachway.io/blog/some-post",
        "https://coachway.io/login",
        "https://coachway.io/careers",
    ]
    assert teardown.select_subpages(base, links, limit=3) == []


def test_respects_limit_highest_tier_first():
    base = "https://coachway.io/"
    links = [
        "https://coachway.io/about",
        "https://coachway.io/features",
        "https://coachway.io/product",
        "https://coachway.io/pricing",
    ]
    result = teardown.select_subpages(base, links, limit=2)
    assert len(result) == 2
    assert result[0] == "https://coachway.io/pricing"  # tier 3 wins the top slot
