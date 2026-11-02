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
