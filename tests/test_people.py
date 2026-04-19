import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.slack import SlackDM
from processors.people import build_email_index, read_auto_section, write_auto_section, MARKER, enrich_people, _extract_email


@pytest.fixture
def people_dir(tmp_path):
    (tmp_path / "luke-martin.md").write_text(
        "# Luke Martin\n\n**Email:** lmartin@teambuildr.com\n**Role:** Revenue team\n\n## Notes\n- test\n"
    )
    (tmp_path / "nicole-foley.md").write_text(
        "# Nicole Foley\n\n**Email:** nicole@teambuildr.com\n**Role:** Admin\n"
    )
    (tmp_path / "no-email.md").write_text(
        "# Someone\n\n**Role:** Unknown\n"
    )
    return str(tmp_path)


def test_build_email_index_finds_all_emails(people_dir):
    index = build_email_index(people_dir)
    assert "lmartin@teambuildr.com" in index
    assert "nicole@teambuildr.com" in index


def test_build_email_index_skips_files_without_email(people_dir):
    index = build_email_index(people_dir)
    assert len(index) == 2


def test_build_email_index_lowercases_emails(people_dir, tmp_path):
    (tmp_path / "test.md").write_text("# Test\n\n**Email:** TEST@EXAMPLE.COM\n")
    index = build_email_index(str(tmp_path))
    assert "test@example.com" in index


