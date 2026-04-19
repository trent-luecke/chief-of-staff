# P0 — Cloud Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the daily brief from a local macOS launchd job to GitHub Actions using Google service account auth, so it runs unconditionally without the local machine.

**Architecture:** Replace `gws` CLI subprocess calls in `collectors/calendar.py` and `collectors/gmail.py` with `google-api-python-client` backed by a Google Workspace service account. Remove personal Gmail (not accessible via service account). Create a GitHub Actions scheduled workflow that checks out the repo, runs the brief, and commits `data/` changes back.

**Tech Stack:** `google-api-python-client>=2.0.0`, `google-auth>=2.0.0`, GitHub Actions (`ubuntu-latest`)

---

### Task 1: Update dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing import test**

```python
# In a temporary scratch file or pytest session — not committed
import google.oauth2.service_account
import googleapiclient.discovery
```

- [ ] **Step 2: Add dependencies to requirements.txt**

Open `requirements.txt`. Add after existing google lines (or at the end if not present):
```
google-api-python-client>=2.0.0
google-auth>=2.0.0
```

Remove this line if present:
```
google-auth-oauthlib
```

- [ ] **Step 3: Install and verify**

```bash
pip install -r requirements.txt
python -c "from google.oauth2 import service_account; from googleapiclient.discovery import build; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat(p0): add google-api-python-client dependency"
```

---

### Task 2: Rewrite `lib/google_auth.py` for service account

