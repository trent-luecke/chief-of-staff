# P14 Phase 4 — Trends, Patterns & Demo Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the weekly synthesis to proactively surface trend anomalies and forward-looking demo pipeline health, delivered as a new section in the weekly email and a Telegram message.

**Architecture:** New `processors/pattern_detector.py` module with two public functions — `detect_anomalies` (Python delta pre-pass over 4 weeks of observations, then one Claude call for narrative) and `scan_upcoming_demos` (calendar fetch for next 28 days, demo classification, pipeline enrichment). Both are called from `weekly_synthesis.py` after `synthesize_week()` with separate try/excepts — failures are non-fatal.

**Tech Stack:** Python, Anthropic SDK (`anthropic`), `collectors/calendar.py` (Google Calendar API), `lib/pipeline_activity.py` (pipeline cache), `lib/llm_logger.py` (usage logging), `lib/storage.py` (R2/local storage), `pytest`

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `collectors/calendar.py` | Add `declined: bool` to `CalendarEvent`, add `fetch_date_range_events` |
| Create | `processors/pattern_detector.py` | All dataclasses, delta computation, `detect_anomalies`, `scan_upcoming_demos` |
| Modify | `weekly_synthesis.py` | Wire both functions, render email section + Telegram message |
| Modify | `config.json` | Add `demo_scan` block |
| Modify | `tests/test_calendar.py` | Tests for `declined` field and `fetch_date_range_events` |
| Create | `tests/test_pattern_detector.py` | All pattern detector tests |

---

## Task 1: Add `CalendarEvent.declined` and `fetch_date_range_events`

**Files:**
- Modify: `collectors/calendar.py`
- Modify: `tests/test_calendar.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_calendar.py`:

```python
from collectors.calendar import fetch_today_events, fetch_two_day_events, fetch_date_range_events, CalendarEvent


MOCK_DECLINED_RESPONSE = {
    "items": [{
        "id": "evt_declined",
        "summary": "Demo: Declined",
        "start": {"dateTime": "2026-04-17T09:00:00-07:00"},
        "end": {"dateTime": "2026-04-17T10:00:00-07:00"},
        "attendees": [
            {"email": "contact@apexfitness.com"},
            {"email": "trent@teambuildr.com", "self": True, "responseStatus": "declined"},
        ],
        "description": "",
    }]
}

MOCK_ACCEPTED_RESPONSE = {
    "items": [{
        "id": "evt_accepted",
        "summary": "Demo: Accepted",
        "start": {"dateTime": "2026-04-17T09:00:00-07:00"},
        "end": {"dateTime": "2026-04-17T10:00:00-07:00"},
        "attendees": [
            {"email": "contact@apexfitness.com"},
            {"email": "trent@teambuildr.com", "self": True, "responseStatus": "accepted"},
        ],
        "description": "",
    }]
}

MOCK_RANGE_RESPONSE = {
    "items": [{
        "id": "evt_range_001",
        "summary": "Range Event",
        "start": {"dateTime": "2026-04-17T09:00:00-07:00"},
        "end": {"dateTime": "2026-04-17T10:00:00-07:00"},
        "attendees": [],
        "description": "",
    }]
}


def test_fetch_today_events_declined_sets_declined_true():
    with patch("collectors.calendar._build_service") as mock:
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = MOCK_DECLINED_RESPONSE
        mock.return_value = service
        events = fetch_today_events(calendar_id="primary", target_date=date(2026, 4, 17))
    assert len(events) == 1
    assert events[0].declined is True


def test_fetch_today_events_accepted_sets_declined_false():
    with patch("collectors.calendar._build_service") as mock:
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = MOCK_ACCEPTED_RESPONSE
        mock.return_value = service
        events = fetch_today_events(calendar_id="primary", target_date=date(2026, 4, 17))
    assert len(events) == 1
    assert events[0].declined is False


def test_fetch_date_range_events_deduplicates_across_calendar_ids():
    with patch("collectors.calendar._build_service") as mock:
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = MOCK_RANGE_RESPONSE
        mock.return_value = service
        events = fetch_date_range_events(
            calendar_ids=["primary", "other@group.calendar.google.com"],
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 18),
        )
    assert len(events) == 1
    assert events[0].id == "evt_range_001"


def test_fetch_date_range_events_skips_failed_calendar():
    with patch("collectors.calendar._build_service") as mock:
        mock.side_effect = Exception("API error")
        events = fetch_date_range_events(
            calendar_ids=["failing@group.calendar.google.com"],
            start_date=date(2026, 4, 17),
            end_date=date(2026, 4, 18),
        )
    assert events == []


def test_fetch_date_range_events_empty_range():
    events = fetch_date_range_events(
        calendar_ids=["primary"],
        start_date=date(2026, 4, 17),
        end_date=date(2026, 4, 17),  # end == start: empty
    )
    assert events == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_calendar.py::test_fetch_today_events_declined_sets_declined_true tests/test_calendar.py::test_fetch_date_range_events_deduplicates_across_calendar_ids -v
```

Expected: `ImportError` (fetch_date_range_events not defined) or `AttributeError` (declined not on CalendarEvent).

- [ ] **Step 3: Update `collectors/calendar.py`**

Replace the `CalendarEvent` dataclass and `fetch_today_events` event-building block, and add `fetch_date_range_events`:

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
    declined: bool = False


def _build_service(user_email: str):
    return build_calendar_service(user_email)


