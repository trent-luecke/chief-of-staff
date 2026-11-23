# tests/test_churn.py
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.churn import churn_actions, has_returned, name_key, strip_account_id  # noqa: E402
from scripts.checkins_sheet import cancellation_records, read_cancellations  # noqa: E402

TODAY = date(2026, 11, 23)


def _c(name, on="2026-10-01", returned=""):
    return {"name": name, "cancelled_on": on, "returned": returned, "tab": "MONTHLY Cancellations"}


def test_strip_account_id_variants():
    assert strip_account_id("The Example Lab (ID: 902)") == "The Example Lab"
    assert strip_account_id("Sample Barbell (692)") == "Sample Barbell"
    assert strip_account_id("Peak Out Strength & Conditioning (ID: 1416) ") == "Peak Out Strength & Conditioning"
    assert strip_account_id("Jade Studio #77") == "Jade Studio"
    assert strip_account_id("42 Academy") == "42 Academy"  # leading number is part of the name


def test_name_key_is_case_and_space_insensitive_only():
    assert name_key("  Orca   Athletics ") == name_key("orca athletics")
    assert name_key("Orca Athletics") != name_key("Orca Athletics - Eastside")


def test_has_returned():
    assert not has_returned("") and not has_returned("No") and not has_returned(None)
    assert has_returned("Yes") and has_returned("12/1/2026")


def test_exact_match_active_account_is_churned():
    out = churn_actions([_c("Orca Athletics"), _c("Demo Gym", "2026-10-26")],
                        [{"name": "Orca Athletics", "status": "Active"},
                         {"name": "Demo Gym", "status": "Churned"},
                         {"name": "Orca Athletics - Eastside", "status": "Active"}], TODAY)
    assert [x["account"] for x in out["to_churn"]] == ["Orca Athletics"]
    assert [x["account"] for x in out["already_churned"]] == ["Demo Gym"]


def test_sibling_location_is_not_churned_by_parent_name():
    out = churn_actions([_c("Orca Athletics")],
                        [{"name": "Orca Athletics - Eastside", "status": "Active"}], TODAY)
    assert out["to_churn"] == []


def test_fuzzy_hit_is_reported_never_churned():
    # The real false positive that motivated exact-only matching.
    out = churn_actions([_c("Peak Out Strength & Conditioning (ID: 1416)", "2026-10-15")],
                        [{"name": "FORGED. Strength and Conditioning", "status": "Active"}], TODAY)
    assert out["to_churn"] == []
    assert out["near_matches"][0]["candidates"] == ["FORGED. Strength and Conditioning"]


def test_old_near_matches_are_not_repeated():
    out = churn_actions([_c("Peak Out Strength & Conditioning", "2026-07-01")],
                        [{"name": "FORGED. Strength and Conditioning", "status": "Active"}], TODAY)
    assert out["near_matches"] == []


def test_returned_customer_is_never_churned_and_flags_if_already_churned():
    out = churn_actions([_c("Jade Studio", returned="Yes"), _c("Demo Gym", returned="Yes")],
                        [{"name": "Jade Studio", "status": "Active"}, {"name": "Demo Gym", "status": "Churned"}], TODAY)
    assert out["to_churn"] == [] and out["already_churned"] == []
    assert [x["account"] for x in out["returned_but_churned"]] == ["Demo Gym"]


def test_latest_row_wins_when_account_appears_twice():
    out = churn_actions([_c("Jade Studio", "2025-01-01"), _c("Jade Studio", "2026-10-01", returned="Yes")],
                        [{"name": "Jade Studio", "status": "Active"}], TODAY)
    assert out["to_churn"] == []


def test_cancellation_records_reads_by_header_and_skips_blank_names():
    rows = [["Jump to Bottom", "Date", "Account Name and #", "Reason", "Customer Returned"],
            ["", "10/1/2026", "Orca Athletics", "Using another software"],
            ["", "", "", ""],
            ["", "11/13/2026", " Deck Sports Lab ", "x", "No"]]
    assert cancellation_records(rows, "MONTHLY Cancellations") == [
        {"name": "Orca Athletics", "cancelled_on": "2026-10-01", "returned": "", "tab": "MONTHLY Cancellations"},
        {"name": "Deck Sports Lab", "cancelled_on": "2026-11-13", "returned": "No", "tab": "MONTHLY Cancellations"},
    ]


def test_cancellation_records_handles_tab_without_date_column():
    rows = [["Jump to Bottom", "Account", "Reason"], ["", "Annual Gym", "Budget"]]
    assert cancellation_records(rows, "ANNUAL Non-Renewals") == [
        {"name": "Annual Gym", "cancelled_on": "", "returned": "", "tab": "ANNUAL Non-Renewals"}]


def test_read_cancellations_reads_both_tabs():
    from tests.test_checkins_sheet import _FakeSheets
    svc = _FakeSheets({
        "MONTHLY Cancellations": [["x", "Date", "Account Name and #"], ["", "10/1/2026", "Jade Studio"]],
        "ANNUAL Non-Renewals": [["x", "Account"], ["", "Annual Gym"]],
    })
    assert [r["name"] for r in read_cancellations(svc)] == ["Jade Studio", "Annual Gym"]


def test_cli_churn_command():
    payload = {"today": "2026-11-23", "cancellations": [_c("Jade Studio")],
               "accounts": [{"name": "Jade Studio", "status": "Active"}]}
    p = subprocess.run([sys.executable, str(ROOT / "scripts/checkins.py"), "churn"],
                       input=json.dumps(payload), capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(p.stdout)["to_churn"][0]["account"] == "Jade Studio"
