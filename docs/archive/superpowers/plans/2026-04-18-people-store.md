# People Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent `data/people/` store that enriches contact files from calendar, Gmail, and Slack DMs on each brief run, and injects people context as ambient background into the Claude brief prompt.

**Architecture:** Contact files live in `data/people/*.md`, each split by a hard marker into a human-written section (never touched by code) and a machine-written `## Activity` section (fully replaced each run). A new `processors/people.py` module runs after all collectors finish, builds an email→file index, matches today's events/threads/DMs to contact files, uses one Claude call per run to assess touchpoint significance and decide on auto-creating new Slack DM profiles, then writes updated activity sections. The brief prompt gains a `## People Context` block injected before the Claude call.

**Tech Stack:** Python 3.14, `pathlib`, `re`, `json`, `anthropic` SDK (already in project), `slack_sdk` (already in project), `pytest` for tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create dir | `data/people/` | Persistent store for all contact files |
| Move | `{luke-martin,luke-green,nicole-foley,james-peters,hewitt-tomlin,clayton,rachel,heather}.md` → `data/people/` | Contact files (human-written sections) |
| Delete | `__pycache__/people copy/` | Duplicate backup, no longer needed |
| Modify | `collectors/slack.py` | Add `SlackDM` dataclass + `fetch_dm_messages()` |
| Create | `processors/people.py` | Email index, marker-write, enrichment orchestrator |
| Modify | `processors/brief.py` | Accept + inject `people_context: str` param |
| Modify | `main.py` | Call `enrich_people()` after collectors, pass context to brief |
| Modify | `config.json` | Add `"people_dir": "data/people"` |
| Create | `tests/test_people.py` | All people-store unit tests |
| Modify | `tests/test_slack.py` | Add DM fetch tests |

---

## Task 1: Migrate contact files into `data/people/`

**Files:**
- Create: `data/people/` (directory)
- Move: 8 contact `.md` files from project root → `data/people/`
- Delete: `__pycache__/people copy/`

- [ ] **Step 1: Create directory and move files**

```bash
cd /path/to/chief-of-staff
mkdir -p data/people
mv luke-martin.md luke-green.md nicole-foley.md james-peters.md \
   hewitt-tomlin.md clayton.md rachel.md heather.md data/people/
rm -rf "__pycache__/people copy"
```

- [ ] **Step 2: Verify**

```bash
ls data/people/
```
Expected: 8 `.md` files, nothing left in `__pycache__/people copy`.

- [ ] **Step 3: Commit**

```bash
git add data/people/ __pycache__
git add -u  # stage deletions from root
git commit -m "chore: migrate contact files to data/people/"
```

---

## Task 2: Add Slack DM fetching to `collectors/slack.py`

**Files:**
- Modify: `collectors/slack.py`
- Modify: `tests/test_slack.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_slack.py`:

```python
from collectors.slack import fetch_dm_messages, SlackDM

MOCK_DM_CHANNELS = {
    "channels": [
        {"id": "D001", "user": "U123", "is_open": True},
        {"id": "D002", "user": "U456", "is_open": False},  # closed DM — should be skipped
    ]
}

MOCK_USER_INFO = {
    "user": {
        "profile": {
            "real_name": "Luke Martin",
            "display_name": "lmartin",
            "email": "lmartin@teambuildr.com",
        }
    }
}

MOCK_DM_HISTORY = {
    "messages": [
        {"type": "message", "text": "Can you send me the CSM list?", "user": "U123",
         "ts": "1713450000.0", "thread_ts": "1713450000.0", "reply_count": 0},
    ]
}


def test_fetch_dm_messages_returns_dm_for_open_channel(mock_client):
    mock_client.return_value.conversations_list.return_value = MOCK_DM_CHANNELS
    mock_client.return_value.conversations_history.return_value = MOCK_DM_HISTORY
    mock_client.return_value.users_info.return_value = MOCK_USER_INFO

    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)

    assert len(dms) == 1
    assert dms[0].user_id == "U123"
    assert dms[0].display_name == "Luke Martin"
    assert dms[0].email == "lmartin@teambuildr.com"
    assert dms[0].messages == ["Can you send me the CSM list?"]


def test_fetch_dm_messages_skips_closed_channels(mock_client):
    mock_client.return_value.conversations_list.return_value = MOCK_DM_CHANNELS
    mock_client.return_value.conversations_history.return_value = {"messages": []}
    mock_client.return_value.users_info.return_value = MOCK_USER_INFO

    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)
    assert all(dm.channel_id != "D002" for dm in dms)


def test_fetch_dm_messages_returns_empty_on_api_error(mock_client):
    from slack_sdk.errors import SlackApiError
    mock_client.return_value.conversations_list.side_effect = SlackApiError(
        "error", {"error": "not_authed"}
    )
    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)
    assert dms == []


def test_fetch_dm_messages_handles_missing_email(mock_client):
    mock_client.return_value.conversations_list.return_value = {
        "channels": [{"id": "D001", "user": "U999", "is_open": True}]
    }
    mock_client.return_value.conversations_history.return_value = MOCK_DM_HISTORY
    mock_client.return_value.users_info.return_value = {
        "user": {"profile": {"real_name": "Unknown Person", "display_name": "unknown"}}
    }
    dms = fetch_dm_messages(token="xoxb-test", since_hours=24)
    assert len(dms) == 1
    assert dms[0].email == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_slack.py::test_fetch_dm_messages_returns_dm_for_open_channel -v
```
Expected: `FAILED — cannot import name 'fetch_dm_messages'`

- [ ] **Step 3: Add `SlackDM` dataclass and `fetch_dm_messages()` to `collectors/slack.py`**

Add after the existing `SlackMessage` dataclass:

```python
@dataclass
class SlackDM:
    user_id: str
    display_name: str
    email: str
    messages: list[str]
    channel_id: str
```

Add after `resolve_channel_ids()`:

```python
def fetch_dm_messages(token: str, since_hours: int = 24) -> list["SlackDM"]:
    client = WebClient(token=token)
    try:
        result = client.conversations_list(types="im", limit=200)
    except SlackApiError:
        return []

    dms = []
    for ch in result.get("channels", []):
        if not ch.get("is_open"):
            continue
        user_id = ch.get("user")
        if not user_id:
            continue

        messages = fetch_channel_messages(token, ch["id"], since_hours=since_hours)
        if not messages:
            continue

        try:
            user_info = client.users_info(user=user_id)
            profile = user_info["user"]["profile"]
            display_name = profile.get("real_name") or profile.get("display_name", user_id)
            email = profile.get("email", "")
        except SlackApiError:
            display_name = user_id
            email = ""

        dms.append(SlackDM(
            user_id=user_id,
            display_name=display_name,
            email=email,
            messages=[m.text for m in messages],
            channel_id=ch["id"],
        ))

    return dms
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_slack.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add collectors/slack.py tests/test_slack.py
git commit -m "feat: add Slack DM fetching (SlackDM + fetch_dm_messages)"
```

---

## Task 3: Build email index and marker-safe file writer

**Files:**
- Create: `processors/people.py`
- Create: `tests/test_people.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_people.py`:

```python
import pytest
from pathlib import Path
from processors.people import build_email_index, read_auto_section, write_auto_section, MARKER


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
    write_auto_section(filepath, significant=[], routine=[], open_threads=[])
    content = Path(filepath).read_text()
    # Human section untouched
    assert "**Email:** lmartin@teambuildr.com" in content
    assert "## Notes" in content
    assert "- test" in content


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_people.py -v
```
Expected: `FAILED — No module named 'processors.people'`

- [ ] **Step 3: Create `processors/people.py` with index builder and marker writer**

Create `processors/people.py`:

```python
import re
from pathlib import Path
from datetime import date

MARKER = "<!-- AUTO-UPDATED: do not edit below this line -->"
MAX_ROUTINE = 5


def build_email_index(people_dir: str) -> dict[str, str]:
    """Scan *.md in people_dir; return {email_lower: filepath} for files with **Email:** fields."""
    index = {}
    for path in Path(people_dir).glob("*.md"):
        content = path.read_text()
        m = re.search(r'\*\*Email:\*\*\s*(\S+@\S+)', content, re.IGNORECASE)
        if m:
            index[m.group(1).lower()] = str(path)
    return index


def read_auto_section(filepath: str) -> dict:
    """Parse the machine-written section. Returns {"significant": [...], "routine": [...], "open_threads": [...]}."""
    content = Path(filepath).read_text()
    if MARKER not in content:
        return {"significant": [], "routine": [], "open_threads": []}

    auto = content.split(MARKER, 1)[1]

    def _extract_list(header: str, text: str) -> list[str]:
        pattern = rf'\*\*{re.escape(header)}\*\*(.*?)(?=\n\*\*|\Z)'
        m = re.search(pattern, text, re.DOTALL)
        if not m:
            return []
        lines = []
        for line in m.group(1).strip().splitlines():
            line = line.strip().lstrip("- ")
            if line and line != "(none)":
                lines.append(line)
        return lines

    return {
        "significant": _extract_list("Significant touchpoints:", auto),
        "routine": _extract_list(f"Recent touchpoints (last {MAX_ROUTINE}):", auto),
        "open_threads": _extract_list("Open threads:", auto),
    }


def write_auto_section(
    filepath: str,
    significant: list[str],
    routine: list[str],
    open_threads: list[str],
) -> None:
    """Replace everything from MARKER onward. The human section above is never touched."""
    content = Path(filepath).read_text()
    human_part = content.split(MARKER, 1)[0].rstrip()
    today = date.today().isoformat()

    lines = ["", MARKER, "## Activity", f"**Last seen:** {today}", ""]

    lines.append("**Significant touchpoints:**")
    for tp in significant:
        lines.append(f"- {tp}")
    if not significant:
        lines.append("- (none)")
    lines.append("")

    lines.append(f"**Recent touchpoints (last {MAX_ROUTINE}):**")
    for tp in routine[:MAX_ROUTINE]:
        lines.append(f"- {tp}")
    if not routine:
        lines.append("- (none)")
    lines.append("")

    lines.append("**Open threads:**")
    for t in open_threads:
        lines.append(f"- {t}")
    if not open_threads:
        lines.append("- (none)")
    lines.append("")

    Path(filepath).write_text(human_part + "\n" + "\n".join(lines))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_people.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/people.py tests/test_people.py
git commit -m "feat: people store — email index and marker-safe file writer"
```

---

## Task 4: Build the enrichment orchestrator (`enrich_people`)