**Files:**
- Modify: `lib/google_auth.py`
- Create: `tests/test_google_auth.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_google_auth.py`:
```python
import json
import os
from unittest.mock import patch, MagicMock
import pytest
from lib.google_auth import get_service_account_credentials, build_gmail_service, build_calendar_service, GMAIL_SCOPES, CALENDAR_SCOPES

FAKE_SA_JSON = json.dumps({
    "type": "service_account",
    "project_id": "test",
    "private_key_id": "key1",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "chief-of-staff@test.iam.gserviceaccount.com",
    "client_id": "123",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
})


def test_gmail_scopes_defined():
    assert "https://www.googleapis.com/auth/gmail.readonly" in GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" in GMAIL_SCOPES


def test_calendar_scopes_defined():
    assert "https://www.googleapis.com/auth/calendar.readonly" in CALENDAR_SCOPES


def test_get_service_account_credentials_returns_delegated_creds():
    with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SA_JSON}):
        with patch("lib.google_auth.service_account.Credentials.from_service_account_info") as mock_sa:
            mock_creds = MagicMock()
            mock_sa.return_value = mock_creds
            mock_creds.with_subject.return_value = mock_creds
            result = get_service_account_credentials(GMAIL_SCOPES, "trent@teambuildr.com")
            mock_sa.assert_called_once()
            mock_creds.with_subject.assert_called_once_with("trent@teambuildr.com")
            assert result == mock_creds


def test_build_gmail_service_returns_service():
    with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SA_JSON}):
        with patch("lib.google_auth.get_service_account_credentials") as mock_creds:
            with patch("lib.google_auth.build") as mock_build:
                mock_build.return_value = MagicMock()
                result = build_gmail_service("trent@teambuildr.com")
                mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds.return_value)


def test_build_calendar_service_returns_service():
    with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": FAKE_SA_JSON}):
        with patch("lib.google_auth.get_service_account_credentials") as mock_creds:
            with patch("lib.google_auth.build") as mock_build:
                mock_build.return_value = MagicMock()
                result = build_calendar_service("trent@teambuildr.com")
                mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds.return_value)
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_google_auth.py -v
```
Expected: `ImportError` or `AttributeError` (functions don't exist yet)

- [ ] **Step 3: Replace `lib/google_auth.py`**

```python
import json
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_service_account_credentials(scopes: list[str], subject_email: str):
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    return creds.with_subject(subject_email)


def build_gmail_service(user_email: str):
    creds = get_service_account_credentials(GMAIL_SCOPES, user_email)
    return build("gmail", "v1", credentials=creds)


def build_calendar_service(user_email: str):
    creds = get_service_account_credentials(CALENDAR_SCOPES, user_email)
    return build("calendar", "v3", credentials=creds)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_google_auth.py -v
```
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add lib/google_auth.py tests/test_google_auth.py
git commit -m "feat(p0): replace OAuth with service account auth in google_auth"
```

---

### Task 3: Rewrite `collectors/calendar.py`

**Files:**
- Modify: `collectors/calendar.py`
- Modify: `tests/test_calendar.py`

- [ ] **Step 1: Rewrite `tests/test_calendar.py`**

```python
from unittest.mock import patch, MagicMock
from datetime import date, datetime
import pytest
from collectors.calendar import fetch_today_events, fetch_two_day_events, CalendarEvent

MOCK_EVENTS_RESPONSE = {
    "items": [
        {
            "id": "evt_001",
            "summary": "Demo: Apex Fitness",
            "start": {"dateTime": "2026-04-17T09:00:00-07:00"},
            "end": {"dateTime": "2026-04-17T10:00:00-07:00"},
            "attendees": [
                {"email": "contact@apexfitness.com"},
                {"email": "trent@teambuildr.com", "self": True},
            ],
            "description": "Product demo",
        },
        {
            "id": "evt_002",
            "summary": "All day event",
            "start": {"date": "2026-04-17"},
            "end": {"date": "2026-04-18"},
        },
    ]
}


@pytest.fixture
def mock_calendar_service():
    with patch("collectors.calendar._build_service") as mock:
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = MOCK_EVENTS_RESPONSE
        mock.return_value = service
        yield service


def test_fetch_today_events_returns_events(mock_calendar_service):
    events = fetch_today_events(
        calendar_id="primary", target_date=date(2026, 4, 17), user_email="trent@teambuildr.com"
    )
    assert len(events) == 1
    assert events[0].id == "evt_001"
    assert events[0].summary == "Demo: Apex Fitness"
    assert isinstance(events[0].start, datetime)


def test_fetch_today_events_filters_all_day(mock_calendar_service):
    events = fetch_today_events(
        calendar_id="primary", target_date=date(2026, 4, 17), user_email="trent@teambuildr.com"
    )
    assert "All day event" not in [e.summary for e in events]


def test_fetch_today_events_handles_api_error():
    with patch("collectors.calendar._build_service") as mock:
        mock.side_effect = Exception("API unavailable")
        events = fetch_today_events(
            calendar_id="primary", target_date=date(2026, 4, 17), user_email="trent@teambuildr.com"
        )
        assert events == []


def test_fetch_two_day_events_returns_sorted_tuple(mock_calendar_service):
    today_events, tomorrow_events = fetch_two_day_events(
        calendar_ids=["primary"], user_email="trent@teambuildr.com"
    )
    assert len(today_events) == 1
    assert len(tomorrow_events) == 1
    assert isinstance(today_events[0].start, datetime)
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_calendar.py -v
```
Expected: FAIL (functions still use subprocess)

- [ ] **Step 3: Rewrite `collectors/calendar.py`**

```python
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from dateutil.parser import parse as parse_dt

from lib.google_auth import build_calendar_service


@dataclass
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    description: str = ""
    attendees: list[str] = field(default_factory=list)


def _build_service(user_email: str):
    return build_calendar_service(user_email)


def fetch_today_events(
    calendar_id: str = "primary",
    target_date: Optional[date] = None,
    user_email: str = "",
) -> list[CalendarEvent]:
    if target_date is None:
        target_date = date.today()
    time_min = datetime.combine(target_date, datetime.min.time()).isoformat() + "Z"
    time_max = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

    try:
        service = _build_service(user_email)
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except Exception as e:
        print(f"WARNING: Calendar fetch failed: {e}", flush=True)
        return []

    events = []
    for item in result.get("items", []):
        start_raw = item.get("start", {})
        if "date" in start_raw and "dateTime" not in start_raw:
            continue
        try:
            events.append(
                CalendarEvent(
                    id=item["id"],
                    summary=item.get("summary", "(no title)"),
                    start=parse_dt(start_raw["dateTime"]),
                    end=parse_dt(item["end"]["dateTime"]),
                    description=item.get("description", ""),
                    attendees=[
                        a["email"] for a in item.get("attendees", []) if not a.get("self")
                    ],
                )
            )
        except (KeyError, ValueError):
            continue
    return events


def fetch_two_day_events(
    calendar_ids: list[str],
    user_email: str = "",
) -> tuple[list[CalendarEvent], list[CalendarEvent]]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_events, tomorrow_events = [], []
    for cal_id in calendar_ids:
        today_events.extend(fetch_today_events(cal_id, today, user_email))
        tomorrow_events.extend(fetch_today_events(cal_id, tomorrow, user_email))
    today_events.sort(key=lambda e: e.start)
    tomorrow_events.sort(key=lambda e: e.start)
    return today_events, tomorrow_events
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_calendar.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/calendar.py tests/test_calendar.py
git commit -m "feat(p0): replace gws CLI with Google Calendar API in calendar collector"
```

---

### Task 4: Rewrite `collectors/gmail.py`

**Files:**
- Modify: `collectors/gmail.py`
- Modify: `tests/test_gmail.py`

- [ ] **Step 1: Rewrite `tests/test_gmail.py`**

```python
from unittest.mock import patch, MagicMock
import pytest
from collectors.gmail import fetch_threads_needing_attention, EmailThread

MOCK_LIST_RESPONSE = {
    "threads": [{"id": "thread_001", "snippet": "Re: Contract renewal — sounds good"}]
}

MOCK_THREAD_RESPONSE = {
    "id": "thread_001",
    "messages": [
        {
            "id": "msg_a",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Contract renewal"},
                    {"name": "From", "value": "John Smith <john@example.com>"},
                    {"name": "Date", "value": "Thu, 16 Apr 2026 10:00:00 -0700"},
                ]
            },
            "internalDate": "1713279600000",
        }
    ],
}


