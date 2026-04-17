from datetime import datetime
from processors.loops import build_loop_summary, LoopSummary
from collectors.gmail import EmailThread
from collectors.notion_inbox import InboxItem


def make_thread(id: str, subject: str, sender: str) -> EmailThread:
    return EmailThread(
        id=id,
        subject=subject,
        last_sender=sender,
        snippet="",
        last_message_date=datetime.now(),
        needs_reply=True,
    )


def make_notion_item(id: str, name: str) -> InboxItem:
    return InboxItem(
        id=id,
        name=name,
        item_type="Task",
        urgency="Medium",
        category="Sales",
        source="Shortcut",
        created_time="2026-04-16T10:00:00Z",
    )


def test_build_loop_summary_new_loops():
    threads = [make_thread("t1", "Contract renewal", "John <john@example.com>")]
    notion_items = [make_notion_item("n1", "Follow up with Sarah")]
    resolved = {"email": [], "notion": []}
    still_open = {"email": [], "notion": []}

    summary = build_loop_summary(threads, notion_items, resolved, still_open)

    assert len(summary.new_email_loops) == 1
    assert summary.new_email_loops[0]["thread_id"] == "t1"
    assert summary.new_email_loops[0]["subject"] == "Contract renewal"
    assert len(summary.new_notion_loops) == 1
    assert summary.new_notion_loops[0]["item_id"] == "n1"


def test_build_loop_summary_resolved_loops():
    resolved = {"email": ["t_old"], "notion": ["n_old"]}
    still_open = {"email": [], "notion": []}

    summary = build_loop_summary([], [], resolved, still_open)

    assert "t_old" in summary.resolved_email_ids
    assert "n_old" in summary.resolved_notion_ids


def test_build_loop_summary_still_open_loops():
    threads = [make_thread("t_persist", "Old subject", "Bob <bob@x.com>")]
    resolved = {"email": [], "notion": []}
    still_open = {"email": ["t_persist"], "notion": []}

    summary = build_loop_summary(threads, [], resolved, still_open)

    assert "t_persist" in summary.still_open_email_ids


def test_build_loop_summary_excludes_still_open_from_new():
    """Threads that are 'still_open' (from yesterday) should NOT appear in new_email_loops."""
    threads = [
        make_thread("t_new", "New email", "Alice <alice@x.com>"),
        make_thread("t_persist", "Old email", "Bob <bob@x.com>"),
    ]
    resolved = {"email": [], "notion": []}
    still_open = {"email": ["t_persist"], "notion": []}

    summary = build_loop_summary(threads, [], resolved, still_open)

    new_ids = [l["thread_id"] for l in summary.new_email_loops]
    assert "t_new" in new_ids
    assert "t_persist" not in new_ids
    assert "t_persist" in summary.still_open_email_ids


def test_build_loop_summary_empty_state():
    summary = build_loop_summary([], [], {"email": [], "notion": []}, {"email": [], "notion": []})
    assert summary.new_email_loops == []
    assert summary.new_notion_loops == []
    assert summary.resolved_email_ids == []
    assert summary.resolved_notion_ids == []
    assert summary.still_open_email_ids == []
    assert summary.still_open_notion_ids == []


def test_build_loop_summary_still_open_notion():
    notion_items = [make_notion_item("n_persist", "Pending follow-up")]
    resolved = {"email": [], "notion": []}
    still_open = {"email": [], "notion": ["n_persist"]}

    summary = build_loop_summary([], notion_items, resolved, still_open)

    assert "n_persist" in summary.still_open_notion_ids
    new_item_ids = [l["item_id"] for l in summary.new_notion_loops]
    assert "n_persist" not in new_item_ids
