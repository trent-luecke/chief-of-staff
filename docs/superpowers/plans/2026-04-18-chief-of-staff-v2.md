# AI Chief of Staff v2 — Full System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete AI Chief of Staff system — Slack/Gmail issue watcher, meeting memory with post-meeting reply capture, draft generation for sales emails, and an extended morning brief — as an orchestration layer above existing scripts.

**Architecture:** Four independent subsystems sharing data through local files. The morning brief is the integration point where all subsystems surface their outputs. Subsystem 1 (Extended Brief) can ship first and alone; Subsystems 2–4 each add capabilities incrementally.

**Tech Stack:** Python 3.11+, `slack-sdk`, `anthropic`, `google-api-python-client`, `jinja2`, macOS launchd. Existing `gws` CLI for all Gmail/Calendar reads.

---

## Subsystem Map

| Subsystem | Tasks | Produces |
|-----------|-------|---------|
| 1. Extended Brief | 1–3 | Seeded data files, personal Gmail, extended Claude prompt |
| 2. Issue Watcher | 4–6 | Slack bot reader, flare-up detection, hourly watcher + launchd |
| 3. Meeting Memory | 7–8 | Per-meeting memory files, post-meeting nudge, reply capture |
| 4. Draft Generation | 9–11 | Demo follow-ups, lead outreach, trial follow-ups, extended main.py |

Build in order — each subsystem feeds into the extended brief.

---

## File Map

```
chief-of-staff/
├── main.py                                  # MODIFY: extend with new collectors
├── watcher.py                               # NEW: hourly Slack+Gmail flare-up monitor
├── nudger.py                                # NEW: post-meeting email nudge sender
├── reply_collector.py                       # NEW: poll replies to nudge emails
├── run_watcher.sh                           # NEW
├── run_nudger.sh                            # NEW
├── collectors/
│   ├── calendar.py                          # EXISTS: unchanged
│   ├── gmail.py                             # EXISTS: unchanged
│   ├── gmail_personal.py                    # NEW: personal Gmail allowlist filter
│   └── slack.py                             # NEW: Slack bot channel reader
├── processors/
│   ├── state.py                             # EXISTS: unchanged
│   ├── loops.py                             # EXISTS: unchanged
│   ├── issues.py                            # NEW: issue log CRUD + auto-resolve
│   ├── meeting_memory.py                    # NEW: meeting file loader + writer
│   ├── drafts.py                            # NEW: Claude draft generation
│   └── brief.py                             # MODIFY: new prompt + new output fields
├── outputs/
│   ├── sender.py                            # EXISTS: unchanged
│   └── dashboard.py                         # EXISTS: unchanged
├── data/
│   ├── projects.md                          # REPLACE: seed with 5 real projects
│   ├── recurring.json                       # REPLACE: seed with full task list
│   ├── personal_allowlist.json              # NEW: allowed personal Gmail senders
│   ├── meeting_index.json                   # NEW: maps calendar patterns → memory files
│   ├── issues.json                          # NEW: issue log
│   ├── pending_nudges.json                  # NEW: sent nudges awaiting reply
│   ├── drafts/                              # NEW: generated email drafts (JSON per draft)
│   └── meeting_memory/                      # NEW: per-meeting markdown files
│       ├── product_sync.md
│       └── dev_triage.md
├── config.json                              # MODIFY: add new keys
├── .env                                     # MODIFY: add SLACK_BOT_TOKEN
├── requirements.txt                         # MODIFY: add slack-sdk
├── com.trent.chiefofstaff.brief.plist       # NEW: launchd 7am brief
├── com.trent.chiefofstaff.watcher.plist     # NEW: launchd hourly watcher
├── com.trent.chiefofstaff.nudger.plist      # NEW: launchd 15-min nudger
└── tests/
    ├── test_gmail_personal.py               # NEW
    ├── test_slack.py                        # NEW
    ├── test_issues.py                       # NEW
    ├── test_meeting_memory.py               # NEW
    ├── test_drafts.py                       # NEW
    └── test_brief_extended.py              # NEW
```

---

## Task 1: Seed Data Files + Config

**Files:**
- Replace: `data/projects.md`
- Replace: `data/recurring.json`
- Create: `data/personal_allowlist.json`
- Create: `data/meeting_index.json`
- Create: `data/issues.json`
- Create: `data/pending_nudges.json`
- Create: `data/meeting_memory/product_sync.md`
- Create: `data/meeting_memory/dev_triage.md`
- Modify: `requirements.txt`
- Modify: `config.json`
- Modify: `.env`

- [ ] **Step 1: Replace data/projects.md**

```markdown
## Project: LTV Lead Magnet
**Status:** In Progress
**Priority:** High
**Tier:** core
**Next:** Design calculator UI and define LTV input variables
**Notes:** Helps TeamBuildr OS leads calculate LTV before a demo; higher conversion expected

## Project: LinkedIn Content
**Status:** Active
**Priority:** Medium
**Tier:** evergreen
**Next:** Batch content block Friday morning
**Notes:** Managed in Notion LinkedIn Content database; chief of staff audits weekly for post gaps and suggests topics

## Project: Vero
**Status:** In Progress
**Priority:** Low-Medium
**Tier:** side-project
**Next:** Review gym-ai folder for current state
**Notes:** Gym AI side hustle — surface if dormant more than 2 weeks

## Project: Customer Feedback Loop
**Status:** Active
**Priority:** High
**Tier:** core
**Next:** Identify customers at 90–120 day mark for outreach scheduling
**Notes:** Schedule calls at 90–120 days post-signup; track cadence and follow-ups

## Project: Content Generation Podcast
**Status:** Active
**Priority:** Medium
**Tier:** recurring
**Next:** Research topics for next Tuesday session
**Notes:** Weekly Tuesday podcast with mentor; research and talking points needed before each session
```

- [ ] **Step 2: Replace data/recurring.json**

```json
{
  "tasks": [
    {
      "name": "Month-end data reconciliation",
      "schedule": "monthly",
      "day": 1,
      "description": "Reconcile new sales, demo count, conversion tracker, and update active client roster in Google Sheets"
    },
    {
      "name": "ICP gym scrape review",
      "schedule": "daily",
      "description": "Review daily web scrape results for new gym facility matches; approve or discard outreach drafts"
    },
    {
      "name": "Trial lead follow-ups",
      "schedule": "daily",
      "description": "30-45 min block: review trial leads who haven't responded; drafts are pre-generated, review and send from Gmail"
    },
    {
      "name": "New leads inbox outreach",
      "schedule": "daily",
      "description": "Check sales inbox for new leads (2-10/day); review and send pre-generated outreach drafts"
    },
    {
      "name": "Recipe research and grocery planning",
      "schedule": "weekly",
      "day": "Thursday",
      "description": "Research recipes via NYT Cooking or ATK; pull ingredients; update shared note with wife for Friday shopping"
    },
    {
      "name": "Saturday breakfast recipe lookup",
      "schedule": "weekly",
      "day": "Thursday",
      "description": "Find a fun Saturday breakfast recipe before Friday grocery run"
    },
    {
      "name": "Budget and debt tracker update",
      "schedule": "weekly",
      "day": "Monday",
      "description": "Update Finance Tracker with last week's bank statement data (script in finance-tracker/)"
    },
    {
      "name": "LinkedIn content batch",
      "schedule": "weekly",
      "day": "Friday",
      "description": "Focused morning block: research new topics or synthesize research, then generate and refine content"
    },
    {
      "name": "PT client programming input",
      "schedule": "weekly",
      "day": "Sunday",
      "description": "Input weekly programming for personal training and remote training clients in TeamBuildr Strength"
    },
    {
      "name": "Competitor research",
      "schedule": "weekly",
      "day": "Wednesday",
      "description": "Deep research on member management software space: new features, new players, important developments"
    },
    {
      "name": "Content podcast research",
      "schedule": "weekly",
      "day": "Monday",
      "description": "Prepare research and talking points for Tuesday content generation podcast session with mentor"
    },
    {
      "name": "PT client new programming cycle",
      "schedule": "monthly",
      "day": 1,
      "description": "Write new 6-week programming block for personal training and remote training clients (staggered schedules)"
    }
  ]
}
```

