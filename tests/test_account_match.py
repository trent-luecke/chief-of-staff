# tests/test_account_match.py
from lib.account_match import normalize_name, match_accounts

ACCTS = ["Beyond Our Best, LLC", "The Athlete Standard", "Country Strong, Inc.", "FSP", "Gem Sessions"]

def test_match_normalizes_suffixes_and_articles():
    assert normalize_name("Beyond Our Best, LLC") == normalize_name("beyond our best")
    assert match_accounts("Athlete Standard", ACCTS)["matched"][0]["account"] == "The Athlete Standard"

def test_match_splits_multi_account_text():
    r = match_accounts("FSP, Gem Sessions", ACCTS)
    assert [m["account"] for m in r["matched"]] == ["FSP", "Gem Sessions"]

def test_match_reports_unmatched():
    r = match_accounts("Totally Unknown Gym", ACCTS)
    assert r["matched"] == [] and r["unmatched"] == ["Totally Unknown Gym"]

def test_match_uncertain_band():
    r = match_accounts("Country Strng", ACCTS)
    assert r["matched"] or r["uncertain"]
    assert r["unmatched"] == []


PREFIX_ACCTS = ["Full Throttle Fitness & Performance, LLC", "SPR Conditioning", "ROI Physical Therapy & Sports Performance",
                "Sthenos Athletics (Ryan Boylen)", "New Era Coaching Ltd", "New Era Coaching Ltd - Dunboyne",
                "CARD Sports Performance"]


def test_match_short_form_leading_words():
    for raw, acct in [("Full Throttle", PREFIX_ACCTS[0]), ("SPR", PREFIX_ACCTS[1]),
                      ("ROI", PREFIX_ACCTS[2]), ("Full-Throttle", PREFIX_ACCTS[0])]:
        assert [m["account"] for m in match_accounts(raw, PREFIX_ACCTS)["matched"]] == [acct], raw


def test_match_all_words_contained():
    assert match_accounts("Ryan Boylen", PREFIX_ACCTS)["matched"][0]["account"] == "Sthenos Athletics (Ryan Boylen)"


def test_match_ambiguous_short_form_is_uncertain():
    r = match_accounts("New Era", PREFIX_ACCTS)
    assert r["matched"] == [] and r["uncertain"][0]["input"] == "New Era"


def test_match_unrelated_short_name_not_matched():
    r = match_accounts("Pivotal Sports Performance", PREFIX_ACCTS)
    assert r["matched"] == []
