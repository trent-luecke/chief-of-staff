# Meeting Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a Telegram pre-meeting brief 20 minutes before qualifying meetings — bullet-list for external calls/demos, structured KPI report for Dept Heads, and recap+open-loops format for recurring internal meetings (Marketing Sync, Luke/Trent).

**Architecture:** `processors/meeting_prep.py` handles classification, context assembly, and the Claude call. `nudger.py` is extended with a pre-meeting check loop that runs alongside the existing post-meeting nudge logic. State is tracked in `data/meeting_preps.json` (keyed on `{event_id}_{date}`) so recurring meetings get a fresh prep each occurrence but never get double-sent within the same run window.

**Tech Stack:** Python 3.11, Anthropic SDK (`anthropic`), existing `collectors/calendar.py` (`CalendarEvent`), Google Sheets API v4 (`google-api-python-client`), `data/pipeline_cache.json`, `data/memory/observations.jsonl`, `data/people/` files, `data/projects.md`, `data/captures.md`, `lib/telegram.py`.

**Google Sheets layout (confirmed by inspection):**
- Sales sheet ID: `1pOUxLMX2H48miMvEbgqOXq1C0VHkGm-XXW2VCodQfU0` — one tab per month named `"April 2026"`, `"March 2026"`, etc. Row 3 = headers (Date, Sales, Type, Total Sale, Customer Name, Salesperson…). Rows 4+ = sale entries where col A has a date (M/D/YYYY) and col D has the dollar total (e.g. `"$1,800.00"`). Stop at the first row with no date in col A.
- Demos sheet ID: `1iaMVUEuslDLVBqUIydPna-LjKOaDpqdDn5O0oLT1HjQ` — same tab-per-month naming. Row 1 = headers (Event ID, Date, Event Title, Salesperson, Attendees). Rows 2+ = one row per demo.

**Prerequisites (already complete):**
- Google Sheets API enabled in GCP project 859502323558
- `scripts/authorize.py` updated with `spreadsheets.readonly` scope
- OAuth re-run; new token (with Sheets scope) saved to `credentials/google_oauth.json` and updated in GitHub Secret `GOOGLE_OAUTH_JSON` and `.env`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `collectors/sheets.py` | Sheets API auth + MTD sales/demos fetchers |
| Create | `processors/meeting_prep.py` | Classification, context builders, Claude call, state I/O |
| Create | `tests/test_meeting_prep.py` | All unit tests for meeting_prep and sheets collector |
| Modify | `lib/google_auth.py` | Add `build_sheets_service()` |
| Modify | `nudger.py` | Add pre-meeting prep loop before post-meeting nudge loop |
| Modify | `config.json` | Add `meeting_prep` config block |

---

## Task 1: Config block + meeting classification

**Files:**
- Modify: `config.json`
- Create: `processors/meeting_prep.py`
- Create: `tests/test_meeting_prep.py`

### What `classify_meeting` must do

Returns one of `"external"`, `"dept_heads"`, `"recurring_internal"`, or `None` (skip).

Priority order:
1. If title matches `dept_heads_patterns` → `"dept_heads"`
2. If title matches `recurring_internal_patterns` → `"recurring_internal"`
3. If it's a work meeting (using `nudger.is_work_meeting`) AND (has an external keyword OR has a non-teambuildr.com attendee) → `"external"`
4. Otherwise → `None`

External keywords: `{"demo", "reconnect", "intro", "pitch", "walkthrough", "onboarding", "call"}`.
A non-teambuildr attendee means any attendee email that does NOT contain `"teambuildr.com"`.

- [ ] **Step 1: Add `meeting_prep` block to `config.json`**

Open `config.json` and add this block before the closing `}`:

```json
  "meeting_prep": {
    "enabled": true,
    "prep_window_minutes": 20,
    "dept_heads_patterns": ["department heads", "dept heads"],
    "recurring_internal_patterns": ["marketing sync", "os weekly", "luke / trent", "luke/trent"],
    "preps_state_file": "data/meeting_preps.json",
    "sheets": {
      "sales_spreadsheet_id": "1pOUxLMX2H48miMvEbgqOXq1C0VHkGm-XXW2VCodQfU0",
      "demos_spreadsheet_id": "1iaMVUEuslDLVBqUIydPna-LjKOaDpqdDn5O0oLT1HjQ"
    }
  }
```

- [ ] **Step 2: Write failing tests for `classify_meeting`**

Create `tests/test_meeting_prep.py`:

```python
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
    # No external keyword, all teambuildr attendees
    assert classify_meeting(
        _event("TeamBuildr Standup", attendees=["team@teambuildr.com"]),
        BASE_CONFIG
    ) is None

def test_dept_heads_takes_priority_over_external():
    # Has "demo" keyword but should still be dept_heads
    assert classify_meeting(_event("Department Heads Demo Review"), BASE_CONFIG) == "dept_heads"
```

- [ ] **Step 3: Run failing tests**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
.venv/bin/pytest tests/test_meeting_prep.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` or `ImportError` — `meeting_prep` doesn't exist yet.

- [ ] **Step 4: Implement `classify_meeting` in `processors/meeting_prep.py`**

```python
"""Pre-meeting prep: classification, context assembly, Claude call, state I/O."""

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

import anthropic
from collectors.calendar import CalendarEvent

EXTERNAL_KEYWORDS = {"demo", "reconnect", "intro", "pitch", "walkthrough", "onboarding", "call"}


