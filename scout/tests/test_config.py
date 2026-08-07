from scout import config


def test_load_config_has_required_keys():
    cfg = config.load_config()
    for key in ("recipient", "teardowns_per_week", "search_queries", "exclude_domains"):
        assert key in cfg
    assert cfg["recipient"] == "trent@teambuildr.com"
    assert cfg["teardowns_per_week"] == 2


def test_load_grounding_is_nonempty_and_mentions_taxonomy():
    text = config.load_grounding()
    assert len(text) > 500
    # grounding must carry the taxonomy the teardown prompt depends on
    assert "Real gap" in text
    assert "JTBD" in text