def test_write_auto_section_creates_marker_if_absent(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    write_auto_section(filepath, significant=[], routine=["2026-04-17 | calendar | \"Rev Team Sync\""], open_threads=[])
    content = Path(filepath).read_text()
    assert MARKER in content
    assert "Rev Team Sync" in content


def test_write_auto_section_preserves_human_content(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    original_content = Path(filepath).read_text()
    write_auto_section(filepath, significant=[], routine=[], open_threads=[])
    new_content = Path(filepath).read_text()
    # Human section above MARKER must be byte-for-byte identical
    original_human = original_content.split(MARKER)[0].rstrip()
    new_human = new_content.split(MARKER)[0].rstrip()
    assert original_human == new_human


def test_write_auto_section_replaces_previous_auto_section(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    write_auto_section(filepath, significant=[], routine=["2026-04-15 | email | \"Old thread\""], open_threads=[])
    write_auto_section(filepath, significant=[], routine=["2026-04-17 | calendar | \"New event\""], open_threads=[])
    content = Path(filepath).read_text()
    assert "New event" in content
    assert "Old thread" not in content
    assert content.count(MARKER) == 1


def test_write_auto_section_significant_touchpoints_persist(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    sig = ["2026-04-10 | email | \"Proposal\" | committed to sending by Friday"]
    write_auto_section(filepath, significant=sig, routine=[], open_threads=[])
    content = Path(filepath).read_text()
    assert "Proposal" in content
    assert "committed to sending by Friday" in content


def test_read_auto_section_returns_empty_dict_if_no_marker(people_dir):
    filepath = str(Path(people_dir) / "nicole-foley.md")
    result = read_auto_section(filepath)
    assert result == {"significant": [], "routine": [], "open_threads": []}


def test_read_auto_section_parses_written_data(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    sig = ["2026-04-10 | email | \"Proposal\" | committed"]
    routine = ["2026-04-17 | calendar | \"Rev Team Sync\""]
    open_threads = ["\"Proposal\" — needs reply"]
    write_auto_section(filepath, significant=sig, routine=routine, open_threads=open_threads)

    result = read_auto_section(filepath)
    assert len(result["significant"]) == 1
    assert "Proposal" in result["significant"][0]
    assert len(result["routine"]) == 1
    assert len(result["open_threads"]) == 1


# ---------------------------------------------------------------------------
# Enrichment tests (Task 4)
# ---------------------------------------------------------------------------

def make_event(summary: str, attendees: list[str]) -> CalendarEvent:
    return CalendarEvent(
        id="evt1",
        summary=summary,
        start=datetime(2026, 4, 18, 9, 0),
        end=datetime(2026, 4, 18, 10, 0),
        description="",
        attendees=attendees,
    )


def make_thread(subject: str, sender: str, needs_reply: bool = True) -> EmailThread:
    return EmailThread(
        id="t1", subject=subject, last_sender=sender,
        snippet="", last_message_date=None, needs_reply=needs_reply,
    )


def make_dm(user_id: str, display_name: str, email: str, messages: list[str]) -> SlackDM:
    return SlackDM(user_id=user_id, display_name=display_name, email=email,
                   messages=messages, channel_id="D001")


def test_extract_email_bare():
    assert _extract_email("luke@example.com") == "luke@example.com"


def test_extract_email_with_display_name():
    assert _extract_email("Luke Martin <lmartin@teambuildr.com>") == "lmartin@teambuildr.com"


def test_extract_email_returns_original_if_no_angle_brackets():
    assert _extract_email("notanemail") == "notanemail"


MOCK_CLAUDE_RESPONSE = """{
  "touchpoint_assessments": [],
  "new_profiles": []
}"""


def test_enrich_people_updates_routine_touchpoint(people_dir):
    event = make_event("Rev Team Sync", ["lmartin@teambuildr.com"])
    with patch("processors.people.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=MOCK_CLAUDE_RESPONSE)]
        )
        enrich_people(
            calendar_events=[event],
            email_threads=[],
            slack_dms=[],
            people_dir=people_dir,
            api_key="test-key",
            model="claude-sonnet-4-6",
        )
    content = Path(people_dir, "luke-martin.md").read_text()
    assert "Rev Team Sync" in content
    assert MARKER in content


def test_enrich_people_records_open_thread(people_dir):
    thread = make_thread("CSM coverage Q2", "Luke Martin <lmartin@teambuildr.com>", needs_reply=True)
    with patch("processors.people.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=MOCK_CLAUDE_RESPONSE)]
        )
        enrich_people(
            calendar_events=[],
            email_threads=[thread],
            slack_dms=[],
            people_dir=people_dir,
            api_key="test-key",
            model="claude-sonnet-4-6",
        )
    content = Path(people_dir, "luke-martin.md").read_text()
    assert "CSM coverage Q2" in content
    assert "needs reply" in content


def test_enrich_people_returns_context_string_for_matched_contacts(people_dir):
    event = make_event("Rev Team Sync", ["lmartin@teambuildr.com"])
    with patch("processors.people.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=MOCK_CLAUDE_RESPONSE)]
        )
        context = enrich_people(
            calendar_events=[event],
            email_threads=[],
            slack_dms=[],
            people_dir=people_dir,
            api_key="test-key",
            model="claude-sonnet-4-6",
        )
    assert "Luke Martin" in context
    assert "lmartin@teambuildr.com" in context


def test_enrich_people_unmatched_email_skipped(people_dir):
    thread = make_thread("Unknown subject", "nobody@external.com", needs_reply=True)
    with patch("processors.people.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=MOCK_CLAUDE_RESPONSE)]
        )
        context = enrich_people(
            calendar_events=[],
            email_threads=[thread],
            slack_dms=[],
            people_dir=people_dir,
            api_key="test-key",
            model="claude-sonnet-4-6",
        )
    assert "nobody@external.com" not in context


MOCK_CLAUDE_NEW_PROFILE = """{
  "touchpoint_assessments": [],
  "new_profiles": [
    {
      "worth_tracking": true,
      "suggested_filename": "james-new.md",
      "display_name": "James New",
      "email": "james@teambuildr.com",
      "reason": "promised to send onboarding doc"
    }
  ]
}"""


def test_enrich_people_creates_new_profile_from_slack_dm(people_dir):
    dm = make_dm("U999", "James New", "james@teambuildr.com", ["Can you send the onboarding doc?"])
    with patch("processors.people.anthropic") as mock_anthropic:
        mock_anthropic.Anthropic.return_value.messages.create.return_value = MagicMock(
            content=[MagicMock(text=MOCK_CLAUDE_NEW_PROFILE)]
        )
        enrich_people(
            calendar_events=[],
            email_threads=[],
            slack_dms=[dm],
            people_dir=people_dir,
            api_key="test-key",
            model="claude-sonnet-4-6",
        )
    new_file = Path(people_dir) / "james-new.md"
    assert new_file.exists()
    content = new_file.read_text()
    assert "James New" in content
    assert "james@teambuildr.com" in content