def fetch_today_events(
    calendar_id: str = "primary",
    target_date: Optional[date] = None,
    user_email: str = "",
    _return_error: bool = False,
) -> list[CalendarEvent]:
    if target_date is None:
        target_date = date.today()
    time_min = datetime.combine(target_date, datetime.min.time()).astimezone().isoformat()
    time_max = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).astimezone().isoformat()

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
        if _return_error:
            return e
        return []

    events = []
    for item in result.get("items", []):
        start_raw = item.get("start", {})
        if "date" in start_raw and "dateTime" not in start_raw:
            continue
        try:
            raw_attendees = item.get("attendees", [])
            self_entry = next((a for a in raw_attendees if a.get("self")), None)
            owner_declined = (
                self_entry is not None
                and self_entry.get("responseStatus") == "declined"
            )
            events.append(
                CalendarEvent(
                    id=item["id"],
                    summary=item.get("summary", "(no title)"),
                    start=parse_dt(start_raw["dateTime"]),
                    end=parse_dt(item["end"]["dateTime"]),
                    description=item.get("description", ""),
                    attendees=[
                        a["email"] for a in raw_attendees if not a.get("self")
                    ],
                    declined=owner_declined,
                )
            )
        except (KeyError, ValueError):
            continue
    return events


def fetch_two_day_events(
    calendar_ids: list[str],
    user_email: str = "",
) -> tuple[list[CalendarEvent], list[CalendarEvent], bool]:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_events, tomorrow_events = [], []
    calendar_failed = False
    for cal_id in calendar_ids:
        result = fetch_today_events(cal_id, today, user_email, _return_error=True)
        if isinstance(result, Exception):
            calendar_failed = True
        else:
            today_events.extend(result)
        result = fetch_today_events(cal_id, tomorrow, user_email, _return_error=True)
        if not isinstance(result, Exception):
            tomorrow_events.extend(result)
    today_events.sort(key=lambda e: e.start)
    tomorrow_events.sort(key=lambda e: e.start)
    return today_events, tomorrow_events, calendar_failed


def fetch_date_range_events(
    calendar_ids: list[str],
    start_date: date,
    end_date: date,
    user_email: str = "",
) -> list[CalendarEvent]:
    seen: set[str] = set()
    events: list[CalendarEvent] = []
    current = start_date
    while current < end_date:
        for cal_id in calendar_ids:
            result = fetch_today_events(cal_id, current, user_email, _return_error=True)
            if isinstance(result, Exception):
                print(f"WARNING: calendar fetch failed for {cal_id} on {current}: {result}", flush=True)
                continue
            for evt in result:
                if evt.id not in seen:
                    seen.add(evt.id)
                    events.append(evt)
        current += timedelta(days=1)
    events.sort(key=lambda e: e.start)
    return events
```

- [ ] **Step 4: Run all calendar tests**

```bash
pytest tests/test_calendar.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add collectors/calendar.py tests/test_calendar.py
git commit -m "feat(p14): add CalendarEvent.declined and fetch_date_range_events"
```

---

## Task 2: Dataclasses and Pure Helper Functions

**Files:**
- Create: `processors/pattern_detector.py`
- Create: `tests/test_pattern_detector.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pattern_detector.py`:

```python
import json
from datetime import date, timedelta

import pytest

from lib.storage import LocalStorage


def _write_obs(storage, entries):
    content = "\n".join(json.dumps(e) for e in entries) + "\n"
    storage.write("memory/observations.jsonl", content)


# --- Pure helper tests ---

def test_parse_kpi_context_extracts_integers():
    from processors.pattern_detector import _parse_kpi_context
    ctx = "sales_revenue=12000 sales_count=3 demos=8 open_bugs=5 bugs_high=2 cancellations_mtd=1"
    result = _parse_kpi_context(ctx)
    assert result["demos"] == 8
    assert result["bugs_high"] == 2
    assert result["cancellations_mtd"] == 1


def test_parse_kpi_context_empty_string():
    from processors.pattern_detector import _parse_kpi_context
    assert _parse_kpi_context("") == {}


def test_parse_kpi_context_ignores_non_integer_values():
    from processors.pattern_detector import _parse_kpi_context
    result = _parse_kpi_context("demos=8 label=foo bugs_high=2")
    assert result["demos"] == 8
    assert result["bugs_high"] == 2
    assert "label" not in result


def test_extract_patterns_section_parses_bullets():
    from processors.pattern_detector import _extract_patterns_section
    content = "# Weekly Synthesis\n\nSome text.\n\n## Patterns\n- Pattern one\n- Pattern two\n\n## Resolved\n- Done thing\n"
    result = _extract_patterns_section(content)
    assert result == ["Pattern one", "Pattern two"]


def test_extract_patterns_section_no_patterns():
    from processors.pattern_detector import _extract_patterns_section
    content = "# Weekly Synthesis\n\nNo patterns section here.\n"
    assert _extract_patterns_section(content) == []


def test_extract_patterns_section_empty_section():
    from processors.pattern_detector import _extract_patterns_section
    content = "## Patterns\n\n## Resolved\n"
    assert _extract_patterns_section(content) == []


def test_week_bucket_current_week():
    from processors.pattern_detector import _week_bucket
    run_date = date(2026, 5, 4)
    assert _week_bucket(date(2026, 5, 4), run_date) == 0
    assert _week_bucket(date(2026, 4, 28), run_date) == 0


def test_week_bucket_prior_weeks():
    from processors.pattern_detector import _week_bucket
    run_date = date(2026, 5, 4)
    assert _week_bucket(date(2026, 4, 27), run_date) == 1
    assert _week_bucket(date(2026, 4, 20), run_date) == 2
    assert _week_bucket(date(2026, 4, 13), run_date) == 3


