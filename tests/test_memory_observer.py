import json
import os
import tempfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from processors.memory_observer import observe, _load_known_decision_dates
from collectors.gmail import EmailThread
from collectors.pipeline import PipelineLead
from processors.brief import BriefContent
from processors.issues import Issue
from lib.storage import LocalStorage


def make_email_thread(id="t1", subject="Test", days_open=3) -> EmailThread:
    return EmailThread(
        id=id, subject=subject, last_sender="sender@example.com",
        snippet="test snippet", last_message_date=None, needs_reply=True,
    )


def make_stale_lead(name="Apex", days=20) -> PipelineLead:
    return PipelineLead(
        name=name, contact="Jane", email="jane@apex.com",
        status="In-Trial", priority="high", last_contacted=None, days_since_contact=days,
        estimated_value=10000, source="notion", stale=True,
    )


def make_issue(id="i1", title="Payment fire", channel="support") -> Issue:
    return Issue(
        id=id, title=title, source="slack", source_ref="slack:C123456", channel=channel,
        created_date="2026-04-16", last_seen_date="2026-04-19",
        status="open", actions_needed=[], outside_parties=[], resolved_date=None,
    )


def make_brief(priorities=None) -> BriefContent:
    return BriefContent(
        executive_summary="Busy day",
        top_3_priorities=priorities or ["Follow up on Apex contract"],
    )


def _read_obs(tmp_path):
    """Read observations written by LocalStorage (at memory/observations.jsonl)."""
    obs_path = tmp_path / "memory" / "observations.jsonl"
    if not obs_path.exists():
        return []
    return [json.loads(l) for l in obs_path.read_text().splitlines() if l.strip()]


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(base_dir=str(tmp_path))


@pytest.fixture
def decisions_file(tmp_path):
    f = tmp_path / "decisions.md"
    f.write_text("# Decisions\n")
    return str(f)


def test_observe_appends_email_loop(storage, decisions_file, tmp_path):
    still_open = {"email": ["t1"], "notion": []}
    threads = [make_email_thread(id="t1", subject="Contract renewal")]
    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=threads,
        still_open_ids=still_open,
        pipeline_leads=[],
        brief=make_brief(),
        issues=[],
    )
    lines = _read_obs(tmp_path)
    email_obs = [o for o in lines if o["type"] == "email_loop"]
    assert len(email_obs) == 1
    assert email_obs[0]["entity"] == "thread:Contract renewal"


def test_observe_appends_pipeline_stale(storage, decisions_file, tmp_path):
    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[make_stale_lead(name="Apex", days=20)],
        brief=make_brief(),
        issues=[],
    )
    lines = _read_obs(tmp_path)
    stale_obs = [o for o in lines if o["type"] == "pipeline_stale"]
    assert len(stale_obs) == 1
    assert "apex" in stale_obs[0]["entity"].lower()


def test_observe_appends_top_priority(storage, decisions_file, tmp_path):
    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(priorities=["Follow up on Apex contract renewal"]),
        issues=[],
    )
    lines = _read_obs(tmp_path)
    priority_obs = [o for o in lines if o["type"] == "top_priority"]
    assert len(priority_obs) == 1


def test_observe_appends_issue_pattern(storage, decisions_file, tmp_path):
    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(),
        issues=[make_issue(title="Payment processing down")],
    )
    lines = _read_obs(tmp_path)
    issue_obs = [o for o in lines if o["type"] == "issue_pattern"]
    assert len(issue_obs) == 1
    assert "Payment processing down" in issue_obs[0]["content"]


def test_observe_emits_new_decisions(storage, tmp_path):
    decisions_file = str(tmp_path / "decisions.md")
    with open(decisions_file, "w") as f:
        f.write("# Decisions\n2026-04-19: Pausing Apex outreach\n")
    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(),
        issues=[],
    )
    lines = _read_obs(tmp_path)
    decision_obs = [o for o in lines if o["type"] == "decision"]
    assert len(decision_obs) == 1
    assert "Pausing Apex outreach" in decision_obs[0]["content"]


def test_observe_does_not_emit_duplicate_decisions(storage, tmp_path):
    decisions_file = str(tmp_path / "decisions.md")
    with open(decisions_file, "w") as f:
        f.write("# Decisions\n2026-04-19: Pausing Apex outreach\n")
    # Prepopulate obs with the same decision already recorded
    storage.append_line("memory/observations.jsonl", json.dumps({
        "date": "2026-04-19", "type": "decision", "entity": "manual",
        "content": "Pausing Apex outreach", "source": "manual"
    }))
    observe(
        storage=storage,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(),
        issues=[],
    )
    lines = _read_obs(tmp_path)
    decision_obs = [o for o in lines if o["type"] == "decision"]
    assert len(decision_obs) == 1  # not duplicated