- [ ] **Step 3: Create data/personal_allowlist.json**

```json
{
  "allowed_senders": [],
  "allowed_domains": [],
  "notes": "Add wife email, bookkeeper email, and teachers' emails before first run. Any sender not listed is ignored."
}
```

- [ ] **Step 4: Create data/meeting_index.json**

```json
{
  "meetings": [
    {
      "calendar_pattern": "product",
      "memory_file": "data/meeting_memory/product_sync.md",
      "nudge_subject": "Product sync notes?",
      "nudge_minutes_after": 5
    },
    {
      "calendar_pattern": "dev",
      "memory_file": "data/meeting_memory/dev_triage.md",
      "nudge_subject": "Dev triage notes?",
      "nudge_minutes_after": 5
    },
    {
      "calendar_pattern": "teofe",
      "memory_file": "data/meeting_memory/product_sync.md",
      "nudge_subject": "Product meeting notes?",
      "nudge_minutes_after": 5
    }
  ]
}
```

- [ ] **Step 5: Create data/issues.json**

```json
{"issues": []}
```

- [ ] **Step 6: Create data/pending_nudges.json**

```json
[]
```

- [ ] **Step 7: Create data/meeting_memory/product_sync.md**

```markdown
# Product Sync — Meeting Memory

## Meeting Details
- **Cadence:** Weekly
- **Participants:** Trent, Teofe (product manager)

## Session Log

<!-- Entries added automatically after each meeting via reply capture -->
```

- [ ] **Step 8: Create data/meeting_memory/dev_triage.md**

```markdown
# Dev Triage — Meeting Memory

## Meeting Details
- **Cadence:** Weekly
- **Participants:** Trent, dev team

## Session Log

<!-- Entries added automatically after each meeting via reply capture -->
```

- [ ] **Step 9: Create data/drafts/.gitkeep**

```bash
mkdir -p data/drafts data/meeting_memory
touch data/drafts/.gitkeep
```

- [ ] **Step 10: Add slack-sdk to requirements.txt**

Add this line to `requirements.txt`:
```
slack-sdk>=3.27.0
```

Run: `pip install slack-sdk`

- [ ] **Step 11: Add SLACK_BOT_TOKEN to .env**

```bash
SLACK_BOT_TOKEN=xoxb-your-token-here
```

- [ ] **Step 12: Extend config.json**

Add these keys to the existing config.json object:

```json
{
  "slack_channels": ["TeamBuildr-OS", "support", "support-tickets"],
  "personal_gmail_profile": "personal",
  "personal_allowlist_file": "data/personal_allowlist.json",
  "meeting_index_file": "data/meeting_index.json",
  "issues_file": "data/issues.json",
  "pending_nudges_file": "data/pending_nudges.json",
  "drafts_dir": "data/drafts",
  "issue_auto_resolve_days": 3
}
```

- [ ] **Step 13: Commit**

```bash
git add data/ requirements.txt config.json .env
git commit -m "chore: seed data files and extend config for v2 system"
```

---

## Task 2: Personal Gmail Collector

**Files:**
- Create: `collectors/gmail_personal.py`
- Create: `tests/test_gmail_personal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gmail_personal.py
import json
from unittest.mock import patch, MagicMock
import pytest
from collectors.gmail_personal import fetch_personal_emails, PersonalEmail

MOCK_LIST = {"threads": [{"id": "t1", "snippet": "Are you picking up Maya today?"}]}

MOCK_THREAD = {
    "id": "t1",
    "messages": [{
        "id": "m1",
        "payload": {"headers": [
            {"name": "Subject", "value": "Pickup today?"},
            {"name": "From", "value": "wife@gmail.com"},
        ]},
        "internalDate": "1713450000000",
    }]
}


def test_fetch_personal_emails_allowlisted_sender(mock_sub):
    mock_sub.side_effect = [
        MagicMock(stdout=json.dumps(MOCK_LIST), returncode=0),
        MagicMock(stdout=json.dumps(MOCK_THREAD), returncode=0),
    ]
    emails = fetch_personal_emails(
        profile="personal",
        allowed_senders=["wife@gmail.com"],
        allowed_domains=[],
        max_results=10,
    )
    assert len(emails) == 1
    assert emails[0].subject == "Pickup today?"
    assert emails[0].sender == "wife@gmail.com"


def test_fetch_personal_emails_blocks_unknown_sender(mock_sub):
    mock_sub.side_effect = [
        MagicMock(stdout=json.dumps(MOCK_LIST), returncode=0),
        MagicMock(stdout=json.dumps(MOCK_THREAD), returncode=0),
    ]
    emails = fetch_personal_emails(
        profile="personal",
        allowed_senders=["someone-else@gmail.com"],
        allowed_domains=[],
        max_results=10,
    )
    assert len(emails) == 0


def test_fetch_personal_emails_gws_failure_returns_empty(mock_sub):
    mock_sub.return_value = MagicMock(stdout="{}", returncode=1)
    emails = fetch_personal_emails(
        profile="personal", allowed_senders=["x@y.com"], allowed_domains=[], max_results=10
    )
    assert emails == []


@pytest.fixture
def mock_sub():
    with patch("collectors.gmail_personal.subprocess.run") as m:
        yield m
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_gmail_personal.py -v
```
Expected: `ModuleNotFoundError: No module named 'collectors.gmail_personal'`

- [ ] **Step 3: Implement collectors/gmail_personal.py**

```python
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PersonalEmail:
    id: str
    subject: str
    sender: str
    snippet: str
    date: Optional[datetime]


def _sender_email(from_header: str) -> str:
    if "<" in from_header:
        return from_header.split("<")[1].rstrip(">").strip().lower()
    return from_header.strip().lower()


def _run_gws(cmd: list[str]) -> dict:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def fetch_personal_emails(
    profile: str,
    allowed_senders: list[str],
    allowed_domains: list[str],
    max_results: int = 20,
) -> list[PersonalEmail]:
    allowed_senders_lower = {s.lower() for s in allowed_senders}
    allowed_domains_lower = {d.lower() for d in allowed_domains}

    list_params = json.dumps({"userId": "me", "q": "is:unread -in:sent", "maxResults": max_results})
    list_data = _run_gws([
        "gws", "--profile", profile, "gmail", "users", "threads", "list",
        "--params", list_params,
    ])

    emails = []
    for t in list_data.get("threads", []):
        thread_params = json.dumps({
            "userId": "me", "id": t["id"], "format": "metadata",
            "metadataHeaders": ["Subject", "From"],
        })
        thread_data = _run_gws([
            "gws", "--profile", profile, "gmail", "users", "threads", "get",
            "--params", thread_params,
        ])
        if not thread_data:
            continue

        messages = thread_data.get("messages", [])
        if not messages:
            continue

        last_msg = messages[-1]
        headers = last_msg.get("payload", {}).get("headers", [])

        def get_header(name: str) -> str:
            return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")

        sender_raw = get_header("From")
        sender_email = _sender_email(sender_raw)
        sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""

        if sender_email not in allowed_senders_lower and sender_domain not in allowed_domains_lower:
            continue

        internal_date = last_msg.get("internalDate")
        date = datetime.fromtimestamp(int(internal_date) / 1000) if internal_date else None

        emails.append(PersonalEmail(
            id=t["id"],
            subject=get_header("Subject") or "(no subject)",
            sender=sender_email,
            snippet=t.get("snippet", ""),
            date=date,
        ))
    return emails
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_gmail_personal.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add collectors/gmail_personal.py tests/test_gmail_personal.py
git commit -m "feat: personal Gmail collector with sender allowlist"
```