def test_week_bucket_outside_window_returns_none():
    from processors.pattern_detector import _week_bucket
    run_date = date(2026, 5, 4)
    assert _week_bucket(date(2026, 4, 5), run_date) is None
    assert _week_bucket(date(2026, 5, 5), run_date) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pattern_detector.py -v
```

Expected: `ModuleNotFoundError` — `processors.pattern_detector` doesn't exist yet.

- [ ] **Step 3: Create `processors/pattern_detector.py` with dataclasses and pure helpers**

```python
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

_OBS_KEY = "memory/observations.jsonl"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PatternAnomaly:
    type: str       # "new" | "recurring" | "worsening"
    title: str
    description: str
    weeks_seen: int = 1


@dataclass
class AnomalyReport:
    anomalies: list[PatternAnomaly] = field(default_factory=list)


@dataclass
class UpcomingDemo:
    date: date
    title: str
    attendee_emails: list[str]
    lead_name: Optional[str]      # None = not in pipeline
    pipeline_stage: Optional[str]


@dataclass
class DemoScanReport:
    demos: list[UpcomingDemo] = field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _parse_kpi_context(context: str) -> dict[str, int]:
    result = {}
    for token in context.split():
        if "=" in token:
            k, _, v = token.partition("=")
            try:
                result[k] = int(v)
            except ValueError:
                pass
    return result


def _extract_patterns_section(content: str) -> list[str]:
    lines = content.splitlines()
    in_patterns = False
    bullets = []
    for line in lines:
        if line.strip() == "## Patterns":
            in_patterns = True
            continue
        if in_patterns:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                bullets.append(line[2:].strip())
    return bullets


def _week_bucket(obs_date: date, run_date: date) -> Optional[int]:
    delta = (run_date - obs_date).days
    if 0 <= delta < 7:
        return 0
    if 7 <= delta < 14:
        return 1
    if 14 <= delta < 21:
        return 2
    if 21 <= delta < 28:
        return 3
    return None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pattern_detector.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add processors/pattern_detector.py tests/test_pattern_detector.py
git commit -m "feat(p14): add pattern_detector dataclasses and pure helpers"
```

---

## Task 3: Data Loading and Delta Computation

**Files:**
- Modify: `processors/pattern_detector.py`
- Modify: `tests/test_pattern_detector.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pattern_detector.py`:

```python
# --- Data loading tests ---

def test_load_observations_window_filters_by_days(tmp_path):
    from processors.pattern_detector import _load_observations_window
    storage = LocalStorage(base_dir=str(tmp_path))
    run_date = date(2026, 5, 4)
    _write_obs(storage, [
        {"date": "2026-05-02", "type": "pipeline_stale", "entity": "acme", "content": "stale"},
        {"date": "2026-04-01", "type": "pipeline_stale", "entity": "old", "content": "old"},
    ])
    result = _load_observations_window(storage, run_date, days=28)
    assert len(result) == 1
    assert result[0]["entity"] == "acme"


def test_load_prior_weekly_patterns_returns_sorted_descending(tmp_path):
    from processors.pattern_detector import _load_prior_weekly_patterns
    storage = LocalStorage(base_dir=str(tmp_path))
    run_date = date(2026, 5, 4)
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Pattern A\n")
    storage.write("weekly/2026-04-20.md", "## Patterns\n- Pattern B\n")
    storage.write("weekly/2026-05-04.md", "## Patterns\n- Current\n")  # excluded (not before run_date)
    result = _load_prior_weekly_patterns(storage, run_date, lookback_weeks=4)
    assert len(result) == 2
    assert result[0]["date"] == "2026-04-27"
    assert result[0]["patterns"] == ["Pattern A"]
    assert result[1]["date"] == "2026-04-20"


def test_load_prior_weekly_patterns_insufficient_history(tmp_path):
    from processors.pattern_detector import _load_prior_weekly_patterns
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Only one\n")
    result = _load_prior_weekly_patterns(storage, date(2026, 5, 4), lookback_weeks=4)
    assert len(result) == 1


# --- Delta computation tests ---

def test_compute_weekly_metrics_counts_stale_entities(tmp_path):
    from processors.pattern_detector import _compute_weekly_metrics
    run_date = date(2026, 5, 4)
    obs = [
        {"date": "2026-05-01", "type": "pipeline_stale", "entity": "acme", "content": ""},
        {"date": "2026-05-02", "type": "pipeline_stale", "entity": "acme", "content": ""},  # same entity, deduped
        {"date": "2026-05-03", "type": "pipeline_stale", "entity": "globo-gym", "content": ""},
    ]
    result = _compute_weekly_metrics(obs, run_date)
    # Bucket 0 = current week
    assert result[0]["pipeline_stale_count"] == 2  # acme + globo-gym (unique entities)


def test_compute_weekly_metrics_counts_issues_by_channel(tmp_path):
    from processors.pattern_detector import _compute_weekly_metrics
    run_date = date(2026, 5, 4)
    obs = [
        {"date": "2026-05-01", "type": "issue_pattern", "entity": "gmail", "content": "", "context": "source: gmail#gmail"},
        {"date": "2026-05-01", "type": "issue_pattern", "entity": "slack", "content": "", "context": "source: slack#support"},
    ]
    result = _compute_weekly_metrics(obs, run_date)
    assert result[0]["issue_email_count"] == 1
    assert result[0]["issue_slack_count"] == 1