@pytest.fixture
def mock_gmail_service():
    with patch("collectors.gmail._build_service") as mock:
        service = MagicMock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = MOCK_LIST_RESPONSE
        service.users.return_value.threads.return_value.get.return_value.execute.return_value = MOCK_THREAD_RESPONSE
        mock.return_value = service
        yield service


def test_fetch_threads_returns_email_thread(mock_gmail_service):
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert len(threads) == 1
    assert threads[0].id == "thread_001"
    assert threads[0].subject == "Contract renewal"
    assert threads[0].last_sender == "John Smith <john@example.com>"


def test_fetch_threads_empty_when_api_fails():
    with patch("collectors.gmail._build_service") as mock:
        mock.side_effect = Exception("API error")
        threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
        assert threads == []


def test_fetch_threads_needs_reply_when_last_sender_is_not_user(mock_gmail_service):
    threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
    assert threads[0].needs_reply is True


def test_fetch_threads_not_needs_reply_when_user_sent_last():
    with patch("collectors.gmail._build_service") as mock:
        service = MagicMock()
        service.users.return_value.threads.return_value.list.return_value.execute.return_value = {
            "threads": [{"id": "thread_002", "snippet": ""}]
        }
        service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
            "id": "thread_002",
            "messages": [
                {
                    "id": "msg_b",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Follow up"},
                            {"name": "From", "value": "Trent Luecke <trent@teambuildr.com>"},
                        ]
                    },
                    "internalDate": "1713279600000",
                }
            ],
        }
        mock.return_value = service
        threads = fetch_threads_needing_attention(user_email="trent@teambuildr.com", max_results=10)
        assert threads[0].needs_reply is False
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_gmail.py -v
```
Expected: FAIL

- [ ] **Step 3: Rewrite `collectors/gmail.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from lib.google_auth import build_gmail_service


@dataclass
class EmailThread:
    id: str
    subject: str
    last_sender: str
    snippet: str
    last_message_date: Optional[datetime]
    needs_reply: bool = True
    label: str = "unread"


