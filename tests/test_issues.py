import json
from datetime import date, timedelta
import pytest
from processors.issues import (
    Issue, IssueLog, load_issues, save_issues,
    add_or_update_issue, auto_resolve_issues, get_open_issues,
)


def test_add_new_issue(tmp_path):
    issues_file = str(tmp_path / "issues.json")
    with open(issues_file, "w") as f:
        json.dump({"issues": []}, f)

    add_or_update_issue(
        issues_file=issues_file,
        source="slack",
        source_ref="C001:1713450000.123",
        channel="support",
        title="Login failures reported",
    )
    log = load_issues(issues_file)
    assert len(log.issues) == 1
    assert log.issues[0].status == "open"
    assert log.issues[0].channel == "support"


def test_duplicate_source_ref_not_added(tmp_path):
    issues_file = str(tmp_path / "issues.json")
    with open(issues_file, "w") as f:
        json.dump({"issues": []}, f)

    add_or_update_issue(issues_file, "slack", "C001:123", "support", "Issue A")
    add_or_update_issue(issues_file, "slack", "C001:123", "support", "Issue A again")
    log = load_issues(issues_file)
    assert len(log.issues) == 1


def test_auto_resolve_old_issues(tmp_path):
    issues_file = str(tmp_path / "issues.json")
    old_date = (date.today() - timedelta(days=4)).isoformat()
    data = {"issues": [{
        "id": "abc", "title": "Old issue", "source": "slack",
        "source_ref": "C001:123", "channel": "support",
        "created_date": old_date, "last_seen_date": old_date,
        "status": "open", "actions_needed": [], "outside_parties": [],
        "resolved_date": None,
    }]}
    with open(issues_file, "w") as f:
        json.dump(data, f)

    auto_resolve_issues(issues_file, resolve_after_days=3)
    log = load_issues(issues_file)
    assert log.issues[0].status == "resolved"


def test_get_open_issues_excludes_resolved(tmp_path):
    issues_file = str(tmp_path / "issues.json")
    today = date.today().isoformat()
    data = {"issues": [
        {"id": "a", "title": "Open", "source": "slack", "source_ref": "r1",
         "channel": "support", "created_date": today, "last_seen_date": today,
         "status": "open", "actions_needed": [], "outside_parties": [], "resolved_date": None},
        {"id": "b", "title": "Done", "source": "slack", "source_ref": "r2",
         "channel": "support", "created_date": today, "last_seen_date": today,
         "status": "resolved", "actions_needed": [], "outside_parties": [], "resolved_date": today},
    ]}
    with open(issues_file, "w") as f:
        json.dump(data, f)

    open_issues = get_open_issues(issues_file)
    assert len(open_issues) == 1
    assert open_issues[0].title == "Open"