def test_compute_weekly_metrics_extracts_kpi_snapshot(tmp_path):
    from processors.pattern_detector import _compute_weekly_metrics
    run_date = date(2026, 5, 4)
    obs = [
        {
            "date": "2026-05-01",
            "type": "kpi_snapshot",
            "entity": "daily",
            "content": "",
            "context": "sales_revenue=12000 bugs_high=3 cancellations_mtd=2 demos=8",
        }
    ]
    result = _compute_weekly_metrics(obs, run_date)
    assert result[0]["bugs_high"] == 3
    assert result[0]["cancellations_mtd"] == 2


def test_compute_demo_trend_last_snapshot_per_month():
    from processors.pattern_detector import _compute_demo_trend
    run_date = date(2026, 5, 4)
    obs = [
        {"date": "2026-04-15", "type": "kpi_snapshot", "entity": "daily", "content": "", "context": "demos=5"},
        {"date": "2026-04-28", "type": "kpi_snapshot", "entity": "daily", "content": "", "context": "demos=9"},  # latest April
        {"date": "2026-03-31", "type": "kpi_snapshot", "entity": "daily", "content": "", "context": "demos=7"},
    ]
    result = _compute_demo_trend(obs, run_date)
    assert len(result) == 2
    april = next(m for m in result if m["month"] == "2026-04")
    assert april["demos"] == 9  # latest entry wins


def test_compute_demo_trend_empty_returns_empty():
    from processors.pattern_detector import _compute_demo_trend
    assert _compute_demo_trend([], date(2026, 5, 4)) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pattern_detector.py::test_load_observations_window_filters_by_days tests/test_pattern_detector.py::test_compute_weekly_metrics_counts_stale_entities tests/test_pattern_detector.py::test_compute_demo_trend_last_snapshot_per_month -v
```

Expected: `ImportError` — functions not defined yet.

- [ ] **Step 3: Add data loading + delta computation to `processors/pattern_detector.py`**

Append after the existing pure helpers:

```python
# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_observations_window(storage, run_date: date, days: int) -> list[dict]:
    cutoff = run_date - timedelta(days=days)
    obs = []
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            obs_date = date.fromisoformat(entry.get("date", "2000-01-01"))
            if cutoff <= obs_date <= run_date:
                obs.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return obs


def _load_prior_weekly_patterns(
    storage, run_date: date, lookback_weeks: int = 4
) -> list[dict]:
    keys = storage.list_keys("weekly/")
    dated = []
    for key in keys:
        name = key.split("/")[-1].replace(".md", "")
        try:
            d = date.fromisoformat(name)
            if d < run_date:
                dated.append((d, key))
        except ValueError:
            continue
    dated.sort(reverse=True)
    result = []
    for d, key in dated[:lookback_weeks]:
        content = storage.read(key) or ""
        result.append({"date": d.isoformat(), "patterns": _extract_patterns_section(content)})
    return result


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def _compute_weekly_metrics(obs: list[dict], run_date: date) -> list[dict]:
    labels = ["current week", "week -1", "week -2", "week -3"]
    buckets = []
    for i in range(4):
        week_end = run_date - timedelta(days=7 * i)
        week_start = run_date - timedelta(days=7 * (i + 1))
        buckets.append({
            "label": labels[i],
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "_stale_entities": set(),
            "issue_email_count": 0,
            "issue_slack_count": 0,
            "_kpi_date": None,
            "bugs_high": None,
            "cancellations_mtd": None,
        })

    for entry in obs:
        try:
            obs_date = date.fromisoformat(entry.get("date", ""))
        except ValueError:
            continue
        bucket_idx = _week_bucket(obs_date, run_date)
        if bucket_idx is None:
            continue
        b = buckets[bucket_idx]
        obs_type = entry.get("type", "")

        if obs_type == "pipeline_stale":
            entity = entry.get("entity", "")
            if entity:
                b["_stale_entities"].add(entity)
        elif obs_type == "issue_pattern":
            context = entry.get("context", "")
            if "slack" in context.lower():
                b["issue_slack_count"] += 1
            else:
                b["issue_email_count"] += 1
        elif obs_type == "kpi_snapshot":
            if b["_kpi_date"] is None or obs_date >= b["_kpi_date"]:
                ctx = _parse_kpi_context(entry.get("context", ""))
                b["bugs_high"] = ctx.get("bugs_high")
                b["cancellations_mtd"] = ctx.get("cancellations_mtd")
                b["_kpi_date"] = obs_date

    for b in buckets:
        b["pipeline_stale_count"] = len(b.pop("_stale_entities"))
        b.pop("_kpi_date", None)

    return buckets


def _compute_demo_trend(obs: list[dict], run_date: date) -> list[dict]:
    monthly: dict[str, dict] = {}
    for entry in obs:
        if entry.get("type") != "kpi_snapshot":
            continue
        try:
            obs_date = date.fromisoformat(entry.get("date", ""))
        except ValueError:
            continue
        month_key = obs_date.strftime("%Y-%m")
        existing = monthly.get(month_key)
        if existing is None:
            monthly[month_key] = entry
        else:
            try:
                if obs_date > date.fromisoformat(existing.get("date", "1970-01-01")):
                    monthly[month_key] = entry
            except ValueError:
                pass

    result = []
    for month_key in sorted(monthly.keys(), reverse=True)[:3]:
        entry = monthly[month_key]
        ctx = _parse_kpi_context(entry.get("context", ""))
        result.append({"month": month_key, "demos": ctx.get("demos", 0)})
    return result
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pattern_detector.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add processors/pattern_detector.py tests/test_pattern_detector.py
git commit -m "feat(p14): add pattern_detector data loading and delta computation"
```

---

## Task 4: `detect_anomalies` — Prompt and Claude Call

**Files:**
- Modify: `processors/pattern_detector.py`
- Modify: `tests/test_pattern_detector.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pattern_detector.py`:

```python
from unittest.mock import MagicMock, patch