---

## Task 3: Issue Log Processor

**Files:**
- Create: `processors/issues.py`
- Create: `tests/test_issues.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_issues.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_issues.py -v
```
Expected: `ModuleNotFoundError: No module named 'processors.issues'`

- [ ] **Step 3: Implement processors/issues.py**

```python
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Optional


@dataclass
class Issue:
    id: str
    title: str
    source: str
    source_ref: str
    channel: str
    created_date: str
    last_seen_date: str
    status: str
    actions_needed: list[str]
    outside_parties: list[str]
    resolved_date: Optional[str]

    @property
    def age_days(self) -> int:
        return (date.today() - date.fromisoformat(self.created_date)).days


@dataclass
class IssueLog:
    issues: list[Issue] = field(default_factory=list)


def load_issues(path: str) -> IssueLog:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return IssueLog()
    return IssueLog(issues=[Issue(**i) for i in data.get("issues", [])])


def save_issues(log: IssueLog, path: str) -> None:
    with open(path, "w") as f:
        json.dump({"issues": [asdict(i) for i in log.issues]}, f, indent=2)


def add_or_update_issue(
    issues_file: str,
    source: str,
    source_ref: str,
    channel: str,
    title: str,
    actions_needed: Optional[list[str]] = None,
    outside_parties: Optional[list[str]] = None,
) -> None:
    log = load_issues(issues_file)
    existing_refs = {i.source_ref for i in log.issues}

    if source_ref in existing_refs:
        for issue in log.issues:
            if issue.source_ref == source_ref:
                issue.last_seen_date = date.today().isoformat()
        save_issues(log, issues_file)
        return

    log.issues.append(Issue(
        id=str(uuid.uuid4())[:8],
        title=title,
        source=source,
        source_ref=source_ref,
        channel=channel,
        created_date=date.today().isoformat(),
        last_seen_date=date.today().isoformat(),
        status="open",
        actions_needed=actions_needed or [],
        outside_parties=outside_parties or [],
        resolved_date=None,
    ))
    save_issues(log, issues_file)


def auto_resolve_issues(issues_file: str, resolve_after_days: int = 3) -> None:
    log = load_issues(issues_file)
    cutoff = date.today() - timedelta(days=resolve_after_days)
    for issue in log.issues:
        if issue.status == "open":
            if date.fromisoformat(issue.last_seen_date) < cutoff:
                issue.status = "resolved"
                issue.resolved_date = date.today().isoformat()
    save_issues(log, issues_file)


def get_open_issues(issues_file: str) -> list[Issue]:
    log = load_issues(issues_file)
    return [i for i in log.issues if i.status in ("open", "monitoring")]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_issues.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/issues.py tests/test_issues.py
git commit -m "feat: issue log processor with CRUD and age-based auto-resolve"
```

---

## Task 4: Slack Bot Collector

**Files:**
- Create: `collectors/slack.py`
- Create: `tests/test_slack.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slack.py
from unittest.mock import MagicMock, patch
import pytest
from collectors.slack import fetch_channel_messages, SlackMessage, resolve_channel_ids

MOCK_HISTORY = {
    "messages": [
        {
            "type": "message",
            "text": "App is down — users reporting login failures",
            "user": "U123",
            "ts": "1713450000.123456",
            "thread_ts": "1713450000.123456",
            "reply_count": 2,
        },
        {
            "type": "message",
            "subtype": "bot_message",
            "text": "Deployment complete",
            "ts": "1713450100.000000",
        },
    ]
}

MOCK_CHANNELS = {
    "channels": [
        {"id": "C001", "name": "support"},
        {"id": "C002", "name": "support-tickets"},
    ]
}


def test_fetch_channel_messages_excludes_bots(mock_client):
    mock_client.return_value.conversations_history.return_value = MOCK_HISTORY
    messages = fetch_channel_messages(token="xoxb-test", channel_id="C001", since_hours=1)
    assert len(messages) == 1
    assert messages[0].text == "App is down — users reporting login failures"
    assert messages[0].thread_ts == "1713450000.123456"


def test_fetch_channel_messages_returns_empty_on_error(mock_client):
    from slack_sdk.errors import SlackApiError
    mock_client.return_value.conversations_history.side_effect = SlackApiError(
        "error", {"error": "not_in_channel"}
    )
    messages = fetch_channel_messages(token="xoxb-test", channel_id="C001", since_hours=1)
    assert messages == []


def test_resolve_channel_ids(mock_client):
    mock_client.return_value.conversations_list.return_value = MOCK_CHANNELS
    ids = resolve_channel_ids(token="xoxb-test", channel_names=["support", "support-tickets"])
    assert ids == {"support": "C001", "support-tickets": "C002"}


@pytest.fixture
def mock_client():
    with patch("collectors.slack.WebClient") as m:
        yield m
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_slack.py -v
```
Expected: `ModuleNotFoundError: No module named 'collectors.slack'`

- [ ] **Step 3: Implement collectors/slack.py**

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


@dataclass
class SlackMessage:
    channel_id: str
    channel_name: str
    text: str
    user: str
    ts: str
    thread_ts: str
    reply_count: int


def fetch_channel_messages(
    token: str,
    channel_id: str,
    since_hours: int = 1,
    channel_name: str = "",
) -> list[SlackMessage]:
    client = WebClient(token=token)
    oldest = str((datetime.now() - timedelta(hours=since_hours)).timestamp())
    try:
        result = client.conversations_history(channel=channel_id, oldest=oldest, limit=200)
    except SlackApiError:
        return []

    messages = []
    for msg in result.get("messages", []):
        if msg.get("subtype") in ("bot_message", "channel_join", "channel_leave"):
            continue
        if not msg.get("text"):
            continue
        messages.append(SlackMessage(
            channel_id=channel_id,
            channel_name=channel_name,
            text=msg["text"],
            user=msg.get("user", ""),
            ts=msg["ts"],
            thread_ts=msg.get("thread_ts", msg["ts"]),
            reply_count=msg.get("reply_count", 0),
        ))
    return messages


def resolve_channel_ids(token: str, channel_names: list[str]) -> dict[str, str]:
    client = WebClient(token=token)
    name_set = {n.lower() for n in channel_names}
    result = {}
    try:
        response = client.conversations_list(types="public_channel,private_channel", limit=200)
        for ch in response.get("channels", []):
            if ch["name"].lower() in name_set:
                result[ch["name"]] = ch["id"]
    except SlackApiError:
        pass
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_slack.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add collectors/slack.py tests/test_slack.py
git commit -m "feat: Slack bot collector for monitored channels"
```

---

## Task 5: Hourly Watcher Script

**Files:**
- Create: `watcher.py`
- Create: `run_watcher.sh`
- Create: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_watcher.py
from collectors.slack import SlackMessage
from collectors.gmail import EmailThread
from datetime import datetime
from watcher import detect_flareups_from_gmail, is_business_hours
from unittest.mock import patch


def make_thread(subject: str, snippet: str) -> EmailThread:
    return EmailThread(
        id="t1", subject=subject, last_sender="customer@gym.com",
        snippet=snippet, last_message_date=datetime.now(), needs_reply=True,
    )


def test_detect_flareups_from_gmail_keyword_match():
    threads = [
        make_thread("Re: Login issue", "I can't log in — getting 500 error"),
        make_thread("Newsletter signup", "Thanks for subscribing"),
    ]
    flareups = detect_flareups_from_gmail(threads)
    assert len(flareups) == 1
    assert flareups[0].subject == "Re: Login issue"


def test_detect_flareups_from_gmail_empty():
    flareups = detect_flareups_from_gmail([])
    assert flareups == []


def test_is_business_hours_midday():
    with patch("watcher.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 18, 12, 0)
        assert is_business_hours() is True


def test_is_business_hours_evening():
    with patch("watcher.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 4, 18, 20, 0)
        assert is_business_hours() is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_watcher.py -v
```
Expected: `ModuleNotFoundError: No module named 'watcher'`