def classify_meeting(event: CalendarEvent, config: dict) -> Optional[str]:
    """Return meeting prep type or None if this meeting should be skipped."""
    title = event.summary.lower()
    prep_cfg = config.get("meeting_prep", {})

    for pattern in prep_cfg.get("dept_heads_patterns", []):
        if pattern.lower() in title:
            return "dept_heads"

    for pattern in prep_cfg.get("recurring_internal_patterns", []):
        if pattern.lower() in title:
            return "recurring_internal"

    # Personal/blocked events — skip
    PERSONAL_KEYWORDS = {
        "haircut", "doctor", "dentist", "gym", "workout", "therapy",
        "appointment", "birthday", "anniversary", "vacation", "lunch",
        "dinner", "blocked", "focus time", "deep work", "no meetings", "ooo",
    }
    if any(kw in title for kw in PERSONAL_KEYWORDS):
        return None

    has_external_keyword = any(kw in title for kw in EXTERNAL_KEYWORDS)
    has_external_attendee = any(
        "teambuildr.com" not in a.lower() for a in event.attendees
    )

    if event.attendees and (has_external_keyword or has_external_attendee):
        return "external"
    if not event.attendees and has_external_keyword:
        return "external"

    return None
```

- [ ] **Step 5: Run tests — expect pass**

```bash
.venv/bin/pytest tests/test_meeting_prep.py -v
```

Expected: All 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add config.json processors/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(prep): meeting classification + config block"
```

---

## Task 2: Google Sheets collector

**Files:**
- Modify: `lib/google_auth.py`
- Create: `collectors/sheets.py`
- Modify: `tests/test_meeting_prep.py`

### What this builds

`build_sheets_service()` in `lib/google_auth.py` — mirrors the existing `build_gmail_service()` pattern.

`collectors/sheets.py` exposes:
- `month_label(offset=0)` — returns `"April 2026"` (offset=0) or `"March 2026"` (offset=-1)
- `fetch_sales_mtd(service, spreadsheet_id, month_label)` → `dict` with keys `count`, `revenue` (float), `entries` (list of dicts with date/customer/salesperson/total)
- `fetch_demos_mtd(service, spreadsheet_id, month_label)` → `dict` with keys `count`, `entries` (list of dicts with date/title/salesperson)

Sales parsing: skip rows where col A (index 0) is empty or doesn't contain `/`. Strip `$` and `,` from col D (index 3) to parse revenue float.

Demos parsing: skip row 0 (header). Each remaining non-empty row is one demo.

Both functions return `{"count": 0, "revenue": 0.0, "entries": []}` / `{"count": 0, "entries": []}` if the tab doesn't exist or the API call fails — non-fatal.

- [ ] **Step 1: Add `build_sheets_service` to `lib/google_auth.py`**

Read `lib/google_auth.py` first to confirm the exact pattern used for `build_gmail_service`, then add after the last `build_*_service` function:

```python
def build_sheets_service(user_email: str = ""):
    creds = _get_credentials()
    return build("sheets", "v4", credentials=creds)
```

(Use whatever internal credential helper `build_gmail_service` uses — mirror it exactly.)

- [ ] **Step 2: Write failing tests for `month_label` and `fetch_sales_mtd`**

Append to `tests/test_meeting_prep.py`:

```python
from collectors.sheets import month_label, fetch_sales_mtd, fetch_demos_mtd
from unittest.mock import MagicMock, patch
from datetime import date

def test_month_label_current():
    label = month_label(0)
    today = date.today()
    expected = today.strftime("%B %Y")
    assert label == expected

def test_month_label_prior():
    label = month_label(-1)
    today = date.today()
    # prior month
    if today.month == 1:
        expected_year = today.year - 1
        expected_month = 12
    else:
        expected_year = today.year
        expected_month = today.month - 1
    from datetime import date as d
    expected = d(expected_year, expected_month, 1).strftime("%B %Y")
    assert label == expected

def test_fetch_sales_mtd_parses_rows():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.return_value = {
        "values": [
            ["`"],
            ["TeamBuildr OS Sales"],
            ["Date", "Sales", "Type", "Total Sale", "Customer Name", "Salesperson"],
            ["4/16/2026", "$200", "MONTHLY", "$1,800.00", "GRIT Athlete", "Trent"],
            ["4/28/2026", "$2,150", "ANNUAL", "$2,150.00", "Alapa Performance", "Trent"],
            [],
        ]
    }
    result = fetch_sales_mtd(mock_service, "fake-id", "April 2026")
    assert result["count"] == 2
    assert result["revenue"] == 3950.0
    assert result["entries"][0]["customer"] == "GRIT Athlete"

def test_fetch_sales_mtd_missing_tab_returns_empty():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.side_effect = Exception("Tab not found")
    result = fetch_sales_mtd(mock_service, "fake-id", "April 2026")
    assert result == {"count": 0, "revenue": 0.0, "entries": []}

def test_fetch_demos_mtd_parses_rows():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.return_value = {
        "values": [
            ["Event ID", "Date", "Event Title", "Salesperson", "Attendees"],
            ["abc123", "2026-04-01", "Demo with Mike", "Trent", "mike@apex.co"],
            ["def456", "2026-04-07", "Demo with Ben", "Luke Martin", "ben@adaptfs.com"],
        ]
    }
    result = fetch_demos_mtd(mock_service, "fake-id", "April 2026")
    assert result["count"] == 2
    assert result["entries"][0]["salesperson"] == "Trent"

def test_fetch_demos_mtd_missing_tab_returns_empty():
    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.side_effect = Exception("Tab not found")
    result = fetch_demos_mtd(mock_service, "fake-id", "April 2026")
    assert result == {"count": 0, "entries": []}
