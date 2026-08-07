from scout import backlog


def _cand(domain, seed=False, nov=0.5, icp=0.5, covered=False):
    c = backlog.new_candidate(domain, domain.split(".")[0], f"https://{domain}/",
                              "A", "websearch", "2026-08-06", seed=seed)
    c["novelty_score"] = nov
    c["icp_relevance"] = icp
    c["covered"] = covered
    return c


def test_new_candidate_shape():
    c = backlog.new_candidate("xoda.com", "Xoda", "https://xoda.com/", "A", "seed", "2026-08-06", seed=True)
    assert c["domain"] == "xoda.com"
    assert c["seed"] is True
    assert c["covered"] is False
    assert c["content_hash"] is None


def test_add_dedups_by_domain():
    records = []
    assert backlog.add(records, _cand("a.com")) is True
    assert backlog.add(records, _cand("a.com")) is False
    assert len(records) == 1


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "candidates.jsonl"
    records = [_cand("a.com"), _cand("b.com")]
    backlog.save(records, p)
    loaded = backlog.load(p)
    assert [r["domain"] for r in loaded] == ["a.com", "b.com"]


def test_load_missing_file_returns_empty(tmp_path):
    assert backlog.load(tmp_path / "nope.jsonl") == []


def test_mark_covered_sets_fields():
    records = [_cand("a.com")]
    backlog.mark_covered(records, "a.com", "hash123", "2026-08-07")
    assert records[0]["covered"] is True
    assert records[0]["content_hash"] == "hash123"
    assert records[0]["covered_at"] == "2026-08-07"


def test_select_prioritizes_seeds_then_score():
    records = [
        _cand("low.com", nov=0.1, icp=0.1),
        _cand("high.com", nov=0.9, icp=0.9),
        _cand("seed.com", seed=True, nov=0.0, icp=0.0),
    ]
    picked = backlog.select_uncovered(records, 2)
    assert picked[0]["domain"] == "seed.com"      # seed first despite low score
    assert picked[1]["domain"] == "high.com"      # then best score


def test_select_skips_covered():
    records = [_cand("done.com", covered=True), _cand("open.com")]
    picked = backlog.select_uncovered(records, 2)
    assert [r["domain"] for r in picked] == ["open.com"]
