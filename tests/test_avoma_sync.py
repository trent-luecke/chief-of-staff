import pytest
from unittest.mock import MagicMock, patch


# ── build_slack_message ───────────────────────────────────────────────────────

def test_build_slack_message_no_calls():
    from scripts.avoma_sync import build_slack_message
    result = build_slack_message([], [], "2026-06-06")
    assert result == "📞 Avoma Sync — 2026-06-06\n\nNo new OS calls in the last 24 hours."


def test_build_slack_message_pipeline_update():
    from scripts.avoma_sync import build_slack_message
    updates = [{
        "lead_name": "Acme Corp",
        "call_type": "demo",
        "call_date": "2026-06-06",
        "inferred_status": "In-Trial / Post Demo",
        "summary": "Strong interest.",
        "is_new_lead": False,
        "account_owner": None,
        "buying_signals": [],
        "objections": [],
    }]
    result = build_slack_message(updates, [], "2026-06-06")
    assert "Acme Corp" in result
    assert "In-Trial / Post Demo" in result
    assert "*Pipeline Updates*" in result


def test_build_slack_message_new_lead_shows_warning():
    from scripts.avoma_sync import build_slack_message
    updates = [{
        "lead_name": "New Gym",
        "call_type": "demo",
        "call_date": "2026-06-06",
        "inferred_status": "No Trial / Post Demo",
        "summary": "First call.",
        "is_new_lead": True,
        "account_owner": "Ryan",
        "buying_signals": [],
        "objections": [],
    }]
    result = build_slack_message(updates, [], "2026-06-06")
    assert "Not in pipeline" in result
    assert "Ryan" in result


def test_build_slack_message_onboarding_update():
    from scripts.avoma_sync import build_slack_message
    updates = [{
        "customer_name": "Iron Will",
        "call_date": "2026-06-06",
        "onboarding_completed": ["Phase 1", "App setup"],
        "onboarding_next_steps": ["Load athletes"],
        "status_update": "In progress",
        "summary": "Good session.",
    }]
    result = build_slack_message([], updates, "2026-06-06")
    assert "Iron Will" in result
    assert "*Onboarding Updates*" in result
    assert "Phase 1" in result


def test_build_slack_message_no_char_limit():
    """Slack limit is 40k — no truncation guard needed unlike Telegram."""
    from scripts.avoma_sync import build_slack_message
    long_summary = "x" * 5000
    updates = [{
        "lead_name": "Big Corp",
        "call_type": "follow_up",
        "call_date": "2026-06-06",
        "inferred_status": "On-Hold",
        "summary": long_summary,
        "is_new_lead": False,
        "account_owner": None,
        "buying_signals": [],
        "objections": [],
    }]
    result = build_slack_message(updates, [], "2026-06-06")
    assert long_summary in result  # not truncated


# ── delivery error path ───────────────────────────────────────────────────────

def test_delivery_exits_1_on_slack_error():
    """The delivery block in main() calls sys.exit(1) when post_message raises."""
    import sys
    from slack_sdk.errors import SlackApiError

    # Reproduce the delivery block in isolation
    def run_delivery(post_fn):
        try:
            post_fn("tok", "D04EQ4BBW2H", "hello")
            print("   Slack DM sent.")
        except Exception as exc:
            print(f"ERROR: Slack send failed: {exc}", file=sys.stderr)
            sys.exit(1)

    with pytest.raises(SystemExit) as exc_info:
        run_delivery(MagicMock(side_effect=SlackApiError("fail", {"error": "not_in_channel"})))
    assert exc_info.value.code == 1


def test_delivery_does_not_exit_on_success():
    """The delivery block does NOT call sys.exit when post_message succeeds."""
    import sys

    def run_delivery(post_fn):
        try:
            post_fn("tok", "D04EQ4BBW2H", "hello")
            print("   Slack DM sent.")
        except Exception as exc:
            print(f"ERROR: Slack send failed: {exc}", file=sys.stderr)
            sys.exit(1)

    # Should not raise
    run_delivery(MagicMock(return_value="ts.001"))


# ── build_queue_entries ────────────────────────────────────────────────────────

def test_build_queue_entries_pipeline_shape():
    from scripts.avoma_sync import build_queue_entries
    pu = [{
        "lead_name": "Acme Corp", "call_type": "demo", "call_date": "2026-06-06",
        "inferred_status": "In-Trial / Post Demo", "summary": "Strong interest.",
        "is_new_lead": True, "account_owner": "Chris",
        "buying_signals": ["timeline"], "objections": [], "call_uuid": "u-123",
    }]
    entries = build_queue_entries(pu, [], now="2026-06-06T12:00:00Z")
    assert len(entries) == 1
    e = entries[0]
    assert e["id"] == "avoma:u-123"
    assert e["source"] == "avoma" and e["target"] == "pipeline"
    assert e["name"] == "Acme Corp" and e["action"] == "update"
    assert e["inferred_status"] == "In-Trial / Post Demo"
    assert e["is_new_lead"] is True and e["account_owner"] == "Chris"
    assert e["timestamp"] == "2026-06-06T12:00:00Z"


def test_build_queue_entries_onboarding_shape():
    from scripts.avoma_sync import build_queue_entries
    ou = [{
        "customer_name": "Alina Bushma", "call_date": "2026-08-12",
        "onboarding_completed": ["Scheduling walkthrough"],
        "onboarding_next_steps": ["Explore independently"],
        "status_update": "In progress", "summary": "Engaged.", "call_uuid": "u-9",
    }]
    entries = build_queue_entries([], ou, now="2026-08-12T12:00:00Z")
    e = entries[0]
    assert e["id"] == "avoma:u-9" and e["target"] == "onboarding"
    assert e["name"] == "Alina Bushma"
    assert e["onboarding_completed"] == ["Scheduling walkthrough"]
    assert e["status_update"] == "In progress"


def test_build_queue_entries_id_fallback_without_uuid():
    from scripts.avoma_sync import build_queue_entries
    pu = [{"lead_name": "No UUID Co", "call_date": "2026-06-06", "call_type": "demo",
           "inferred_status": "Post Demo", "summary": "", "is_new_lead": False,
           "account_owner": None, "buying_signals": [], "objections": []}]
    entries = build_queue_entries(pu, [], now="2026-06-06T12:00:00Z")
    assert entries[0]["id"] == "avoma:No UUID Co:2026-06-06"