```

- [ ] **Step 3: Run — expect failures**

```bash
.venv/bin/pytest tests/test_meeting_prep.py::test_month_label_current tests/test_meeting_prep.py::test_fetch_sales_mtd_parses_rows -v
```

Expected: `ImportError` — `collectors/sheets.py` doesn't exist yet.

- [ ] **Step 4: Implement `collectors/sheets.py`**

```python
"""Google Sheets data fetcher for Dept Heads KPI context."""

import re
from datetime import date, datetime
from typing import Optional


def month_label(offset: int = 0) -> str:
    """Return a tab name like 'April 2026'. offset=-1 gives prior month."""
    today = date.today()
    month = today.month + offset
    year = today.year
    if month <= 0:
        month += 12
        year -= 1
    elif month > 12:
        month -= 12
        year += 1
    return datetime(year, month, 1).strftime("%B %Y")


def _parse_dollar(val: str) -> float:
    try:
        return float(re.sub(r"[$,]", "", val.strip()))
    except (ValueError, AttributeError):
        return 0.0


def fetch_sales_mtd(service, spreadsheet_id: str, tab_label: str) -> dict:
    """Fetch OS sales entries from the named monthly tab."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_label}'!A1:F60",
        ).execute()
    except Exception:
        return {"count": 0, "revenue": 0.0, "entries": []}

    rows = result.get("values", [])
    entries = []
    for row in rows:
        if not row:
            continue
        date_val = row[0] if len(row) > 0 else ""
        if "/" not in str(date_val):
            continue
        total = _parse_dollar(row[3]) if len(row) > 3 else 0.0
        entries.append({
            "date": date_val,
            "total": total,
            "customer": row[4] if len(row) > 4 else "",
            "salesperson": row[5] if len(row) > 5 else "",
            "sale_type": row[2] if len(row) > 2 else "",
        })

    revenue = sum(e["total"] for e in entries)
    return {"count": len(entries), "revenue": revenue, "entries": entries}


def fetch_demos_mtd(service, spreadsheet_id: str, tab_label: str) -> dict:
    """Fetch demo entries from the named monthly tab."""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_label}'!A1:E60",
        ).execute()
    except Exception:
        return {"count": 0, "entries": []}

    rows = result.get("values", [])
    entries = []
    for row in rows[1:]:  # skip header row
        if not row or not row[0]:
            continue
        entries.append({
            "date": row[1] if len(row) > 1 else "",
            "title": row[2] if len(row) > 2 else "",
            "salesperson": row[3] if len(row) > 3 else "",
        })

    return {"count": len(entries), "entries": entries}
```

- [ ] **Step 5: Run — expect pass**

```bash
.venv/bin/pytest tests/test_meeting_prep.py -v
```

Expected: All tests pass including new sheets tests.

- [ ] **Step 6: Smoke test against live sheets**

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, ".")
from lib.google_auth import build_sheets_service
from collectors.sheets import month_label, fetch_sales_mtd, fetch_demos_mtd

svc = build_sheets_service()
label = month_label(0)
print("Current month:", label)

sales = fetch_sales_mtd(svc, "1pOUxLMX2H48miMvEbgqOXq1C0VHkGm-XXW2VCodQfU0", label)
print(f"Sales MTD: {sales['count']} deals, ${sales['revenue']:,.0f}")
for e in sales["entries"]:
    print(f"  {e['date']} — {e['customer']} ({e['salesperson']}) ${e['total']:,.0f}")

demos = fetch_demos_mtd(svc, "1iaMVUEuslDLVBqUIydPna-LjKOaDpqdDn5O0oLT1HjQ", label)
print(f"Demos MTD: {demos['count']}")
for e in demos["entries"]:
    print(f"  {e['date']} — {e['title']} ({e['salesperson']})")
EOF
```

Expected: Prints April 2026 data matching what you see in the sheets.

- [ ] **Step 7: Commit**

```bash
git add lib/google_auth.py collectors/sheets.py tests/test_meeting_prep.py
git commit -m "feat(prep): Google Sheets collector for sales + demos MTD"
```

---

## Task 3: State management

State is stored in `data/meeting_preps.json` as `{"sent_keys": ["event_id_2026-04-30", ...]}`.
The key format is `{event.id}_{date.today().isoformat()}` — unique per event per calendar day, so recurring meetings get fresh prep each week.
On save, keys older than 7 days are pruned.

**Files:**
- Modify: `processors/meeting_prep.py`
- Modify: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write failing tests for state functions**

Append to `tests/test_meeting_prep.py`:

```python
import json
from datetime import date, timedelta
from processors.meeting_prep import make_prep_key, load_prep_state, save_prep_state


def test_make_prep_key():
    event = _event("Luke / Trent")
    event.id = "abc123"
    key = make_prep_key(event)
    assert key == f"abc123_{date.today().isoformat()}"


def test_load_prep_state_missing_file():
    assert load_prep_state("/nonexistent/path.json") == set()


def test_load_prep_state_corrupt_file(tmp_path):
    p = tmp_path / "preps.json"
    p.write_text("not json")
    assert load_prep_state(str(p)) == set()


def test_save_and_load_roundtrip(tmp_path):
    p = str(tmp_path / "preps.json")
    keys = {f"event1_{date.today().isoformat()}", f"event2_{date.today().isoformat()}"}
    save_prep_state(keys, p)
    assert load_prep_state(p) == keys


def test_save_prunes_old_keys(tmp_path):
    p = str(tmp_path / "preps.json")
    old_date = (date.today() - timedelta(days=8)).isoformat()
    old_key = f"old_event_{old_date}"
    today_key = f"new_event_{date.today().isoformat()}"
    save_prep_state({old_key, today_key}, p)
    loaded = load_prep_state(p)
    assert today_key in loaded
    assert old_key not in loaded
```

- [ ] **Step 2: Run — expect failures**

```bash
.venv/bin/pytest tests/test_meeting_prep.py::test_make_prep_key tests/test_meeting_prep.py::test_load_prep_state_missing_file tests/test_meeting_prep.py::test_save_and_load_roundtrip tests/test_meeting_prep.py::test_save_prunes_old_keys -v
```

Expected: `ImportError` on the new functions.

- [ ] **Step 3: Implement state functions in `processors/meeting_prep.py`**

Append after `classify_meeting`:

```python
def make_prep_key(event: CalendarEvent) -> str:
    return f"{event.id}_{date.today().isoformat()}"


def load_prep_state(path: str) -> set:
    try:
        with open(path) as f:
            data = json.load(f)
        return set(data.get("sent_keys", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_prep_state(sent_keys: set, path: str) -> None:
    cutoff = date.today() - timedelta(days=7)
    def _key_date(k: str) -> date:
        try:
            return date.fromisoformat(k.rsplit("_", 1)[-1])
        except ValueError:
            return date.today()
    recent = {k for k in sent_keys if _key_date(k) >= cutoff}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({"sent_keys": sorted(recent)}, f, indent=2)
```

- [ ] **Step 4: Run — expect pass**

```bash
.venv/bin/pytest tests/test_meeting_prep.py -v
```

Expected: All state tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(prep): prep state management (load/save/key)"
```

---

## Task 3: External meeting context assembly

`build_external_context()` returns a string with three sections (each omitted if empty):
1. **Contact Background** — contents of the matching people file (first 800 chars)
2. **Pipeline Record** — matching lead from `pipeline_cache.json`
3. **Recent Context** — last 5 observations from `observations.jsonl` that mention any name token from the meeting title or attendee emails

Name extraction: split meeting title and attendee email local parts on `[-_.\s]`, lowercase, drop tokens under 3 chars.

**Files:**
- Modify: `processors/meeting_prep.py`
- Modify: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_meeting_prep.py`:

```python
import os, json
from processors.meeting_prep import build_external_context


def test_build_external_context_people_match(tmp_path):
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    (people_dir / "mike-woodby.md").write_text("Mike Woodby — Apex Holland coach.")
    config = {
        "people_dir": str(people_dir),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Mike Woodby: OS Demo", attendees=["mike@apexholland.co"])
    result = build_external_context(event, config)
    assert "Mike Woodby" in result
    assert "Apex Holland" in result


def test_build_external_context_pipeline_match(tmp_path):
    pipeline = {"leads": [{"name": "Apex Holland", "status": "In-Trial", "contact": "Mike Woodby", "email": "mike@apexholland.co", "days_since_contact": 10, "estimated_value": 2000, "stale": False, "priority": "High", "last_contacted": "2026-04-20", "source": None}]}
    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline))
    config = {
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(pipeline_path)},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Apex Holland Demo", attendees=["mike@apexholland.co"])
    result = build_external_context(event, config)
    assert "In-Trial" in result or "Apex Holland" in result


def test_build_external_context_empty_when_no_data(tmp_path):
    config = {
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Unknown Person Demo")
    result = build_external_context(event, config)
    # Should not crash; returns whatever it can (may be empty string)
    assert isinstance(result, str)
```

- [ ] **Step 2: Run — expect failures**

```bash
.venv/bin/pytest tests/test_meeting_prep.py::test_build_external_context_people_match tests/test_meeting_prep.py::test_build_external_context_pipeline_match tests/test_meeting_prep.py::test_build_external_context_empty_when_no_data -v
```

Expected: `ImportError` on `build_external_context`.

- [ ] **Step 3: Implement `build_external_context` in `processors/meeting_prep.py`**

Append after `save_prep_state`:

```python
def _name_tokens(text: str) -> list[str]:
    """Extract lowercase name tokens (3+ chars) from title or email local part."""
    parts = re.split(r"[-_.\s@:|/]", text.lower())
    return [p for p in parts if len(p) >= 3]


def _find_people_file(people_dir: str, tokens: list[str]) -> Optional[str]:
    if not os.path.isdir(people_dir):
        return None
    for fname in sorted(os.listdir(people_dir)):
        if not fname.endswith(".md"):
            continue
        base = fname[:-3].lower()
        if any(re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", base) for t in tokens):
            return os.path.join(people_dir, fname)
    return None


def _find_pipeline_lead(pipeline_path: str, tokens: list[str]) -> Optional[dict]:
    try:
        with open(pipeline_path) as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for lead in cache.get("leads", []):
        lead_text = (lead.get("name", "") + " " + lead.get("contact", "") + " " + lead.get("email", "")).lower()
        if any(t in lead_text for t in tokens):
            return lead
    return None


def _find_observations(obs_path: str, tokens: list[str], limit: int = 5) -> list[str]:
    lines = []
    try:
        with open(obs_path) as f:
            for line in f:
                obs = json.loads(line)
                content = obs.get("content", "")
                if any(t in content.lower() for t in tokens):
                    lines.append(f"{obs.get('date', '?')}: {content}")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return lines[-limit:]


def build_external_context(event: CalendarEvent, config: dict) -> str:
    people_dir = config.get("people_dir", "data/people")
    pipeline_path = config.get("pipeline", {}).get("cache_path", "data/pipeline_cache.json")
    obs_path = config.get("memory", {}).get("observations_file", "data/memory/observations.jsonl")

    # Gather name tokens from title + attendee emails
    tokens = _name_tokens(event.summary)
    for attendee in event.attendees:
        local = attendee.split("@")[0]
        tokens += _name_tokens(local)
    tokens = list(set(tokens))

    parts = []

    people_path = _find_people_file(people_dir, tokens)
    if people_path:
        try:
            with open(people_path) as f:
                parts.append("## Contact Background\n" + f.read()[:800])
        except OSError:
            pass

    lead = _find_pipeline_lead(pipeline_path, tokens)
    if lead:
        days = f"{lead.get('days_since_contact')}d ago" if lead.get("days_since_contact") is not None else "unknown"
        val = f"${lead['estimated_value']:,.0f}" if lead.get("estimated_value") else ""
        stale = " [STALE]" if lead.get("stale") else ""
        lines = [
            f"Name: {lead.get('name', '?')}",
            f"Status: {lead.get('status', '?')}{stale}",
            f"Last contact: {days}",
        ]
        if val:
            lines.append(f"Est. value: {val}")
        parts.append("## Pipeline Record\n" + "\n".join(lines))

    obs = _find_observations(obs_path, tokens)
    if obs:
        parts.append("## Recent Context\n" + "\n".join(f"• {o}" for o in obs))

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run — expect pass**

```bash
.venv/bin/pytest tests/test_meeting_prep.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(prep): external meeting context assembly"
```

---

## Task 4: Internal meeting context assembly

Two internal context builders share the same function — the Claude prompt differentiates their output format.

`build_dept_heads_context()`: Pipeline breakdown by status + Google Sheets MTD sales/demos numbers + prior month totals if it's the first meeting of the month (day ≤ 7) + projects.md + open captures (for bottleneck synthesis).

"First meeting of the month" = `date.today().day <= 7`. When true, fetch the prior month tab and include totals alongside MTD.

`build_recurring_internal_context()`: Last 10 observations mentioning person keywords from meeting title + full `projects.md` + first 1000 chars of `captures.md`.

**Files:**
- Modify: `processors/meeting_prep.py`
- Modify: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_meeting_prep.py`:

```python
from processors.meeting_prep import build_dept_heads_context, build_recurring_internal_context


from unittest.mock import patch as _patch

def test_build_dept_heads_context_pipeline_summary(tmp_path):
    pipeline = {"leads": [
        {"name": "Tyler Landeck", "status": "In-Trial / Post Demo", "estimated_value": 2000, "stale": True, "contact": "", "email": "", "days_since_contact": 40, "priority": "High", "last_contacted": "2026-03-20", "source": None},
        {"name": "Mike Woodby", "status": "Out of Demo / Need Update", "estimated_value": None, "stale": False, "contact": "", "email": "", "days_since_contact": 5, "priority": "Medium", "last_contacted": "2026-04-25", "source": None},
    ]}
    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(json.dumps(pipeline))
    config = {
        "pipeline": {"cache_path": str(pipeline_path)},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    result = build_dept_heads_context(config)
    assert "In-Trial" in result or "Tyler" in result
    assert "Out of Demo" in result or "Mike" in result


def test_build_dept_heads_context_no_crash_missing_files(tmp_path):
    config = {
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    result = build_dept_heads_context(config)
    assert isinstance(result, str)


def test_build_recurring_internal_context_observations(tmp_path):
    obs_path = tmp_path / "obs.jsonl"
    obs_path.write_text(
        json.dumps({"date": "2026-04-28", "type": "top_priority", "entity": "priorities", "content": "Discussed LTV with Luke — he wants a demo next week", "source": "brief"}) + "\n"
    )
    projects_file = tmp_path / "projects.md"
    projects_file.write_text("## Project: LTV Lead Magnet\n**Next:** Design UI\n")
    config = {
        "memory": {"observations_file": str(obs_path)},
        "projects_file": str(projects_file),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Luke / Trent")
    result = build_recurring_internal_context(event, config)
    assert "luke" in result.lower() or "LTV" in result


def test_build_recurring_internal_context_no_crash_missing_files(tmp_path):
    config = {
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
        "projects_file": str(tmp_path / "projects.md"),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Luke / Trent")
    result = build_recurring_internal_context(event, config)
    assert isinstance(result, str)
```

- [ ] **Step 2: Run — expect failures**

```bash
.venv/bin/pytest tests/test_meeting_prep.py::test_build_dept_heads_context_pipeline_summary tests/test_meeting_prep.py::test_build_recurring_internal_context_observations -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement both context builders in `processors/meeting_prep.py`**

Append after `build_external_context`:

```python
def build_dept_heads_context(config: dict) -> str:
    pipeline_path = config.get("pipeline", {}).get("cache_path", "data/pipeline_cache.json")
    obs_path = config.get("memory", {}).get("observations_file", "data/memory/observations.jsonl")
    projects_file = config.get("projects_file", "data/projects.md")
    captures_file = config.get("captures_file", "data/captures.md")
    sheets_cfg = config.get("meeting_prep", {}).get("sheets", {})
    sales_sheet_id = sheets_cfg.get("sales_spreadsheet_id", "")
    demos_sheet_id = sheets_cfg.get("demos_spreadsheet_id", "")
    parts = []

    # ── Pipeline ────────────────────────────────────────────────────────
    try:
        with open(pipeline_path) as f:
            cache = json.load(f)
        leads = cache.get("leads", [])
        total = len(leads)
        by_status: dict[str, list] = {}
        for lead in leads:
            by_status.setdefault(lead.get("status", "Unknown"), []).append(lead)
        lines = [f"## Pipeline ({total} total)"]
        for status, group in sorted(by_status.items()):
            names = ", ".join(l.get("name", "?") for l in group[:3])
            suffix = "..." if len(group) > 3 else ""
            stale_count = sum(1 for l in group if l.get("stale"))
            line = f"• {status} ({len(group)}): {names}{suffix}"
            if stale_count:
                line += f" [{stale_count} stale]"
            lines.append(line)
        parts.append("\n".join(lines))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # ── Sales + Demos from Google Sheets ────────────────────────────────
    if sales_sheet_id or demos_sheet_id:
        try:
            from lib.google_auth import build_sheets_service
            from collectors.sheets import month_label, fetch_sales_mtd, fetch_demos_mtd
            svc = build_sheets_service()
            cur_label = month_label(0)
            is_first_of_month = date.today().day <= 7

            kpi_lines = [f"## Sales & Demos — {cur_label} MTD"]
            if sales_sheet_id:
                sales = fetch_sales_mtd(svc, sales_sheet_id, cur_label)
                kpi_lines.append(f"• New Sales MTD: {sales['count']} deals, ${sales['revenue']:,.0f}")
                if is_first_of_month:
                    prior = fetch_sales_mtd(svc, sales_sheet_id, month_label(-1))
                    kpi_lines.append(f"• {month_label(-1)} Final: {prior['count']} deals, ${prior['revenue']:,.0f}")
            if demos_sheet_id:
                demos = fetch_demos_mtd(svc, demos_sheet_id, cur_label)
                kpi_lines.append(f"• Demos MTD: {demos['count']}")
                if is_first_of_month:
                    prior_demos = fetch_demos_mtd(svc, demos_sheet_id, month_label(-1))
                    kpi_lines.append(f"• {month_label(-1)} Final Demos: {prior_demos['count']}")
            parts.append("\n".join(kpi_lines))
        except Exception as e:
            parts.append(f"## Sales & Demos\n(unavailable: {e})")

    # ── Projects ─────────────────────────────────────────────────────────
    if os.path.exists(projects_file):
        try:
            with open(projects_file) as f:
                parts.append("## Active Projects\n" + f.read()[:2000])
        except OSError:
            pass

    # ── Open captures (bottleneck synthesis material) ────────────────────
    if os.path.exists(captures_file):
        try:
            with open(captures_file) as f:
                content = f.read().strip()
            if content:
                parts.append("## Open Items & Flags\n" + content[:1000])
        except OSError:
            pass

    return "\n\n".join(parts)


def build_recurring_internal_context(event: CalendarEvent, config: dict) -> str:
    obs_path = config.get("memory", {}).get("observations_file", "data/memory/observations.jsonl")
    projects_file = config.get("projects_file", "data/projects.md")
    captures_file = config.get("captures_file", "data/captures.md")

    tokens = _name_tokens(event.summary)
    parts = []

    obs = _find_observations(obs_path, tokens, limit=10)
    if obs:
        parts.append("## Recent Context\n" + "\n".join(f"• {o}" for o in obs))

    if os.path.exists(projects_file):
        try:
            with open(projects_file) as f:
                parts.append("## Active Projects\n" + f.read()[:2000])
        except OSError:
            pass

    if os.path.exists(captures_file):
        try:
            with open(captures_file) as f:
                content = f.read().strip()
            if content:
                parts.append("## Open Captures\n" + content[:1000])
        except OSError:
            pass

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run — expect pass**

```bash
.venv/bin/pytest tests/test_meeting_prep.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(prep): dept heads + recurring internal context builders"
```

---

## Task 5: Claude call + message formatter

`build_prep_message()` is the public entry point. It:
1. Routes to the right context builder based on `meeting_type`
2. Calls Claude with a type-specific system prompt
3. Prepends an emoji header and meeting title to the response
4. Returns the final Telegram-ready string

**Prompts by type:**

- **external**: "Generate a 5-bullet pre-meeting brief: Who / Context / Open / Goal / Opener. Plain text, tight."
- **dept_heads**: "Generate a KPI-focused Dept Heads prep: Pipeline bullets, Signals This Week, Talking Points. Plain text."
- **recurring_internal**: "Generate a structured meeting prep: Last Time / Open Items / Projects to Touch / Suggested Focus. Plain text."

**Files:**
- Modify: `processors/meeting_prep.py`
- Modify: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write failing tests (mocking Claude)**

Append to `tests/test_meeting_prep.py`:

```python
from unittest.mock import MagicMock, patch
from processors.meeting_prep import build_prep_message


@patch("processors.meeting_prep.anthropic.Anthropic")
def test_build_prep_message_external(mock_cls, tmp_path):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="• Who: Mike\n• Context: Demo stage\n• Open: Contract\n• Goal: Close\n• Opener: How's Q2?")],
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    config = {
        "people_dir": str(tmp_path / "people"),
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Mike: OS Demo", attendees=["mike@apex.co"])
    result = build_prep_message(event, "external", config, api_key="test-key")
    assert "🎯" in result
    assert "Mike: OS Demo" in result
    assert "Who" in result


@patch("processors.meeting_prep.anthropic.Anthropic")
def test_build_prep_message_dept_heads(mock_cls, tmp_path):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Pipeline: 3 in trial\nSignals: Q2 push\nTalking Points: Stale leads")],
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    config = {
        "pipeline": {"cache_path": str(tmp_path / "pipeline.json")},
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
    }
    event = _event("Department Heads Weekly")
    result = build_prep_message(event, "dept_heads", config, api_key="test-key")
    assert "📊" in result
    assert "Department Heads" in result


@patch("processors.meeting_prep.anthropic.Anthropic")
def test_build_prep_message_recurring_internal(mock_cls, tmp_path):
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Last Time: Discussed LTV\nOpen Items: Follow up demo\nProjects: LTV magnet\nFocus: Push to close")],
        usage=MagicMock(input_tokens=100, output_tokens=50),
    )
    config = {
        "memory": {"observations_file": str(tmp_path / "obs.jsonl")},
        "projects_file": str(tmp_path / "projects.md"),
        "captures_file": str(tmp_path / "captures.md"),
    }
    event = _event("Luke / Trent")
    result = build_prep_message(event, "recurring_internal", config, api_key="test-key")
    assert "📋" in result
    assert "Luke / Trent" in result
```

- [ ] **Step 2: Run — expect failures**

```bash
.venv/bin/pytest tests/test_meeting_prep.py::test_build_prep_message_external tests/test_meeting_prep.py::test_build_prep_message_dept_heads tests/test_meeting_prep.py::test_build_prep_message_recurring_internal -v
```

Expected: `ImportError` on `build_prep_message`.

- [ ] **Step 3: Implement `build_prep_message` in `processors/meeting_prep.py`**

Append after `build_recurring_internal_context`:

```python
_SYSTEM_PROMPTS = {
    "external": (
        "You are Trent Luecke's AI Chief of Staff preparing him for an upcoming external meeting. "
        "Generate a concise pre-meeting brief with exactly these 5 bullets:\n"
        "• Who: [one sentence — who they are and where they're from]\n"
        "• Context: [where they are in the sales process or last interaction]\n"
        "• Open: [any unresolved item or thing they mentioned previously]\n"
        "• Goal: [what a win looks like for this meeting]\n"
        "• Opener: [a natural conversation starter]\n\n"
        "Plain text only. Tight and scannable. No headers."
    ),
    "dept_heads": (
        "You are Trent Luecke's AI Chief of Staff preparing him for the Department Heads meeting. "
        "Trent is VP of Sales at TeamBuildr OS. "
        "Generate a structured KPI prep brief with these sections:\n\n"
        "**Pipeline**\n[Total count + breakdown by stage. Call out stale counts.]\n\n"
        "**Sales & Demos**\n[MTD new sales count and revenue. MTD demos count. If prior month totals are provided, include them.]\n\n"
        "**Active Projects**\n[2-3 most important active projects and their next actions]\n\n"
        "**Bottlenecks / Cross-Department Needs**\n[Synthesize from open flags and items — anything blocked waiting on another team. If nothing clear, say 'None flagged'.]\n\n"
        "Plain text only. No preamble."
    ),
    "recurring_internal": (
        "You are Trent Luecke's AI Chief of Staff preparing him for a recurring internal meeting. "
        "Generate a structured prep brief with these sections:\n\n"
        "**Last Time**\n[Key things from the most recent prior context — what was discussed or decided]\n\n"
        "**Open Items**\n[Unresolved threads or action items relevant to this meeting]\n\n"
        "**Projects to Touch**\n[1-3 active projects most relevant to this person with their next actions]\n\n"
        "**Suggested Focus**\n[1-2 sentence recommended agenda for this meeting]\n\n"
        "Plain text only. No preamble."
    ),
}

_EMOJI = {
    "external": "🎯",
    "dept_heads": "📊",
    "recurring_internal": "📋",
}


def build_prep_message(
    event: CalendarEvent,
    meeting_type: str,
    config: dict,
    api_key: str,
) -> str:
    if meeting_type == "external":
        context = build_external_context(event, config)
    elif meeting_type == "dept_heads":
        context = build_dept_heads_context(config)
    else:
        context = build_recurring_internal_context(event, config)

    model = config.get("ai_model", "claude-sonnet-4-6")
    user_content = f"Meeting: {event.summary}\n\n{context}" if context else f"Meeting: {event.summary}"

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=600,
        system=_SYSTEM_PROMPTS[meeting_type],
        messages=[{"role": "user", "content": user_content}],
    )
    body = response.content[0].text.strip()
    emoji = _EMOJI.get(meeting_type, "📋")
    return f"{emoji} {event.summary}\n\n{body}"
```

- [ ] **Step 4: Run all tests — expect pass**

```bash
.venv/bin/pytest tests/test_meeting_prep.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(prep): Claude call + message formatter"
```

---

## Task 6: Wire into nudger.py

The pre-meeting prep check runs in the same `for event in today_events` loop, before the post-meeting nudge check. It needs `ANTHROPIC_API_KEY` from the environment and the `meeting_prep.enabled` flag from config.

The prep fires when: `event.start - timedelta(minutes=prep_window) <= now <= event.start`.

State (both nudge and prep) is saved at the end of `run()`.

**Files:**
- Modify: `nudger.py`

- [ ] **Step 1: Add `ANTHROPIC_API_KEY` to the nudge workflow**

Open `.github/workflows/nudge.yml`. In the `Run nudger` step, add the env var:

```yaml
      - name: Run nudger
        env:
          GOOGLE_OAUTH_JSON: ${{ secrets.GOOGLE_OAUTH_JSON }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_ALLOWED_CHAT_ID: ${{ secrets.TELEGRAM_ALLOWED_CHAT_ID }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python nudger.py
```

- [ ] **Step 2: Update `nudger.py` to add the prep loop**

Replace the entire `run()` function with the version below. The changes are:
- Import `ANTHROPIC_API_KEY` from env
- Load prep state before the loop
- Add prep check at the top of the event loop (before the nudge check)
- Save prep state after the loop

```python
def run() -> None:
    config = load_config()
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    nudge_delay = config.get("nudge_minutes_after", 5)
    pending_file = config["pending_nudges_file"]
    pending = load_pending_nudges(pending_file)
    already_nudged = {n["event_id"] for n in pending}

    prep_config = config.get("meeting_prep", {})
    prep_enabled = prep_config.get("enabled", False)
    prep_window = prep_config.get("prep_window_minutes", 20)
    prep_state_file = prep_config.get("preps_state_file", "data/meeting_preps.json")

    today_events, _, _ = fetch_two_day_events(config["calendar_ids"])
    now = datetime.now().astimezone()

    from processors.meeting_prep import (
        classify_meeting, build_prep_message,
        load_prep_state, save_prep_state, make_prep_key,
    )
    sent_preps = load_prep_state(prep_state_file) if prep_enabled else set()

    for event in today_events:
        # ── Pre-meeting prep ────────────────────────────────────────────
        if prep_enabled and api_key and bot_token and chat_id:
            prep_key = make_prep_key(event)
            if prep_key not in sent_preps:
                meeting_type = classify_meeting(event, config)
                if meeting_type:
                    prep_start = event.start - timedelta(minutes=prep_window)
                    if prep_start <= now <= event.start:
                        try:
                            message = build_prep_message(event, meeting_type, config, api_key)
                            send_message(bot_token, chat_id, message)
                            sent_preps.add(prep_key)
                            print(f"  Prep sent for: {event.summary} ({meeting_type})")
                        except Exception as e:
                            print(f"  WARNING: Prep failed for {event.summary}: {e}")

        # ── Post-meeting nudge ───────────────────────────────────────────
        if event.id in already_nudged:
            continue
        if not is_work_meeting(event):
            continue
        nudge_time = event.end + timedelta(minutes=nudge_delay)
        if now < nudge_time:
            continue

        if bot_token and chat_id:
            text = f"📝 {event.summary} just wrapped. Drop your notes — what was covered, open items, action items."
            send_message(bot_token, chat_id, text)
            print(f"  Nudge sent for: {event.summary}")
        else:
            print(f"  WARNING: TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_CHAT_ID not set — skipping nudge for {event.summary}")

        pending.append({
            "event_id": event.id,
            "meeting_name": event.summary,
            "sent_at": now.isoformat(),
            "session_date": date.today().isoformat(),
        })

    save_pending_nudges(pending, pending_file)
    if prep_enabled:
        save_prep_state(sent_preps, prep_state_file)
    print("✅ Nudger run complete.")
```

- [ ] **Step 3: Run nudger locally — expect clean output**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
.venv/bin/python nudger.py
```

Expected: `✅ Nudger run complete.` with no exceptions. If there's a meeting within the next 20 minutes it will attempt a real Claude call and Telegram send.

- [ ] **Step 4: Run full test suite — no regressions**

```bash
.venv/bin/pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All existing tests pass, all new meeting prep tests pass.

- [ ] **Step 5: Commit and push**

```bash
git add nudger.py .github/workflows/nudge.yml
git commit -m "feat(prep): wire pre-meeting prep into nudger loop"
git pull --rebase && git push
```

---

## Self-Review

### Spec coverage

| Requirement | Covered by |
|---|---|
| 20-minute window before meeting | Task 7 — `prep_start = event.start - timedelta(minutes=prep_window)` |
| External demos/calls → bullet list | Task 6 — `external` system prompt; Task 1 classification |
| Dept Heads → KPI report | Task 5 — `build_dept_heads_context`; Task 6 prompt |
| Dept Heads: pipeline count + stage breakdown | Task 5 — `build_dept_heads_context` pipeline section |
| Dept Heads: Sales MTD (count + revenue) | Task 2 — `fetch_sales_mtd`; Task 5 — Sheets section |
| Dept Heads: Demos MTD count | Task 2 — `fetch_demos_mtd`; Task 5 — Sheets section |
| Dept Heads: prior month totals on first meeting of month | Task 5 — `is_first_of_month = date.today().day <= 7` |
| Dept Heads: active projects | Task 5 — projects.md included in context |
| Dept Heads: bottlenecks synthesized from context | Task 5 — captures/flags included; Task 6 prompt instructs synthesis |
| Marketing Sync / Luke → recap + open loops | Task 5 — `build_recurring_internal_context`; Task 6 prompt |
| No duplicate sends for same meeting | Task 3 — `{event_id}_{date}` key; Task 7 — check before send |
| Recurring meetings get fresh prep each occurrence | Task 3 — key includes date, so same event_id on different dates is a new key |
| Config-driven meeting patterns | Task 1 — `dept_heads_patterns`, `recurring_internal_patterns` in `config.json` |
| Sheets IDs in config (not hardcoded) | Task 1 — `meeting_prep.sheets` block in `config.json` |
| Non-fatal — failure doesn't crash nudger | Task 7 — `try/except` around prep call with WARNING print |
| Persisted state committed back to repo | Existing nudge workflow already commits `data/` |

### Placeholder scan

No TBD, TODO, or vague steps found.

### Type consistency

- `CalendarEvent` fields used: `.id`, `.summary`, `.start`, `.end`, `.attendees` — consistent with `collectors/calendar.py` dataclass definition throughout.
- `classify_meeting(event: CalendarEvent, config: dict) -> Optional[str]` — consistent across tests and nudger wiring.
- `build_prep_message(event, meeting_type, config, api_key)` — 4-arg signature used consistently in tests and Task 6 wiring.
- `load_prep_state(path) -> set` / `save_prep_state(keys: set, path)` — consistent across tests and Task 6.
