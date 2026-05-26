# tests/test_resolve_notifications.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.resolve_observations import _build_notification


def test_notification_short_form_single():
    classified = [{"index": 1, "entity": "foo", "type": "no_match",
                   "candidate_id": None, "candidate_name": None, "confidence": None}]
    msg = _build_notification(classified)
    assert msg == (
        "1 unresolved entity from tonight's run.\n\n"
        "Open your people tracker HTML artifact to reconcile new items."
    )


def test_notification_short_form_plural():
    classified = [
        {"index": 1, "entity": "foo", "type": "no_match",
         "candidate_id": None, "candidate_name": None, "confidence": None},
        {"index": 2, "entity": "bar", "type": "fuzzy_match",
         "candidate_id": "bar-id", "candidate_name": "Bar Person", "confidence": 0.87},
    ]
    msg = _build_notification(classified)
    assert msg == (
        "2 unresolved entities from tonight's run.\n\n"
        "Open your people tracker HTML artifact to reconcile new items."
    )


def test_notification_contains_no_numbered_list():
    classified = [
        {"index": 1, "entity": "someone", "type": "fuzzy_match",
         "candidate_id": "p1", "candidate_name": "Someone", "confidence": 0.90},
    ]
    msg = _build_notification(classified)
    assert "1." not in msg
    assert "confirm" not in msg.lower()
    assert "Reply" not in msg