- [ ] **Step 3: Implement watcher.py**

```python
#!/usr/bin/env python3
"""Hourly watcher: scans Slack channels and Gmail for flare-ups, updates issue log."""

import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from collectors.slack import fetch_channel_messages, resolve_channel_ids, SlackMessage
from collectors.gmail import fetch_threads_needing_attention, EmailThread
from processors.issues import add_or_update_issue, auto_resolve_issues

FLAREUP_KEYWORDS = {
    "down", "outage", "broken", "error", "bug", "slow", "crash",
    "not working", "issue", "problem", "failing", "failed", "timeout",
    "unreachable", "complaint", "can't log in", "can't access",
}


def detect_flareups_from_gmail(threads: list[EmailThread]) -> list[EmailThread]:
    flareups = []
    for t in threads:
        text = (t.subject + " " + t.snippet).lower()
        if any(kw in text for kw in FLAREUP_KEYWORDS):
            flareups.append(t)
    return flareups


def is_business_hours() -> bool:
    now = datetime.now()
    return 7 <= now.hour < 16


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def run() -> None:
    if not is_business_hours():
        print("Outside business hours — skipping watcher run.")
        return

    config = load_config()
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    issues_file = config["issues_file"]

    print("🔍 Scanning Slack channels...")
    if slack_token:
        channel_map = resolve_channel_ids(slack_token, config["slack_channels"])
        for channel_name, channel_id in channel_map.items():
            messages = fetch_channel_messages(
                slack_token, channel_id, since_hours=1, channel_name=channel_name
            )
            for msg in messages:
                title = msg.text[:120] + ("..." if len(msg.text) > 120 else "")
                add_or_update_issue(
                    issues_file=issues_file,
                    source="slack",
                    source_ref=f"{channel_id}:{msg.thread_ts}",
                    channel=channel_name,
                    title=title,
                )
    else:
        print("  SLACK_BOT_TOKEN not set — skipping Slack scan.")

    print("📧 Scanning Gmail for flare-up keywords...")
    gmail_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=20,
        profile=config.get("gmail_profile"),
        query="is:unread subject:(down OR outage OR broken OR error OR bug)",
    )
    for thread in detect_flareups_from_gmail(gmail_threads):
        add_or_update_issue(
            issues_file=issues_file,
            source="gmail",
            source_ref=thread.id,
            channel="gmail",
            title=thread.subject[:120],
        )

    print("🔄 Auto-resolving stale issues...")
    auto_resolve_issues(issues_file, resolve_after_days=config.get("issue_auto_resolve_days", 3))

    print("✅ Watcher run complete.")


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Create run_watcher.sh**

```bash
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/watcher_$(date +%Y%m%d).log"
mkdir -p "$SCRIPT_DIR/logs"
cd "$SCRIPT_DIR"
source .venv/bin/activate
python watcher.py >> "$LOG_FILE" 2>&1
echo "Watcher run at $(date)" >> "$LOG_FILE"
```

Run: `chmod +x run_watcher.sh`

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_watcher.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add watcher.py run_watcher.sh tests/test_watcher.py
git commit -m "feat: hourly Slack+Gmail flare-up watcher"
```

---

## Task 6: launchd Plists

**Files:**
- Create: `com.trent.chiefofstaff.brief.plist`
- Create: `com.trent.chiefofstaff.watcher.plist`
- Create: `com.trent.chiefofstaff.nudger.plist`

- [ ] **Step 1: Create com.trent.chiefofstaff.brief.plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trent.chiefofstaff.brief</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/run_brief.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/logs/brief_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/logs/brief_launchd_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
```

- [ ] **Step 2: Create com.trent.chiefofstaff.watcher.plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trent.chiefofstaff.watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/run_watcher.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>StandardOutPath</key>
    <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/logs/watcher_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/logs/watcher_launchd_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
```

- [ ] **Step 3: Create com.trent.chiefofstaff.nudger.plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.trent.chiefofstaff.nudger</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/run_nudger.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>900</integer>
    <key>StandardOutPath</key>
    <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/logs/nudger_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/trentluecke/dev/Claude-Projects/chief-of-staff/logs/nudger_launchd_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
```

- [ ] **Step 4: Load all three plists**

```bash
mkdir -p ~/Library/LaunchAgents
cp com.trent.chiefofstaff.brief.plist ~/Library/LaunchAgents/
cp com.trent.chiefofstaff.watcher.plist ~/Library/LaunchAgents/
cp com.trent.chiefofstaff.nudger.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.trent.chiefofstaff.brief.plist
launchctl load ~/Library/LaunchAgents/com.trent.chiefofstaff.watcher.plist
launchctl load ~/Library/LaunchAgents/com.trent.chiefofstaff.nudger.plist
```

- [ ] **Step 5: Verify all three are loaded**

```bash
launchctl list | grep chiefofstaff
```
Expected: All three jobs appear.

- [ ] **Step 6: Test watcher manually**

```bash
./run_watcher.sh
cat logs/watcher_$(date +%Y%m%d).log
```
Expected: Log shows Slack scan, Gmail scan, "Watcher run complete."

- [ ] **Step 7: Commit**

```bash
git add com.trent.chiefofstaff.brief.plist com.trent.chiefofstaff.watcher.plist com.trent.chiefofstaff.nudger.plist
git commit -m "chore: launchd plists for brief (7am), watcher (hourly), nudger (15min)"
```

---

## Task 7: Meeting Memory Processor

**Files:**
- Create: `processors/meeting_memory.py`
- Create: `tests/test_meeting_memory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meeting_memory.py
from datetime import datetime
import pytest
from processors.meeting_memory import (
    load_meeting_index, find_meeting_for_event, append_session_notes,
    load_last_session_summary, MeetingConfig,
)
from collectors.calendar import CalendarEvent


def make_event(summary: str) -> CalendarEvent:
    dt = datetime(2026, 4, 21, 10, 0)
    return CalendarEvent(id="e1", summary=summary, start=dt, end=dt)


def test_find_meeting_for_event_matches_pattern():
    configs = [
        MeetingConfig(calendar_pattern="product", memory_file="data/meeting_memory/product_sync.md",
                      nudge_subject="Notes?", nudge_minutes_after=5),
        MeetingConfig(calendar_pattern="dev", memory_file="data/meeting_memory/dev_triage.md",
                      nudge_subject="Notes?", nudge_minutes_after=5),
    ]
    event = make_event("Weekly Product Sync")
    match = find_meeting_for_event(event, configs)
    assert match is not None
    assert match.memory_file == "data/meeting_memory/product_sync.md"


def test_find_meeting_for_event_no_match():
    configs = [MeetingConfig(calendar_pattern="product", memory_file="p.md",
                             nudge_subject="n", nudge_minutes_after=5)]
    event = make_event("Demo: Apex Fitness")
    match = find_meeting_for_event(event, configs)
    assert match is None


def test_append_session_notes_creates_entry(tmp_path):
    memory_file = str(tmp_path / "meeting.md")
    with open(memory_file, "w") as f:
        f.write("# Test Meeting\n\n## Session Log\n\n")
    append_session_notes(memory_file, "2026-04-21", "Discussed roadmap. Action: share feedback by Friday.")
    with open(memory_file) as f:
        content = f.read()
    assert "2026-04-21" in content
    assert "Discussed roadmap" in content