def test_detect_anomalies_returns_empty_with_insufficient_history(tmp_path):
    from processors.pattern_detector import detect_anomalies, AnomalyReport
    from processors.weekly_synthesizer import WeeklySynthesis
    storage = LocalStorage(base_dir=str(tmp_path))
    # Only one prior weekly file — below the 2-file minimum
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Pattern A\n")
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=["P1"])
    result = detect_anomalies(storage, synthesis, date(2026, 5, 4), "key", "claude-sonnet-4-6")
    assert isinstance(result, AnomalyReport)
    assert result.anomalies == []


def test_detect_anomalies_returns_anomalies_from_claude(tmp_path):
    from processors.pattern_detector import detect_anomalies, PatternAnomaly
    from processors.weekly_synthesizer import WeeklySynthesis
    storage = LocalStorage(base_dir=str(tmp_path))
    run_date = date(2026, 5, 4)
    storage.write("weekly/2026-04-27.md", "## Patterns\n- Pattern A\n")
    storage.write("weekly/2026-04-20.md", "## Patterns\n- Pattern B\n")
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=["Stale leads spiking"])
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "anomalies": [{
            "type": "worsening",
            "title": "Stale leads spike",
            "description": "5 stale leads this week vs avg of 1.5.",
            "weeks_seen": 1,
        }]
    }))]
    mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
    with patch("processors.pattern_detector.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = detect_anomalies(storage, synthesis, run_date, "key", "claude-sonnet-4-6")
    assert len(result.anomalies) == 1
    assert result.anomalies[0].type == "worsening"
    assert result.anomalies[0].title == "Stale leads spike"


def test_detect_anomalies_handles_invalid_json_from_claude(tmp_path):
    from processors.pattern_detector import detect_anomalies, AnomalyReport
    from processors.weekly_synthesizer import WeeklySynthesis
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write("weekly/2026-04-27.md", "## Patterns\n- A\n")
    storage.write("weekly/2026-04-20.md", "## Patterns\n- B\n")
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=[])
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not json at all")]
    mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
    with patch("processors.pattern_detector.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = detect_anomalies(storage, synthesis, date(2026, 5, 4), "key", "claude-sonnet-4-6")
    assert isinstance(result, AnomalyReport)
    assert result.anomalies == []


def test_build_anomaly_prompt_includes_metrics_and_patterns():
    from processors.pattern_detector import _build_anomaly_prompt
    from processors.weekly_synthesizer import WeeklySynthesis
    synthesis = WeeklySynthesis(executive_summary="ok", patterns=["Lead follow-ups high"])
    weekly_metrics = [
        {"label": "current week", "week_start": "2026-04-27", "week_end": "2026-05-04",
         "pipeline_stale_count": 4, "issue_email_count": 2, "issue_slack_count": 1,
         "bugs_high": 3, "cancellations_mtd": 1},
    ]
    demo_trend = [{"month": "2026-04", "demos": 8}, {"month": "2026-03", "demos": 10}]
    prior_patterns = [{"date": "2026-04-27", "patterns": ["Pattern A"]}]
    prompt = _build_anomaly_prompt(synthesis, date(2026, 5, 4), weekly_metrics, demo_trend, prior_patterns)
    assert "Lead follow-ups high" in prompt
    assert "pipeline_stale_count" not in prompt  # should be formatted, not raw key names
    assert "2026-04" in prompt
    assert "Pattern A" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pattern_detector.py::test_detect_anomalies_returns_empty_with_insufficient_history tests/test_pattern_detector.py::test_detect_anomalies_returns_anomalies_from_claude -v
```

Expected: `ImportError` — `detect_anomalies` not defined yet.

- [ ] **Step 3: Add prompt builder, system prompt, and `detect_anomalies` to `processors/pattern_detector.py`**

Append after the delta computation section:

```python
import anthropic
from lib.llm_logger import log_usage

# ---------------------------------------------------------------------------
# Anomaly detection — prompt + Claude call
# ---------------------------------------------------------------------------

_ANOMALY_SYSTEM_PROMPT = """\
You are analyzing weekly trend data for Trent Luecke — VP of Sales at TeamBuildr OS \
(B2B SaaS for strength and conditioning coaches).

Review the metric deltas and pattern history. Surface 0–3 genuinely notable anomalies only.

An anomaly is worth surfacing if:
- A metric is 2× or more above its 4-week average (type: "worsening")
- A pattern has appeared in 3+ of the last 4 synthesized pattern lists (type: "recurring")
- A new pattern this week is absent from all prior 4 weeks AND supported by raw metric counts \
(type: "new")
- Month-over-month demo count dropped 20%+ (type: "worsening")

Cite specific numbers. If nothing clearly meets these thresholds, return {"anomalies": []}.

Respond ONLY in JSON:
{"anomalies": [{"type": "new"|"recurring"|"worsening", "title": "short label", \
"description": "1-2 sentences with specific numbers", "weeks_seen": 1}]}
"""


def _build_anomaly_prompt(
    current_synthesis,
    run_date: date,
    weekly_metrics: list[dict],
    demo_trend: list[dict],
    prior_patterns: list[dict],
) -> str:
    lines = [f"## Current week (ending {run_date.isoformat()})", ""]

    lines.append("**Current patterns:**")
    for p in current_synthesis.patterns:
        lines.append(f"- {p}")
    lines.append("")

    lines.append("## Weekly metrics (current + prior 3 weeks)")
    lines.append("")
    lines.append("| Week | Stale Leads | Issues (email) | Issues (Slack) | Bugs High | Cancellations MTD |")
    lines.append("|---|---|---|---|---|---|")
    for m in weekly_metrics:
        bugs = m["bugs_high"] if m["bugs_high"] is not None else "—"
        cancel = m["cancellations_mtd"] if m["cancellations_mtd"] is not None else "—"
        lines.append(
            f"| {m['label']} ({m['week_start']}) "
            f"| {m['pipeline_stale_count']} "
            f"| {m['issue_email_count']} "
            f"| {m['issue_slack_count']} "
            f"| {bugs} "
            f"| {cancel} |"
        )
    lines.append("")

    if demo_trend:
        lines.append("## Demo trend (last 3 months, demos MTD at month-end)")
        lines.append("")
        for m in demo_trend:
            lines.append(f"- {m['month']}: {m['demos']} demos")
        lines.append("")

    lines.append("## Prior 4 weeks — synthesized patterns")
    lines.append("")
    for pw in prior_patterns:
        lines.append(f"**Week ending {pw['date']}:**")
        for p in pw["patterns"]:
            lines.append(f"- {p}")
        if not pw["patterns"]:
            lines.append("- (none recorded)")
        lines.append("")

    return "\n".join(lines)


def detect_anomalies(
    storage,
    current_synthesis,
    run_date: date,
    api_key: str,
    model: str,
    lookback_weeks: int = 4,
) -> AnomalyReport:
    prior_patterns = _load_prior_weekly_patterns(storage, run_date, lookback_weeks)
    if len(prior_patterns) < 2:
        return AnomalyReport()

    obs = _load_observations_window(storage, run_date, days=90)
    weekly_metrics = _compute_weekly_metrics(obs, run_date)
    demo_trend = _compute_demo_trend(obs, run_date)

    prompt = _build_anomaly_prompt(current_synthesis, run_date, weekly_metrics, demo_trend, prior_patterns)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=800,
        system=_ANOMALY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    log_usage("pattern_detector", response.usage, model)

    raw = response.content[0].text.strip()
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return AnomalyReport()

    anomalies = []
    for item in data.get("anomalies", [])[:3]:
        anomalies.append(PatternAnomaly(
            type=item.get("type", "new"),
            title=item.get("title", ""),
            description=item.get("description", ""),
            weeks_seen=item.get("weeks_seen", 1),
        ))
    return AnomalyReport(anomalies=anomalies)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pattern_detector.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add processors/pattern_detector.py tests/test_pattern_detector.py
git commit -m "feat(p14): add detect_anomalies with Claude-backed pattern detection"
```

---

## Task 5: `scan_upcoming_demos`

**Files:**
- Modify: `processors/pattern_detector.py`
- Modify: `tests/test_pattern_detector.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_pattern_detector.py`:

```python
from datetime import datetime
from collectors.calendar import CalendarEvent


def _make_event(
    id="evt1",
    summary="John Smith / Trent Luecke",
    description="TeamBuildr OS demo with CrossFit Denver",
    attendees=None,
    declined=False,
    start_dt=None,
):
    if attendees is None:
        attendees = ["contact@crossfitdenver.com"]
    if start_dt is None:
        start_dt = datetime(2026, 5, 10, 9, 0)
    return CalendarEvent(
        id=id,
        summary=summary,
        start=start_dt,
        end=datetime(2026, 5, 10, 10, 0),
        description=description,
        attendees=attendees,
        declined=declined,
    )


_DEMO_CFG = {
    "demo_keywords": ["demo"],
    "internal_domains": ["teambuildr.com"],
}


def test_is_demo_event_passes_all_rules():
    from processors.pattern_detector import _is_demo_event
    event = _make_event()
    assert _is_demo_event(event, _DEMO_CFG) is True


def test_is_demo_event_fails_missing_demo_keyword_in_description():
    from processors.pattern_detector import _is_demo_event
    event = _make_event(description="TeamBuildr OS intro call")
    assert _is_demo_event(event, _DEMO_CFG) is False


def test_is_demo_event_fails_missing_os_in_title_and_description():
    from processors.pattern_detector import _is_demo_event
    event = _make_event(description="Product demo with the client")
    assert _is_demo_event(event, _DEMO_CFG) is False


def test_is_demo_event_fails_all_internal_attendees():
    from processors.pattern_detector import _is_demo_event
    event = _make_event(attendees=["colleague@teambuildr.com"])
    assert _is_demo_event(event, _DEMO_CFG) is False


def test_is_demo_event_fails_no_attendees():
    from processors.pattern_detector import _is_demo_event
    event = _make_event(attendees=[])
    assert _is_demo_event(event, _DEMO_CFG) is False


def test_is_demo_event_fails_declined():
    from processors.pattern_detector import _is_demo_event
    event = _make_event(declined=True)
    assert _is_demo_event(event, _DEMO_CFG) is False


def test_is_demo_event_os_in_title_not_description():
    from processors.pattern_detector import _is_demo_event
    event = _make_event(
        summary="TeamBuildr OS / John Smith",
        description="Product demo scheduled",
    )
    assert _is_demo_event(event, _DEMO_CFG) is True


def test_is_demo_event_empty_description_fails():
    from processors.pattern_detector import _is_demo_event
    event = _make_event(description="")
    assert _is_demo_event(event, _DEMO_CFG) is False


def test_scan_upcoming_demos_returns_matching_events(tmp_path):
    from processors.pattern_detector import scan_upcoming_demos, DemoScanReport
    storage = LocalStorage(base_dir=str(tmp_path))
    config = {
        "calendar_ids": ["primary"],
        "demo_scan": {
            "sales_rep_calendar_ids": [],
            "lookforward_days": 28,
            "demo_keywords": ["demo"],
            "internal_domains": ["teambuildr.com"],
        },
    }
    event = _make_event(start_dt=datetime(2026, 5, 10, 9, 0))
    with patch("collectors.calendar.fetch_date_range_events", return_value=[event]):
        result = scan_upcoming_demos(config, "trent@teambuildr.com", date(2026, 5, 4), storage)
    assert isinstance(result, DemoScanReport)
    assert result.total == 1
    assert result.demos[0].lead_name is None  # no pipeline data in tmp storage


def test_scan_upcoming_demos_enriches_known_pipeline_lead(tmp_path):
    from processors.pattern_detector import scan_upcoming_demos
    storage = LocalStorage(base_dir=str(tmp_path))
    storage.write_json("pipeline_cache.json", {
        "leads": [{"email": "contact@crossfitdenver.com", "name": "CrossFit Denver", "status": "Demo Scheduled"}]
    })
    config = {
        "calendar_ids": ["primary"],
        "demo_scan": {
            "sales_rep_calendar_ids": [],
            "lookforward_days": 28,
            "demo_keywords": ["demo"],
            "internal_domains": ["teambuildr.com"],
        },
    }
    event = _make_event()
    with patch("collectors.calendar.fetch_date_range_events", return_value=[event]):
        result = scan_upcoming_demos(config, "trent@teambuildr.com", date(2026, 5, 4), storage)
    assert result.demos[0].lead_name == "CrossFit Denver"
    assert result.demos[0].pipeline_stage == "Demo Scheduled"


def test_scan_upcoming_demos_skips_non_demo_events(tmp_path):
    from processors.pattern_detector import scan_upcoming_demos
    storage = LocalStorage(base_dir=str(tmp_path))
    config = {
        "calendar_ids": ["primary"],
        "demo_scan": {
            "sales_rep_calendar_ids": [],
            "lookforward_days": 28,
            "demo_keywords": ["demo"],
            "internal_domains": ["teambuildr.com"],
        },
    }
    not_a_demo = _make_event(description="Just a call, no product info")
    with patch("processors.pattern_detector.fetch_date_range_events", return_value=[not_a_demo]):
        result = scan_upcoming_demos(config, "trent@teambuildr.com", date(2026, 5, 4), storage)
    assert result.total == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pattern_detector.py::test_is_demo_event_passes_all_rules tests/test_pattern_detector.py::test_scan_upcoming_demos_returns_matching_events -v
```

Expected: `ImportError` — `_is_demo_event` and `scan_upcoming_demos` not defined.

- [ ] **Step 3: Add `_load_pipeline_lead_details`, `_is_demo_event`, and `scan_upcoming_demos` to `processors/pattern_detector.py`**

Append after `detect_anomalies`:

```python
# ---------------------------------------------------------------------------
# Demo scan
# ---------------------------------------------------------------------------

def _load_pipeline_lead_details(storage) -> dict[str, dict]:
    data = storage.read_json("pipeline_cache.json", default={})
    result = {}
    for r in data.get("leads", []):
        if r.get("email") and r.get("status") not in {"Closed", "Lost"}:
            result[r["email"].lower()] = {
                "name": r.get("name", ""),
                "status": r.get("status", ""),
            }
    return result


def _is_demo_event(event, demo_cfg: dict) -> bool:
    demo_keywords = [kw.lower() for kw in demo_cfg.get("demo_keywords", ["demo"])]
    internal_domains = [d.lower() for d in demo_cfg.get("internal_domains", ["teambuildr.com"])]

    title = event.summary.lower()
    desc = (event.description or "").lower()

    # Rule 1: demo keyword in description
    if not any(kw in desc for kw in demo_keywords):
        return False

    # Rule 2: "OS" in title or description
    if "os" not in title and "os" not in desc:
        return False

    # Rule 3: at least one external attendee
    has_external = any(
        not any(email.lower().endswith(f"@{domain}") for domain in internal_domains)
        for email in event.attendees
    )
    if not has_external:
        return False

    # Rule 4: not declined by calendar owner
    if event.declined:
        return False

    return True


def scan_upcoming_demos(
    config: dict,
    user_email: str,
    run_date: date,
    storage,
) -> DemoScanReport:
    from collectors.calendar import fetch_date_range_events

    demo_cfg = config.get("demo_scan", {})
    lookforward = demo_cfg.get("lookforward_days", 28)
    internal_domains = [d.lower() for d in demo_cfg.get("internal_domains", ["teambuildr.com"])]

    all_cal_ids = list(config.get("calendar_ids", [])) + list(demo_cfg.get("sales_rep_calendar_ids", []))
    start = run_date + timedelta(days=1)
    end = run_date + timedelta(days=lookforward + 1)

    events = fetch_date_range_events(all_cal_ids, start, end, user_email)
    lead_details = _load_pipeline_lead_details(storage)

    demos = []
    for event in events:
        if not _is_demo_event(event, demo_cfg):
            continue

        external_emails = [
            email for email in event.attendees
            if not any(email.lower().endswith(f"@{domain}") for domain in internal_domains)
        ]

        lead_name = None
        pipeline_stage = None
        for email in external_emails:
            details = lead_details.get(email.lower())
            if details:
                lead_name = details["name"]
                pipeline_stage = details["status"]
                break

        demos.append(UpcomingDemo(
            date=event.start.date(),
            title=event.summary,
            attendee_emails=external_emails,
            lead_name=lead_name,
            pipeline_stage=pipeline_stage,
        ))

    return DemoScanReport(demos=demos, total=len(demos))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pattern_detector.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add processors/pattern_detector.py tests/test_pattern_detector.py
git commit -m "feat(p14): add scan_upcoming_demos with demo classification and pipeline enrichment"
```

---

## Task 6: Wire into `weekly_synthesis.py`

**Files:**
- Modify: `weekly_synthesis.py`

- [ ] **Step 1: Add rendering helpers and update imports**

At the top of `weekly_synthesis.py`, add to imports:

```python
from processors.pattern_detector import (
    detect_anomalies, scan_upcoming_demos,
    AnomalyReport, DemoScanReport,
)
```

Add these two rendering functions before `_main_inner`:

```python
def _render_trends_html(anomaly_report: AnomalyReport, demo_report: DemoScanReport) -> str:
    if not anomaly_report.anomalies and not demo_report.demos:
        return ""
    parts = ["<h3>Trends &amp; Demo Health</h3>"]
    if anomaly_report.anomalies:
        parts.append("<h4>Pattern Alerts</h4><ul>")
        for a in anomaly_report.anomalies:
            parts.append(f"<li><strong>{a.title}</strong> — {a.description}</li>")
        parts.append("</ul>")
    if demo_report.demos:
        parts.append(f"<h4>Upcoming Demos ({demo_report.total} in next 28 days)</h4><ul>")
        for d in demo_report.demos:
            lead_info = d.lead_name or "new prospect"
            stage_info = f" ({d.pipeline_stage})" if d.pipeline_stage else " (not in pipeline)"
            parts.append(f"<li>{d.date.isoformat()} — {d.title} — {lead_info}{stage_info}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def _format_trends_telegram(anomaly_report: AnomalyReport, demo_report: DemoScanReport) -> str:
    lines = []
    if anomaly_report.anomalies:
        lines.append("Pattern Alerts:")
        for a in anomaly_report.anomalies:
            lines.append(f"• {a.title} — {a.description}")
        lines.append("")
    if demo_report.demos:
        lines.append(f"Upcoming Demos ({demo_report.total} in next 28 days):")
        for d in demo_report.demos:
            lead_info = d.lead_name or "new prospect"
            stage_info = f" ({d.pipeline_stage})" if d.pipeline_stage else ""
            lines.append(f"• {d.date.isoformat()} — {d.title} — {lead_info}{stage_info}")
    return "\n".join(lines)
```

- [ ] **Step 2: Wire both functions into `_main_inner`**

In `_main_inner`, after `_save_synthesis(storage, synthesis, run_date)` and before the Gmail send, add:

```python
    anomaly_report = AnomalyReport()
    demo_report = DemoScanReport()

    if config.get("demo_scan", {}).get("enabled"):
        try:
            anomaly_report = detect_anomalies(storage, synthesis, run_date, api_key, config["ai_model"])
        except Exception as e:
            print(f"WARNING: anomaly detection failed: {e}", file=sys.stderr)
        try:
            demo_report = scan_upcoming_demos(config, config["email"], run_date, storage)
        except Exception as e:
            print(f"WARNING: demo scan failed: {e}", file=sys.stderr)
```

Then update `html` to include the trends section. Replace:

```python
    html = _render_html(synthesis, run_date.isoformat())
```

With:

```python
    html = _render_html(synthesis, run_date.isoformat())
    trends_html = _render_trends_html(anomaly_report, demo_report)
    if trends_html:
        html += "\n" + trends_html
```

Then, after the existing retrieval digest Telegram block, add:

```python
    trends_text = _format_trends_telegram(anomaly_report, demo_report)
    if trends_text and bot_token and chat_id:
        try:
            header = f"📈 Trends & Demo Health — week ending {run_date.isoformat()}\n\n"
            send_message(bot_token, chat_id, header + trends_text)
            print("Trends & demo health sent via Telegram.")
        except Exception as e:
            print(f"WARNING: trends Telegram send failed: {e}", file=sys.stderr)
```

- [ ] **Step 3: Run existing weekly synthesizer tests to verify no regressions**

```bash
pytest tests/test_weekly_synthesizer.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add weekly_synthesis.py
git commit -m "feat(p14): wire Trends & Demo Health into weekly synthesis email and Telegram"
```

---

## Task 7: Config Update

**Files:**
- Modify: `config.json`

- [ ] **Step 1: Add `demo_scan` block to `config.json`**

Add after the `"storage"` block:

```json
"demo_scan": {
  "enabled": true,
  "sales_rep_calendar_ids": [],
  "lookforward_days": 28,
  "demo_keywords": ["demo"],
  "internal_domains": ["teambuildr.com"]
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python -c "import json; json.load(open('config.json')); print('valid')"
```

Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add config.json
git commit -m "chore(p14): add demo_scan config block"
```

---

## Final Verification

- [ ] **Run the full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass, no regressions.

- [ ] **Verify import chain is clean**

```bash
python -c "from processors.pattern_detector import detect_anomalies, scan_upcoming_demos; print('ok')"
```

Expected: `ok`