**Files:**
- Modify: `processors/people.py` (add `_extract_email`, `_assess_with_claude`, `_create_profile`, `enrich_people`)
- Modify: `tests/test_people.py` (add enrichment tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_people.py`:

```python
from unittest.mock import patch, MagicMock
from datetime import datetime
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.slack import SlackDM
from processors.people import enrich_people, _extract_email


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_people.py::test_enrich_people_updates_routine_touchpoint -v
```
Expected: `FAILED — cannot import name 'enrich_people'`

- [ ] **Step 3: Add `_extract_email`, `_assess_with_claude`, `_create_profile`, and `enrich_people` to `processors/people.py`**

Add these imports at the top of `processors/people.py`:

```python
import json
import anthropic
from typing import Optional
```

Add these functions after `write_auto_section`:

```python
def _extract_email(sender: str) -> str:
    """Extract bare email from 'Display Name <email>' or return input unchanged."""
    m = re.search(r'<([^>]+)>', sender)
    return m.group(1).strip() if m else sender.strip()


def _assess_with_claude(
    touchpoints_by_file: dict[str, list[dict]],
    unmatched_dms: list,
    api_key: str,
    model: str,
) -> dict:
    """One Claude call per run. Returns {"touchpoint_assessments": [...], "new_profiles": [...]}."""
    if not touchpoints_by_file and not unmatched_dms:
        return {"touchpoint_assessments": [], "new_profiles": []}

    tp_list = []
    for i, (filepath, tps) in enumerate(touchpoints_by_file.items()):
        for tp in tps:
            tp_list.append({
                "key": f"{i}:{tp['subject']}",
                "filepath": filepath,
                "date": tp["date"],
                "source": tp["source"],
                "subject": tp["subject"],
            })

    dm_list = [
        {
            "user_id": dm.user_id,
            "display_name": dm.display_name,
            "email": dm.email,
            "messages": dm.messages[:3],
        }
        for dm in unmatched_dms
    ]

    prompt = f"""Assess the following for the chief-of-staff people store.

TOUCHPOINTS (new interactions to assess for significance):
{json.dumps(tp_list, indent=2)}

For each touchpoint, decide if it is SIGNIFICANT: does it contain an open deliverable, stated commitment, key decision, or follow-up dependency? Return only touchpoints that ARE significant.

UNMATCHED SLACK DMS (people with no existing profile):
{json.dumps(dm_list, indent=2)}

For each Slack DM, decide if this person is worth tracking (recurring relationship, pending deliverable, or follow-up needed).

Respond ONLY in JSON:
{{
  "touchpoint_assessments": [
    {{"key": "<key from input>", "filepath": "<filepath>", "significant": true, "reason": "<one line>"}}
  ],
  "new_profiles": [
    {{"user_id": "<id>", "worth_tracking": true, "suggested_filename": "firstname-lastname.md",
       "display_name": "<name>", "email": "<email>", "reason": "<one line>"}}
  ]
}}

Only include items where significant/worth_tracking is true. Empty arrays are fine."""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    m = re.search(r'```(?:json)?\n?(.*?)```', raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"touchpoint_assessments": [], "new_profiles": []}


def _create_profile(profile_data: dict, people_dir: str) -> None:
    """Create a new contact file pre-populated with Slack data. Human sections left empty."""
    filename = profile_data.get("suggested_filename", f"{profile_data['user_id']}.md")
    filepath = Path(people_dir) / filename
    if filepath.exists():
        return
    display_name = profile_data.get("display_name", profile_data.get("user_id", "Unknown"))
    email = profile_data.get("email", "")
    user_id = profile_data.get("user_id", "")
    content = f"# {display_name}\n\n"
    if email:
        content += f"**Email:** {email}\n"
    if user_id:
        content += f"**Slack user ID:** {user_id}\n"
    content += "\n## Relationship\n\n## Notes\n"
    filepath.write_text(content)


def enrich_people(
    calendar_events: list,
    email_threads: list,
    slack_dms: list,
    people_dir: str,
    api_key: str,
    model: str,
) -> str:
    """Enrich contact files and return people context string for the brief prompt."""
    index = build_email_index(people_dir)
    today = date.today().isoformat()

    matched_files: set[str] = set()
    new_touchpoints: dict[str, list[dict]] = {}
    new_open_threads: dict[str, list[str]] = {}
    unmatched_dms = []

    for event in calendar_events:
        for attendee_email in event.attendees:
            filepath = index.get(attendee_email.lower())
            if filepath:
                matched_files.add(filepath)
                new_touchpoints.setdefault(filepath, []).append(
                    {"date": today, "source": "calendar", "subject": event.summary}
                )

    for thread in email_threads:
        email = _extract_email(thread.last_sender).lower()
        filepath = index.get(email)
        if filepath:
            matched_files.add(filepath)
            new_touchpoints.setdefault(filepath, []).append(
                {"date": today, "source": "email", "subject": thread.subject}
            )
            if thread.needs_reply:
                new_open_threads.setdefault(filepath, []).append(
                    f'"{thread.subject}" — needs reply'
                )

    for dm in slack_dms:
        if dm.email:
            filepath = index.get(dm.email.lower())
            if filepath:
                matched_files.add(filepath)
                preview = dm.messages[0][:60] if dm.messages else "DM"
                new_touchpoints.setdefault(filepath, []).append(
                    {"date": today, "source": "slack", "subject": preview}
                )
            else:
                unmatched_dms.append(dm)

    assessment = _assess_with_claude(new_touchpoints, unmatched_dms, api_key, model)

    sig_by_file: dict[str, list[str]] = {}
    for hit in assessment.get("touchpoint_assessments", []):
        fp = hit.get("filepath", "")
        reason = hit.get("reason", "")
        key = hit.get("key", "")
        # Reconstruct the touchpoint string from the key and filepath
        for tp in new_touchpoints.get(fp, []):
            if tp["subject"] in key:
                tp_str = f"{tp['date']} | {tp['source']} | \"{tp['subject']}\""
                if reason:
                    tp_str += f" | {reason}"
                sig_by_file.setdefault(fp, []).append(tp_str)
                break

    for filepath in matched_files:
        if not Path(filepath).exists():
            continue
        existing = read_auto_section(filepath)
        significant = list(existing["significant"]) + sig_by_file.get(filepath, [])
        routine_new = [
            f"{tp['date']} | {tp['source']} | \"{tp['subject']}\""
            for tp in new_touchpoints.get(filepath, [])
            if not any(tp["subject"] in s for s in sig_by_file.get(filepath, []))
        ]
        routine = (routine_new + existing["routine"])[:MAX_ROUTINE]
        open_threads = new_open_threads.get(filepath, []) + [
            t for t in existing["open_threads"]
            if t not in new_open_threads.get(filepath, [])
        ]
        write_auto_section(filepath, significant, routine, open_threads)

    for profile_data in assessment.get("new_profiles", []):
        if profile_data.get("worth_tracking"):
            _create_profile(profile_data, people_dir)
            new_path = str(Path(people_dir) / profile_data.get("suggested_filename", ""))
            if Path(new_path).exists():
                matched_files.add(new_path)

    context_parts = []
    for filepath in sorted(matched_files):
        if Path(filepath).exists():
            context_parts.append(Path(filepath).read_text())

    return "\n\n---\n\n".join(context_parts)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_people.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/people.py tests/test_people.py
git commit -m "feat: people store — enrich_people orchestrator with Claude assessment"
```

---

## Task 5: Wire people context into `processors/brief.py`

**Files:**
- Modify: `processors/brief.py`
- Modify: `tests/test_brief.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_brief.py`:

```python
def test_people_context_appears_in_prompt():
    from processors.brief import _build_prompt
    from collectors.calendar import CalendarEvent
    from collectors.gmail import EmailThread
    from datetime import datetime

    # Minimal valid inputs
    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=MagicMock(resolved_email_ids=[], still_open_email_ids=[]),
        open_issues=[],
        personal_emails=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        people_context="## People Context\n\n# Luke Martin\n**Email:** lmartin@teambuildr.com",
    )
    assert "Luke Martin" in prompt
    assert "People Context" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_brief.py::test_people_context_appears_in_prompt -v