def _build_service(user_email: str):
    return build_gmail_service(user_email)


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _parse_thread(thread_data: dict, user_email: str) -> Optional[EmailThread]:
    messages = thread_data.get("messages", [])
    if not messages:
        return None
    last_msg = messages[-1]
    headers = last_msg.get("payload", {}).get("headers", [])
    subject = _get_header(headers, "Subject") or "(no subject)"
    sender = _get_header(headers, "From")
    internal_date = last_msg.get("internalDate")
    date = None
    if internal_date:
        try:
            date = datetime.fromtimestamp(int(internal_date) / 1000)
        except (ValueError, OSError):
            pass
    needs_reply = user_email.lower() not in sender.lower()
    return EmailThread(
        id=thread_data["id"],
        subject=subject,
        last_sender=sender,
        snippet=thread_data.get("snippet", ""),
        last_message_date=date,
        needs_reply=needs_reply,
    )


def fetch_threads_needing_attention(
    user_email: str,
    max_results: int = 15,
    query: str = "is:unread OR is:starred -in:sent",
) -> list[EmailThread]:
    try:
        service = _build_service(user_email)
        list_data = service.users().threads().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
    except Exception as e:
        print(f"WARNING: Gmail fetch failed: {e}", flush=True)
        return []

    threads = []
    for t in list_data.get("threads", []):
        try:
            thread_data = service.users().threads().get(
                userId="me",
                id=t["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
        except Exception:
            continue
        thread_data.setdefault("snippet", t.get("snippet", ""))
        parsed = _parse_thread(thread_data, user_email)
        if parsed:
            threads.append(parsed)
    return threads
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_gmail.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add collectors/gmail.py tests/test_gmail.py
git commit -m "feat(p0): replace gws CLI with Gmail API in gmail collector"
```

---

### Task 5: Update `outputs/sender.py`

**Files:**
- Modify: `outputs/sender.py`

The only change is removing the `build_gmail_service_from_config` helper and its OAuth imports — `send_brief_email` and `build_html_email` are unchanged. The gmail service will be built in `main.py` and passed in directly.

- [ ] **Step 1: Run existing sender tests to establish baseline**

```bash
pytest tests/test_sender.py -v
```
Expected: All PASS (tests don't use `build_gmail_service_from_config`)

- [ ] **Step 2: Update `outputs/sender.py`**

Replace the file contents:
```python
import base64
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, FileSystemLoader

from collectors.calendar import CalendarEvent
from collectors.local_data import Project, RecurringTask
from processors.brief import BriefContent
from processors.loops import LoopSummary


def build_html_email(
    brief: BriefContent,
    today_events: list[CalendarEvent],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    template_dir: str = "templates",
) -> str:
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("morning_brief.html")
    now = datetime.now()
    return template.render(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        date_str=now.strftime("%A, %B ") + str(now.day),
        generated_at=now.strftime("%I:%M %p").lstrip("0"),
    )


def send_brief_email(
    gmail_service,
    to_email: str,
    subject: str,
    html_body: str,
    plain_text: str = "Morning brief — view in an HTML-capable email client.",
) -> str:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = to_email
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return result.get("id", "")
```

- [ ] **Step 3: Run sender tests to verify still pass**

```bash
pytest tests/test_sender.py -v
```
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add outputs/sender.py
git commit -m "feat(p0): remove OAuth-based build_gmail_service_from_config from sender"
```

---

### Task 6: Remove personal Gmail

**Files:**
- Delete: `collectors/gmail_personal.py`
- Delete: `tests/test_gmail_personal.py`
- Modify: `processors/brief.py` (remove PersonalEmail import and parameter)
- Modify: `main.py` (remove fetch_personal_emails and personal_emails)

- [ ] **Step 1: Delete files**

```bash
rm collectors/gmail_personal.py tests/test_gmail_personal.py
```

- [ ] **Step 2: Update `processors/brief.py`**

Remove these lines from the top of the file:
```python
from collectors.gmail_personal import PersonalEmail
```

In `_build_prompt`, remove `personal_emails: list[PersonalEmail]` from the signature:
```python
def _build_prompt(
    today_events: list[CalendarEvent],
    tomorrow_events: list[CalendarEvent],
    email_threads: list[EmailThread],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    open_issues: list[Issue],
    drafts: list[Draft],
    meeting_prep: list[str],
    inbox_text: str,
    attention_leads: list[PipelineLead] = None,
    gym_scout_leads: list[GymScoutLead] = None,
    people_context: str = "",
) -> str:
```

Remove the `## Personal Items` section from the `sections` list in `_build_prompt`:
```python
# Remove these two lines:
"## Personal Items (allowlisted personal Gmail)",
*([f"  {e.sender}: {e.subject} — {e.snippet[:80]}" for e in personal_emails] or ["  (none)"]),
"",
```

In `generate_brief`, remove `personal_emails: list[PersonalEmail] = None` from the signature and remove `personal_emails or []` from the `_build_prompt` call.

Full updated `generate_brief` signature:
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
    drafts: list[Draft] = None,
    meeting_prep: list[str] = None,
    inbox_text: str = "",
    attention_leads: list[PipelineLead] = None,
    gym_scout_leads: list[GymScoutLead] = None,
    people_context: str = "",
) -> BriefContent:
```

Full updated `_build_prompt` call inside `generate_brief`:
```python
prompt = _build_prompt(
    today_events, tomorrow_events, email_threads, projects, due_tasks,
    loop_summary,
    open_issues or [],
    drafts or [],
    meeting_prep or [],
    inbox_text or "",
    attention_leads=attention_leads or [],
    gym_scout_leads=gym_scout_leads or [],
    people_context=people_context,
)
```

- [ ] **Step 3: Run brief tests to verify still pass**

```bash
pytest tests/test_brief.py tests/test_brief_extended.py -v
```
Expected: All PASS (tests don't use personal_emails in assertions)

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "feat(p0): remove personal Gmail collector and brief integration"
```

---

### Task 7: Update `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Apply all changes to `main.py`**

Make these four changes:

**a) Replace imports at the top** — remove personal Gmail and OAuth-based sender import, add service account import:

Remove:
```python
from collectors.gmail_personal import fetch_personal_emails
```

Change:
```python
from outputs.sender import build_gmail_service_from_config, build_html_email, send_brief_email
```
To:
```python
from outputs.sender import build_html_email, send_brief_email
from lib.google_auth import build_gmail_service
```

**b) Remove `load_personal_allowlist` function** (lines 37–42) and **the personal Gmail fetch block** (lines 101–107):

Delete:
```python
def load_personal_allowlist(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"allowed_senders": [], "allowed_domains": []}
```

Delete:
```python
    print("📱  Fetching Gmail (personal)...")
    allowlist = load_personal_allowlist(config.get("personal_allowlist_file", "data/personal_allowlist.json"))
    personal_emails = fetch_personal_emails(
        profile=config.get("personal_gmail_profile", "personal"),
        allowed_senders=allowlist.get("allowed_senders", []),
        allowed_domains=allowlist.get("allowed_domains", []),
        max_results=20,
    )
```

**c) Update `fetch_two_day_events` and `fetch_threads_needing_attention` calls** — replace `profile=` with `user_email=`:

```python
    today_events, tomorrow_events = fetch_two_day_events(
        config["calendar_ids"], user_email=config["email"]
    )
```

```python
    email_threads = fetch_threads_needing_attention(
        user_email=config["email"],
        max_results=config.get("unread_email_max", 15),
    )
```

**d) Replace OAuth gmail service with service account** — in the send block:

Replace:
```python
        gmail = build_gmail_service_from_config(config["credentials_path"], config["token_path"])
```
With:
```python
        gmail = build_gmail_service(config["email"])
```

**e) Remove `personal_emails=personal_emails` from `generate_brief()` call** (it was already removed in Task 6's brief.py changes, so ensure it's not passed here either).

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/test_notion_inbox.py
```
Expected: All PASS (notion_inbox skipped as it requires network)

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(p0): update main.py to use service account auth, remove personal Gmail"
```

---

### Task 8: Update `config.json` and `.gitignore`

**Files:**
- Modify: `config.json`
- Modify: `.gitignore`

- [ ] **Step 1: Update `config.json`**

Remove these keys:
- `"credentials_path"`
- `"token_path"`
- `"personal_gmail_profile"`
- `"personal_allowlist_file"`
- `"include_personal_gmail"`
- `"gmail_profile"` (gws profile, no longer used)