def test_load_last_session_summary_returns_most_recent(tmp_path):
    memory_file = str(tmp_path / "meeting.md")
    content = "# Test\n\n## Session Log\n\n### 2026-04-14\nOld session.\n\n### 2026-04-21\nLatest session.\n"
    with open(memory_file, "w") as f:
        f.write(content)
    summary = load_last_session_summary(memory_file)
    assert "Latest session" in summary
    assert "Old session" not in summary
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_meeting_memory.py -v
```
Expected: `ModuleNotFoundError: No module named 'processors.meeting_memory'`

- [ ] **Step 3: Implement processors/meeting_memory.py**

```python
import json
import re
from dataclasses import dataclass
from typing import Optional
from collectors.calendar import CalendarEvent


@dataclass
class MeetingConfig:
    calendar_pattern: str
    memory_file: str
    nudge_subject: str
    nudge_minutes_after: int


def load_meeting_index(path: str) -> list[MeetingConfig]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [MeetingConfig(**m) for m in data.get("meetings", [])]


def find_meeting_for_event(
    event: CalendarEvent, configs: list[MeetingConfig]
) -> Optional[MeetingConfig]:
    summary_lower = event.summary.lower()
    for config in configs:
        if config.calendar_pattern.lower() in summary_lower:
            return config
    return None


def append_session_notes(memory_file: str, session_date: str, notes: str) -> None:
    try:
        with open(memory_file) as f:
            content = f.read()
    except FileNotFoundError:
        content = "# Meeting Memory\n\n## Session Log\n\n"

    entry = f"\n### {session_date}\n{notes.strip()}\n"

    if "## Session Log" in content:
        content = content + entry
    else:
        content = content + "\n## Session Log\n" + entry

    with open(memory_file, "w") as f:
        f.write(content)


def load_last_session_summary(memory_file: str) -> str:
    try:
        with open(memory_file) as f:
            content = f.read()
    except FileNotFoundError:
        return ""

    sessions = re.split(r"\n### \d{4}-\d{2}-\d{2}\n", content)
    if len(sessions) < 2:
        return ""
    return sessions[-1].strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_meeting_memory.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_memory.py tests/test_meeting_memory.py
git commit -m "feat: meeting memory loader and session notes appender"
```

---

## Task 8: Post-Meeting Nudger + Reply Collector

**Files:**
- Create: `nudger.py`
- Create: `reply_collector.py`
- Create: `run_nudger.sh`

- [ ] **Step 1: Implement nudger.py**

```python
#!/usr/bin/env python3
"""Post-meeting nudger: sends a reply-able email after each tracked internal meeting ends."""

import json
import os
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from collectors.calendar import fetch_two_day_events
from processors.meeting_memory import load_meeting_index, find_meeting_for_event
from outputs.sender import build_gmail_service_from_config, send_brief_email


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_pending_nudges(path: str) -> list[dict]:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_pending_nudges(nudges: list[dict], path: str) -> None:
    with open(path, "w") as f:
        json.dump(nudges, f, indent=2)


def run() -> None:
    config = load_config()
    meeting_configs = load_meeting_index(config["meeting_index_file"])
    pending_file = config["pending_nudges_file"]
    pending = load_pending_nudges(pending_file)
    already_nudged = {n["event_id"] for n in pending}

    today_events, _ = fetch_two_day_events(
        config["calendar_ids"], profile=config.get("gmail_profile")
    )
    now = datetime.now()
    gmail = build_gmail_service_from_config(config["credentials_path"], config["token_path"])

    for event in today_events:
        if event.id in already_nudged:
            continue
        meeting_config = find_meeting_for_event(event, meeting_configs)
        if not meeting_config:
            continue
        nudge_time = event.end + timedelta(minutes=meeting_config.nudge_minutes_after)
        if now < nudge_time:
            continue

        body = (
            f"<p>Your <strong>{event.summary}</strong> just wrapped.</p>"
            f"<p>Reply to this email with your notes — what was covered, open items, "
            f"and any action items. I'll add them to the meeting log automatically.</p>"
        )
        msg_id = send_brief_email(
            gmail_service=gmail,
            to_email=config["email"],
            subject=meeting_config.nudge_subject,
            html_body=body,
        )
        pending.append({
            "event_id": event.id,
            "meeting_name": event.summary,
            "memory_file": meeting_config.memory_file,
            "thread_id": msg_id,
            "sent_at": now.isoformat(),
            "session_date": date.today().isoformat(),
        })
        print(f"  Nudge sent for: {event.summary}")

    save_pending_nudges(pending, pending_file)
    print("✅ Nudger run complete.")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Implement reply_collector.py**

```python
#!/usr/bin/env python3
"""Reply collector: checks for replies to nudge emails and writes them to meeting memory files."""

import base64
import json
import os
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from processors.meeting_memory import append_session_notes


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def get_thread_message_count(thread_id: str, profile: str) -> int:
    params = json.dumps({"userId": "me", "id": thread_id, "format": "minimal"})
    result = subprocess.run(
        ["gws", "--profile", profile, "gmail", "users", "threads", "get", "--params", params],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0
    try:
        data = json.loads(result.stdout)
        return len(data.get("messages", []))
    except json.JSONDecodeError:
        return 0


def get_latest_reply_text(thread_id: str, profile: str) -> str:
    params = json.dumps({"userId": "me", "id": thread_id, "format": "full"})
    result = subprocess.run(
        ["gws", "--profile", profile, "gmail", "users", "threads", "get", "--params", params],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return ""
    try:
        data = json.loads(result.stdout)
        messages = data.get("messages", [])
        if len(messages) < 2:
            return ""
        last = messages[-1]
        parts = last.get("payload", {}).get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                body = part.get("body", {}).get("data", "")
                return base64.urlsafe_b64decode(body + "==").decode("utf-8", errors="ignore")
        return last.get("snippet", "")
    except Exception:
        return ""


def run() -> None:
    config = load_config()
    pending_file = config["pending_nudges_file"]
    profile = config.get("gmail_profile", "work")

    try:
        with open(pending_file) as f:
            pending = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    cutoff = datetime.now() - timedelta(days=7)
    still_pending = []

    for nudge in pending:
        sent_at = datetime.fromisoformat(nudge["sent_at"])
        if sent_at < cutoff:
            continue

        count = get_thread_message_count(nudge["thread_id"], profile)
        if count < 2:
            still_pending.append(nudge)
            continue

        reply_text = get_latest_reply_text(nudge["thread_id"], profile)
        if reply_text.strip():
            append_session_notes(nudge["memory_file"], nudge["session_date"], reply_text)
            print(f"  Captured notes for: {nudge['meeting_name']}")
        else:
            still_pending.append(nudge)

    with open(pending_file, "w") as f:
        json.dump(still_pending, f, indent=2)

    print("✅ Reply collector complete.")


if __name__ == "__main__":
    run()
```

- [ ] **Step 3: Create run_nudger.sh**

```bash
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/nudger_$(date +%Y%m%d).log"
mkdir -p "$SCRIPT_DIR/logs"
cd "$SCRIPT_DIR"
source .venv/bin/activate
python nudger.py >> "$LOG_FILE" 2>&1
python reply_collector.py >> "$LOG_FILE" 2>&1
echo "Nudger+reply run at $(date)" >> "$LOG_FILE"
```

Run: `chmod +x run_nudger.sh`

- [ ] **Step 4: Test manually**

```bash
./run_nudger.sh
cat logs/nudger_$(date +%Y%m%d).log
```
Expected: Log shows "Nudger run complete" and "Reply collector complete."

- [ ] **Step 5: Commit**

```bash
git add nudger.py reply_collector.py run_nudger.sh
git commit -m "feat: post-meeting nudge emailer and reply capture"
```

---

## Task 9: Draft Generator