```
Expected: `FAILED — _build_prompt() got unexpected keyword argument 'people_context'`

- [ ] **Step 3: Add `people_context` to `_build_prompt` and `generate_brief` in `processors/brief.py`**

In `_build_prompt`, add `people_context: str = ""` parameter and add to the sections list:

```python
def _build_prompt(
    today_events: list[CalendarEvent],
    tomorrow_events: list[CalendarEvent],
    email_threads: list[EmailThread],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    open_issues: list[Issue],
    personal_emails: list[PersonalEmail],
    drafts: list[Draft],
    meeting_prep: list[str],
    inbox_text: str,
    attention_leads: list[PipelineLead] = None,
    gym_scout_leads: list[GymScoutLead] = None,
    people_context: str = "",
) -> str:
```

Add at the beginning of the `sections` list (before `## Open Issues`):

```python
sections = [
    "## People Context (background — use to identify missed deliverables and add relationship context)",
    people_context if people_context else "  (no contacts matched today)",
    "",
    # ... existing sections follow unchanged ...
]
```

In `generate_brief`, add `people_context: str = ""` parameter and pass it through:

```python
def generate_brief(
    api_key: str,
    model: str,
    today_events: list[CalendarEvent],
    tomorrow_events: list[CalendarEvent],
    email_threads: list[EmailThread],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    open_issues: list[Issue] = None,
    personal_emails: list[PersonalEmail] = None,
    drafts: list[Draft] = None,
    meeting_prep: list[str] = None,
    inbox_text: str = "",
    attention_leads: list[PipelineLead] = None,
    gym_scout_leads: list[GymScoutLead] = None,
    people_context: str = "",
) -> BriefContent:
```