The updated config should look like this (preserve all other keys):
```json
{
  "email": "trent@teambuildr.com",
  "people_dir": "data/people",
  "brief_subject_prefix": "☀️ Morning Brief",
  "calendar_ids": ["primary"],
  "unread_email_max": 15,
  "starred_email_max": 10,
  "ai_model": "claude-sonnet-4-6",
  "state_dir": "data/state",
  "projects_file": "data/projects.md",
  "recurring_file": "data/recurring.json",
  "dashboard_path": "output/dashboard.html",
  "notion": {
    "enabled": false,
    "inbox_database_id": "",
    "inbox_filter_status": ["Inbox", "Processing"]
  },
  "slack_channels": ["TeamBuildr-OS", "support", "support-tickets"],
  "meeting_index_file": "data/meeting_index.json",
  "issues_file": "data/issues.json",
  "pending_nudges_file": "data/pending_nudges.json",
  "drafts_dir": "data/drafts",
  "issue_auto_resolve_days": 3,
  "inbox_file": "~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/chief-of-staff-inbox.md",
  "pipeline": {
    "enabled": true,
    "cache_path": "data/pipeline_cache.json",
    "trial_followup_after_days": 5,
    "stale_after_days": 14,
    "cache_stale_warn_days": 7
  },
  "gym_scout": {
    "enabled": true,
    "results_csv": "/Users/trentluecke/dev/Claude-Projects/Gym_Scout/gym_scout_results.csv",
    "lookback_days": 7
  }
}
```

- [ ] **Step 2: Update `.gitignore`**

Remove `data/state/` from `.gitignore` (state snapshots must persist between Actions runs via git):

Current line to remove:
```
data/state/
```

Add to ensure drafts and archive are not committed (optional noise):
```
data/drafts/
```

Keep `credentials/` gitignored — service account JSON goes in GitHub Secrets, not the repo.

- [ ] **Step 3: Stage existing state files**

```bash
git add data/state/ 2>/dev/null || true
git status
```

- [ ] **Step 4: Commit**

```bash
git add config.json .gitignore
git commit -m "feat(p0): remove OAuth config keys, un-ignore data/state for git persistence"
```

---

### Task 9: Create GitHub Actions workflow

**Files:**
- Create: `.github/workflows/brief.yml`

- [ ] **Step 1: Create directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Create `.github/workflows/brief.yml`**

```yaml
name: Daily Brief

on:
  schedule:
    # 7am CDT (UTC-5, Apr-Oct). Change to "0 13 * * *" in November for CST (UTC-6).
    - cron: "0 12 * * *"
  workflow_dispatch:

jobs:
  run-brief:
    runs-on: ubuntu-latest
    env:
      TZ: America/Chicago

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run brief
        env:
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
        run: python main.py

      - name: Persist data
        run: |
          git config user.name "chief-of-staff[bot]"
          git config user.email "noreply@github.com"
          git add data/
          git diff --cached --quiet || git commit -m "chore: daily data update $(date +%Y-%m-%d)"
          git push
```

- [ ] **Step 3: Add GitHub Secrets**

In the GitHub repo → Settings → Secrets and variables → Actions, add:

| Name | Value |
|------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Contents of service account key JSON file |
| `ANTHROPIC_API_KEY` | Value from local `.env` |
| `SLACK_BOT_TOKEN` | Value from local `.env` |

- [ ] **Step 4: Commit workflow**

```bash
git add .github/workflows/brief.yml
git commit -m "feat(p0): add GitHub Actions scheduled workflow for daily brief"
```

---

### Task 10: End-to-end verification

- [ ] **Step 1: Run full test suite locally**

```bash
pytest tests/ -v --ignore=tests/test_notion_inbox.py
```
Expected: All PASS

- [ ] **Step 2: Dry-run locally with service account**

Set `GOOGLE_SERVICE_ACCOUNT_JSON` in your local environment (copy the JSON content), then:

```bash
GOOGLE_SERVICE_ACCOUNT_JSON='<paste json here>' python main.py --no-email
```
Expected: Brief generates without error, no email sent

- [ ] **Step 3: Trigger manual Actions run**

Push all commits to the remote branch, then go to GitHub → Actions → Daily Brief → Run workflow.

Expected: Workflow succeeds, brief email arrives, a `chore: daily data update` commit appears in the repo

- [ ] **Step 4: Final commit**

```bash
git push
```