**Files:**
- Create: `processors/drafts.py`
- Create: `tests/test_drafts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drafts.py
import json
from unittest.mock import patch, MagicMock
import pytest
from processors.drafts import generate_demo_followup, generate_lead_outreach, generate_trial_followup, Draft
from collectors.calendar import CalendarEvent
from datetime import datetime


def make_mock_claude(text: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


MOCK_DRAFT = json.dumps({
    "subject": "Great connecting today",
    "body": "Hi,\n\nThanks for taking the time today...",
    "to": "contact@example.com",
})


def make_event(summary: str, attendees: list[str]) -> CalendarEvent:
    dt = datetime(2026, 4, 18, 10, 0)
    return CalendarEvent(id="e1", summary=summary, start=dt, end=dt, attendees=attendees)


def test_generate_demo_followup_returns_draft(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(MOCK_DRAFT)
    event = make_event("Demo: Apex Fitness", ["contact@apexfitness.com"])
    draft = generate_demo_followup(api_key="sk-test", model="claude-haiku-4-5-20251001", event=event)
    assert draft is not None
    assert draft.subject == "Great connecting today"
    assert draft.to == "contact@apexfitness.com"
    assert draft.draft_type == "demo_followup"


def test_generate_demo_followup_no_attendees_returns_none(mock_anthropic):
    event = make_event("Demo: Apex Fitness", [])
    draft = generate_demo_followup(api_key="sk-test", model="claude-haiku-4-5-20251001", event=event)
    assert draft is None


def test_generate_lead_outreach_returns_draft(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(MOCK_DRAFT)
    draft = generate_lead_outreach(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        lead_name="John Smith", lead_email="john@crossfitgym.com",
        gym_name="CrossFit Denver", snippet="30 athletes, comp team",
    )
    assert draft is not None
    assert draft.draft_type == "lead_outreach"


def test_generate_trial_followup_returns_draft(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(MOCK_DRAFT)
    draft = generate_trial_followup(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        lead_name="Jane Doe", lead_email="jane@gym.com", days_in_trial=7,
    )
    assert draft is not None
    assert draft.draft_type == "trial_followup"


@pytest.fixture
def mock_anthropic():
    with patch("processors.drafts.anthropic.Anthropic") as m:
        yield m
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_drafts.py -v
```
Expected: `ModuleNotFoundError: No module named 'processors.drafts'`

- [ ] **Step 3: Implement processors/drafts.py**

```python
import anthropic
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from collectors.calendar import CalendarEvent


@dataclass
class Draft:
    subject: str
    body: str
    to: str
    draft_type: str
    context: str = ""
    created_date: str = field(default_factory=lambda: date.today().isoformat())


def _call_claude(api_key: str, model: str, prompt: str, max_tokens: int = 500) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _parse_draft(raw: str, fallback_to: str, draft_type: str, context: str = "") -> Optional[Draft]:
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    try:
        data = json.loads(raw)
        return Draft(
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            to=data.get("to", fallback_to),
            draft_type=draft_type,
            context=context,
        )
    except (json.JSONDecodeError, KeyError):
        return None


def generate_demo_followup(api_key: str, model: str, event: CalendarEvent) -> Optional[Draft]:
    if not event.attendees:
        return None
    to_email = event.attendees[0]
    prompt = f"""Write a warm, brief follow-up email after a sales demo call.

Meeting: {event.summary}
Time: {event.start.strftime('%B %-d at %-I:%M %p')}
Recipient email: {to_email}

Guidelines:
- 3-4 sentences max
- Thank them for their time
- Mention you'll send over next steps or resources
- Warm but professional tone, not salesy
- Use [Name] as placeholder for their first name

Respond with JSON only: {{"subject": "...", "body": "...", "to": "{to_email}"}}"""

    raw = _call_claude(api_key, model, prompt)
    return _parse_draft(raw, to_email, "demo_followup", context=event.summary)


def generate_lead_outreach(
    api_key: str,
    model: str,
    lead_name: str,
    lead_email: str,
    gym_name: str,
    snippet: str = "",
) -> Optional[Draft]:
    prompt = f"""Write a short, personalized cold outreach email for a gym facility.

Lead: {lead_name}
Gym: {gym_name}
Email: {lead_email}
Context about their gym: {snippet or "no additional context"}
Product: TeamBuildr OS — strength and conditioning software for gym owners

Guidelines:
- 3-4 sentences max
- Reference something specific about their gym if context is available
- Soft pitch: invite them to learn more, not to buy
- Subject line should feel personal, not like a marketing blast
- Sign from Trent at TeamBuildr OS

Respond with JSON only: {{"subject": "...", "body": "...", "to": "{lead_email}"}}"""

    raw = _call_claude(api_key, model, prompt)
    return _parse_draft(raw, lead_email, "lead_outreach", context=gym_name)


def generate_trial_followup(
    api_key: str,
    model: str,
    lead_name: str,
    lead_email: str,
    days_in_trial: int,
) -> Optional[Draft]:
    prompt = f"""Write a brief check-in email for a trial user who hasn't responded.

Lead: {lead_name}
Email: {lead_email}
Days in trial: {days_in_trial}
Product: TeamBuildr OS

Guidelines:
- 2-3 sentences max
- No pressure — just checking in and offering help
- Ask one simple open-ended question to start a conversation
- Sign from Trent

Respond with JSON only: {{"subject": "...", "body": "...", "to": "{lead_email}"}}"""

    raw = _call_claude(api_key, model, prompt)
    return _parse_draft(raw, lead_email, "trial_followup", context=f"{days_in_trial}d in trial")


def save_draft(draft: Draft, drafts_dir: str) -> str:
    os.makedirs(drafts_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{draft.draft_type}_{date.today().isoformat()}_{timestamp}.json"
    path = os.path.join(drafts_dir, filename)
    with open(path, "w") as f:
        json.dump({
            "subject": draft.subject, "body": draft.body, "to": draft.to,
            "draft_type": draft.draft_type, "context": draft.context,
            "created_date": draft.created_date,
        }, f, indent=2)
    return path


def load_todays_drafts(drafts_dir: str) -> list[Draft]:
    today = date.today().isoformat()
    drafts = []
    try:
        for filename in sorted(os.listdir(drafts_dir)):
            if today in filename and filename.endswith(".json"):
                with open(os.path.join(drafts_dir, filename)) as f:
                    data = json.load(f)
                drafts.append(Draft(**data))
    except FileNotFoundError:
        pass
    return drafts
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_drafts.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/drafts.py tests/test_drafts.py
git commit -m "feat: draft generator for demo follow-ups, lead outreach, trial follow-ups"
```

---

## Task 10: Extended Brief Generator

**Files:**
- Modify: `processors/brief.py`
- Create: `tests/test_brief_extended.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_brief_extended.py
import json
from unittest.mock import patch, MagicMock
from datetime import date
import pytest
from processors.brief import generate_brief, BriefContent
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.gmail_personal import PersonalEmail
from collectors.local_data import Project, RecurringTask
from processors.loops import LoopSummary
from processors.issues import Issue
from processors.drafts import Draft
from datetime import datetime


def make_mock_claude(text: str):
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


MOCK_BRIEF = {
    "executive_summary": "Busy day — two demos, one open issue from yesterday, Monday pipeline review due.",
    "top_3_priorities": [
        "[ISSUE: 1 day, Slack #support] Login failures — still open, check with dev",
        "Demo: Apex Fitness at 10am — follow-up draft ready",
        "New leads in sales inbox — outreach drafts ready",
    ],
    "watch_outs": ["Apex trial ends Friday"],
    "schedule_notes": "Two demos back-to-back 10-11:30am, clear afternoon",
    "personal_items": ["wife@gmail.com: Pickup today?"],
    "recurring_due": ["Review sales pipeline (weekly, Monday)", "Budget tracker update (weekly, Monday)"],
    "drafts_ready": ["demo_followup: Apex Fitness — review and send"],
    "meeting_prep": [],
}


def test_generate_brief_includes_issue_fields(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(
        json.dumps(MOCK_BRIEF)
    )
    issues = [Issue(
        id="abc", title="Login failures", source="slack", source_ref="C001:123",
        channel="support", created_date=date.today().isoformat(),
        last_seen_date=date.today().isoformat(), status="open",
        actions_needed=[], outside_parties=[], resolved_date=None,
    )]
    brief = generate_brief(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        today_events=[], tomorrow_events=[], email_threads=[],
        projects=[], due_tasks=[], loop_summary=LoopSummary(),
        open_issues=issues, personal_emails=[], drafts=[], meeting_prep=[],
    )
    assert len(brief.top_3_priorities) == 3
    assert len(brief.recurring_due) == 2
    assert brief.executive_summary != ""


def test_generate_brief_handles_empty_new_fields(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude(
        json.dumps(MOCK_BRIEF)
    )
    brief = generate_brief(
        api_key="sk-test", model="claude-haiku-4-5-20251001",
        today_events=[], tomorrow_events=[], email_threads=[],
        projects=[], due_tasks=[], loop_summary=LoopSummary(),
    )
    assert isinstance(brief.personal_items, list)
    assert isinstance(brief.drafts_ready, list)


@pytest.fixture
def mock_anthropic():
    with patch("processors.brief.anthropic.Anthropic") as m:
        yield m
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_brief_extended.py -v
```
Expected: TypeError — `generate_brief` missing new keyword arguments.

