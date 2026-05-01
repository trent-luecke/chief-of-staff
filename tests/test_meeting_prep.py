import pytest
from datetime import datetime
from collectors.calendar import CalendarEvent
from processors.meeting_prep import classify_meeting

BASE_CONFIG = {
    "meeting_prep": {
        "dept_heads_patterns": ["department heads", "dept heads"],
        "recurring_internal_patterns": ["marketing sync", "os weekly", "luke / trent", "luke/trent"],
    }
}

def _event(summary, attendees=None):
    now = datetime.now()
    return CalendarEvent(
        id="test-id",
        summary=summary,
        start=now,
        end=now,
        attendees=attendees or [],
    )


def test_classify_dept_heads():
    assert classify_meeting(_event("Department Heads Weekly"), BASE_CONFIG) == "dept_heads"

def test_classify_dept_heads_case_insensitive():
    assert classify_meeting(_event("DEPARTMENT HEADS"), BASE_CONFIG) == "dept_heads"

def test_classify_recurring_internal_marketing():
    assert classify_meeting(_event("OS Weekly Marketing Sync"), BASE_CONFIG) == "recurring_internal"

def test_classify_recurring_internal_luke():
    assert classify_meeting(_event("Luke / Trent"), BASE_CONFIG) == "recurring_internal"

def test_classify_external_by_keyword():
    assert classify_meeting(_event("Mike: OS Demo"), BASE_CONFIG) == "external"

def test_classify_external_by_attendee():
    assert classify_meeting(
        _event("Intro call", attendees=["coach@apexholland.co"]),
        BASE_CONFIG
    ) == "external"

def test_classify_skips_personal():
    assert classify_meeting(_event("Haircut"), BASE_CONFIG) is None

def test_classify_skips_generic_internal():
    assert classify_meeting(
        _event("TeamBuildr Standup", attendees=["team@teambuildr.com"]),
        BASE_CONFIG
    ) is None

def test_dept_heads_takes_priority_over_external():
    assert classify_meeting(_event("Department Heads Demo Review"), BASE_CONFIG) == "dept_heads"