In the `_build_prompt(...)` call inside `generate_brief`, add:

```python
    people_context=people_context,
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_brief.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add processors/brief.py tests/test_brief.py
git commit -m "feat: inject people context into brief prompt"
```

---

## Task 6: Wire into `main.py` and `config.json`

**Files:**
- Modify: `main.py`
- Modify: `config.json`

- [ ] **Step 1: Add `people_dir` to `config.json`**

Open `config.json` and add:

```json
"people_dir": "data/people"
```

- [ ] **Step 2: Wire `enrich_people` into `main.py`**

Add import at top of `main.py`:

```python
from processors.people import enrich_people
```

In `run()`, add the enrichment call after all collectors finish and before the brief is generated. Insert after the `gym_scout_leads` block and before `todays_drafts = load_todays_drafts(...)`:

```python
    print("🧠  Enriching people store...")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    slack_dms = []
    if slack_token:
        from collectors.slack import fetch_dm_messages
        slack_dms = fetch_dm_messages(token=slack_token, since_hours=24)

    people_context = ""
    people_dir = config.get("people_dir", "data/people")
    if os.path.isdir(people_dir):
        people_context = enrich_people(
            calendar_events=today_events,
            email_threads=email_threads,
            slack_dms=slack_dms,
            people_dir=people_dir,
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            model=config["ai_model"],
        )
```

Pass `people_context` to `generate_brief`:

```python
    brief = generate_brief(
        api_key=api_key,
        model=config["ai_model"],
        today_events=today_events,
        tomorrow_events=tomorrow_events,
        email_threads=email_threads,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        open_issues=open_issues,
        personal_emails=personal_emails,
        drafts=todays_drafts,
        meeting_prep=meeting_prep,
        inbox_text=inbox_text,
        attention_leads=attention_leads,
        gym_scout_leads=gym_scout_leads,
        people_context=people_context,   # ← add this line
    )
```

- [ ] **Step 3: Run full test suite to confirm nothing is broken**

```bash
pytest tests/ -v
```
Expected: all tests pass (new people tests + all existing tests).

- [ ] **Step 4: Smoke test with dry-run**

```bash
python main.py --dry-run --no-email
```
Expected: prints `🧠  Enriching people store...` and completes without error.

- [ ] **Step 5: Commit**

```bash
git add main.py config.json
git commit -m "feat: wire people enrichment into main pipeline"
```

---

## Self-Review Checklist

- [x] **Spec: File organization** — Task 1 migrates files to `data/people/`, deletes `__pycache__/people copy/`
- [x] **Spec: Marker boundary** — `write_auto_section` splits on MARKER, never touches human section; tested in Task 3
- [x] **Spec: Email index from markdown** — `build_email_index` scans `**Email:**` fields; tested in Task 3
- [x] **Spec: Calendar + Gmail + Slack DM enrichment** — `enrich_people` processes all three; tested in Task 4
- [x] **Spec: Slack DM auto-profile creation** — `_create_profile` + Claude JSON response; tested in Task 4
- [x] **Spec: Two-tier touchpoint decay** — significant persists, routine capped at 5; tested in Tasks 3 & 4
- [x] **Spec: One Claude call per run** — `_assess_with_claude` batches all assessments + DM profiles
- [x] **Spec: People context as brief background** — `_build_prompt` injects before issues; tested in Task 5
- [x] **Spec: Unmatched calendar/Gmail emails skipped** — handled in `enrich_people`, tested in Task 4
- [x] **Type consistency** — `MARKER`, `MAX_ROUTINE`, `_extract_email`, `read_auto_section`, `write_auto_section`, `build_email_index`, `enrich_people` names consistent across Tasks 3, 4, 5