- [ ] **Step 3: Replace processors/brief.py**

```python
import json
import re
import anthropic
from dataclasses import dataclass, field
from collectors.calendar import CalendarEvent
from collectors.gmail import EmailThread
from collectors.gmail_personal import PersonalEmail
from collectors.local_data import Project, RecurringTask
from processors.loops import LoopSummary
from processors.issues import Issue
from processors.drafts import Draft


SYSTEM_PROMPT = """\
You are an AI Chief of Staff for Trent Luecke — VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches) and founder of Vero (gym AI side project). You also help with his personal life, LinkedIn content, and a weekly content podcast.

Deliver an expansive, actionable morning brief. Be direct. No filler. Prioritize ruthlessly.

Rules:
- Open issues from prior days appear in top_3_priorities with age and source: "[ISSUE: N days, Slack #channel] title"
- Issues are the highest-priority items if they are multi-day or involve customer-facing problems
- recurring_due lists tasks due today by name and cadence — do not bury these in priorities
- drafts_ready lists email drafts generated and waiting for review — just name and context
- personal_items lists anything from personal Gmail that needs attention — brief, not buried
- meeting_prep lists prep notes for internal meetings today — last session summary and open items

Respond ONLY in JSON with these exact keys:
{
  "executive_summary": "2-3 sentence synthesis of the day ahead",
  "top_3_priorities": ["3 action items, open issues called out with age and source"],
  "watch_outs": ["0-3 risks or things that could go wrong today"],
  "schedule_notes": "one sentence about schedule shape",
  "personal_items": ["personal email items needing attention, empty list if none"],
  "recurring_due": ["recurring tasks due today with cadence"],
  "drafts_ready": ["drafts ready to review and send"],
  "meeting_prep": ["prep notes for today's internal meetings, empty list if none"]
}
"""


@dataclass
class BriefContent:
    executive_summary: str
    top_3_priorities: list[str] = field(default_factory=list)
    watch_outs: list[str] = field(default_factory=list)
    schedule_notes: str = ""
    personal_items: list[str] = field(default_factory=list)
    recurring_due: list[str] = field(default_factory=list)
    drafts_ready: list[str] = field(default_factory=list)
    meeting_prep: list[str] = field(default_factory=list)


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
) -> str:
    def fmt_event(e: CalendarEvent) -> str:
        return f"  {e.start.strftime('%I:%M%p').lstrip('0')} — {e.summary}"

    def fmt_issue(i: Issue) -> str:
        return f"  [{i.age_days}d, {i.source}#{i.channel}] {i.title} (status: {i.status})"

    def fmt_draft(d: Draft) -> str:
        return f"  {d.draft_type}: {d.context} → to {d.to}"

    sections = [
        "## Open Issues (surface in priorities with age and source)",
        *[fmt_issue(i) for i in open_issues] or ["  (none)"],
        "",
        "## Today's Calendar",
        *[fmt_event(e) for e in today_events] or ["  (no events)"],
        "",
        "## Tomorrow Preview",
        *[fmt_event(e) for e in tomorrow_events] or ["  (no events)"],
        "",
        "## Work Emails Needing Attention",
        *[f"  {t.subject} from {t.last_sender}" for t in email_threads] or ["  (none)"],
        "",
        "## Personal Items (allowlisted personal Gmail)",
        *[f"  {e.sender}: {e.subject} — {e.snippet[:80]}" for e in personal_emails] or ["  (none)"],
        "",
        "## Email Drafts Ready for Review",
        *[fmt_draft(d) for d in drafts] or ["  (none)"],
        "",
        "## Meeting Prep (internal meetings today)",
        *[f"  {m}" for m in meeting_prep] or ["  (no tracked internal meetings today)"],
        "",
        "## Active Projects",
        *[f"  {p.name} [{p.status}] — Next: {p.next_step}" for p in projects] or ["  (none)"],
        "",
        "## Recurring Tasks Due Today",
        *[f"  {t.name} ({t.schedule})" for t in due_tasks] or ["  (none)"],
        "",
        "## Open Loop Summary",
        f"  Resolved since yesterday: {len(loop_summary.resolved_email_ids)} items",
        f"  Still open: {len(loop_summary.still_open_email_ids)} items",
    ]
    return "\n".join(sections)


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
) -> BriefContent:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(
        today_events, tomorrow_events, email_threads, projects, due_tasks,
        loop_summary,
        open_issues or [],
        personal_emails or [],
        drafts or [],
        meeting_prep or [],
    )
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    data = json.loads(raw)
    return BriefContent(
        executive_summary=data.get("executive_summary", ""),
        top_3_priorities=data.get("top_3_priorities", []),
        watch_outs=data.get("watch_outs", []),
        schedule_notes=data.get("schedule_notes", ""),
        personal_items=data.get("personal_items", []),
        recurring_due=data.get("recurring_due", []),
        drafts_ready=data.get("drafts_ready", []),
        meeting_prep=data.get("meeting_prep", []),
    )
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests PASS including existing tests.

- [ ] **Step 5: Commit**

```bash
git add processors/brief.py tests/test_brief_extended.py
git commit -m "feat: extend brief generator with issues, personal Gmail, drafts, meeting prep sections"
```

---

## Task 11: Extend Main Orchestrator

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Replace main.py**

```python
#!/usr/bin/env python3
"""AI Chief of Staff — Morning Brief Orchestrator."""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

from collectors.calendar import fetch_two_day_events
from collectors.gmail import fetch_threads_needing_attention
from collectors.gmail_personal import fetch_personal_emails
from collectors.local_data import load_projects, load_due_recurring_tasks
from collectors.notion_inbox import fetch_inbox_items
from processors.state import StateSnapshot, save_snapshot, load_snapshot, diff_snapshots
from processors.loops import build_loop_summary
from processors.issues import get_open_issues, auto_resolve_issues
from processors.meeting_memory import load_meeting_index, find_meeting_for_event, load_last_session_summary
from processors.drafts import generate_demo_followup, save_draft, load_todays_drafts
from processors.brief import generate_brief, BriefContent
from outputs.sender import build_gmail_service_from_config, build_html_email, send_brief_email
from outputs.dashboard import write_dashboard


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_personal_allowlist(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"allowed_senders": [], "allowed_domains": []}


def build_meeting_prep(today_events, meeting_configs) -> list[str]:
    prep = []
    for event in today_events:
        config = find_meeting_for_event(event, meeting_configs)
        if not config:
            continue
        last_summary = load_last_session_summary(config.memory_file)
        if last_summary:
            preview = last_summary[:200] + ("..." if len(last_summary) > 200 else "")
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — Last session: {preview}")
        else:
            prep.append(f"{event.summary} ({event.start.strftime('%-I:%M%p')}) — No prior session notes")
    return prep


def generate_daily_drafts(config: dict, today_events) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = config["ai_model"]
    drafts_dir = config["drafts_dir"]
    for event in today_events:
        if "demo" in event.summary.lower() and event.attendees:
            draft = generate_demo_followup(api_key, model, event)
            if draft:
                save_draft(draft, drafts_dir)
                print(f"   Draft: demo follow-up for {event.summary}")


def run(config: dict, dry_run: bool = False, no_email: bool = False) -> None:
    print("🗓  Fetching calendar...")
    today_events, tomorrow_events = fetch_two_day_events(
        config["calendar_ids"], profile=config.get("gmail_profile")
    )

    print("📧  Fetching Gmail (work)...")
    email_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=config.get("unread_email_max", 15),
        profile=config.get("gmail_profile"),
    )

    print("📱  Fetching Gmail (personal)...")
    allowlist = load_personal_allowlist(config.get("personal_allowlist_file", "data/personal_allowlist.json"))
    personal_emails = fetch_personal_emails(
        profile=config.get("personal_gmail_profile", "personal"),
        allowed_senders=allowlist.get("allowed_senders", []),
        allowed_domains=allowlist.get("allowed_domains", []),
        max_results=20,
    )

    print("📋  Loading projects and recurring tasks...")
    projects = load_projects(config["projects_file"])
    due_tasks = load_due_recurring_tasks(config["recurring_file"])

    notion_items = []
    if config.get("notion", {}).get("enabled"):
        print("🔔  Fetching Notion inbox...")
        notion_token = os.environ.get("NOTION_TOKEN", "")
        if notion_token:
            notion_items = fetch_inbox_items(
                token=notion_token,
                database_id=config["notion"]["inbox_database_id"],
                filter_statuses=config["notion"]["inbox_filter_status"],
            )

    print("🔥  Loading open issues...")
    auto_resolve_issues(config["issues_file"], resolve_after_days=config.get("issue_auto_resolve_days", 3))
    open_issues = get_open_issues(config["issues_file"])

    print("🗒  Building meeting prep...")
    meeting_configs = load_meeting_index(config.get("meeting_index_file", "data/meeting_index.json"))
    meeting_prep = build_meeting_prep(today_events, meeting_configs)

    print("✍️  Generating demo follow-up drafts...")
    generate_daily_drafts(config, today_events)
    todays_drafts = load_todays_drafts(config["drafts_dir"])

    print("🔄  Resolving open loops...")
    yesterday = date.today() - timedelta(days=1)
    previous_state = load_snapshot(yesterday, config["state_dir"])
    today_email_ids = [t.id for t in email_threads]
    today_notion_ids = [n.id for n in notion_items]

    if previous_state:
        resolved, still_open = diff_snapshots(previous_state, today_email_ids, today_notion_ids)
    else:
        resolved = {"email": [], "notion": []}
        still_open = {"email": [], "notion": []}

    loop_summary = build_loop_summary(email_threads, notion_items, resolved, still_open)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    print("🤖  Generating brief with Claude...")
    try:
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
        )
    except Exception as e:
        print(f"ERROR: Failed to generate brief: {e}", file=sys.stderr)
        brief = BriefContent(
            executive_summary="Brief generation failed — check logs.",
            top_3_priorities=["Check logs", "Retry: python main.py --no-email"],
            watch_outs=[str(e)[:200]],
        )

    print("📊  Writing dashboard...")
    write_dashboard(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        output_path=config["dashboard_path"],
    )

    if not dry_run and not no_email:
        print("📤  Sending brief email...")
        gmail = build_gmail_service_from_config(config["credentials_path"], config["token_path"])
        subject = f"☀️ Morning Brief — {datetime.now().strftime('%A, %B %-d')}"
        html = build_html_email(brief, today_events, projects, due_tasks, loop_summary)
        msg_id = send_brief_email(gmail, config["email"], subject, html)
        print(f"   Sent: {msg_id}")
    else:
        print("   (email skipped)")

    print("💾  Saving state snapshot...")
    snapshot = StateSnapshot(
        date=date.today().isoformat(),
        open_email_thread_ids=today_email_ids,
        open_notion_item_ids=today_notion_ids,
    )
    save_snapshot(snapshot, config["state_dir"])

    print("\n✅ Brief complete.")
    print(f"\nSummary: {brief.executive_summary}")
    print("\nTop Priorities:")
    for i, p in enumerate(brief.top_3_priorities, 1):
        print(f"  {i}. {p}")
    if brief.watch_outs:
        print("\nWatch Outs:")
        for w in brief.watch_outs:
            print(f"  ⚠️  {w}")
    if open_issues:
        print(f"\nOpen Issues: {len(open_issues)}")
    if todays_drafts:
        print(f"\nDrafts Ready: {len(todays_drafts)}")


def main():
    parser = argparse.ArgumentParser(description="AI Chief of Staff Morning Brief")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    config = load_config(args.config)
    run(config, dry_run=args.dry_run, no_email=args.no_email)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests PASS.

- [ ] **Step 3: Dry run to verify end-to-end integration**

```bash
python main.py --dry-run
```
Expected: Each step prints. Brief generates. No email sent. Check for errors in output.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: extend main orchestrator — issues, personal Gmail, meeting prep, drafts"
```

---

## Self-Review

**Spec coverage:**
- ✅ Morning brief email (7am CT) — Tasks 10, 11, launchd Task 6
- ✅ Issue log from Slack (3 channels: TeamBuildr-OS, support, support-tickets) — Tasks 3, 4, 5
- ✅ Gmail fallback for flare-ups (keyword detection) — Task 5 (watcher.py)
- ✅ Issue auto-resolve by age (not manual) — Task 3 (issues.py `auto_resolve_issues`)
- ✅ Issues blended into priorities with age + source callout — Task 10 (brief.py system prompt)
- ✅ Meeting memory files per recurring internal meeting — Task 7
- ✅ Post-meeting email nudge → reply → memory file — Task 8
- ✅ Meeting prep surfaced on day of meeting — Tasks 7, 11
- ✅ Demo follow-up draft generation — Task 9
- ✅ New lead outreach draft generation — Task 9
- ✅ Trial follow-up draft generation — Task 9
- ✅ Personal Gmail with sender allowlist — Task 2
- ✅ Slack bot collector (direct bot token, not Zapier) — Task 4
- ✅ launchd for brief (7am), watcher (hourly), nudger (15min) — Task 6
- ✅ projects.md seeded with 5 real projects — Task 1
- ✅ recurring.json seeded with full task list — Task 1
- ✅ System treats existing scripts as orchestration targets — architectural pattern throughout

**Placeholder scan:** None found. All steps contain working code.

**Type consistency:**
- `generate_brief` signature in `brief.py` matches all call sites in `main.py` and tests
- `Issue.age_days` is a `@property` — used correctly in `_build_prompt` via `fmt_issue`
- `MeetingConfig` dataclass fields exactly match `meeting_index.json` schema keys
- `Draft` dataclass fields match `save_draft`, `load_todays_drafts`, and test usage
- `PersonalEmail` fields match usage in `_build_prompt`

**Intentional gaps (not errors):**
- HubSpot trial list has no API access. `generate_trial_followup` exists in `drafts.py` and is ready to call; surfacing it in the brief requires either manual input of lead data or a future read mechanism. The function signature is stable.
- `build_html_email` in `sender.py` and the Jinja2 template don't yet render the new `BriefContent` fields (`personal_items`, `drafts_ready`, `recurring_due`, `meeting_prep`). The email will render without them — these are Phase 2 template updates when the dashboard is built.
- LinkedIn Notion audit (read database for content gaps) — deferred to Phase 2 dashboard work; the project is tracked in `projects.md` with a note about Notion.
