# Routine Triggers + /routine Slack Command Implementation Plan (Phase 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The morning brief detects upcoming Google Calendar out-of-office windows and suggests activating a matching routine; a new `/routine` Slack command lists and runs routines, recording the OOO window's `trigger_key` so suggestions stop.

**Architecture:** A new `lib/ooo.py` owns OOO detection (its own `events().list` query via the injected calendar service — the existing `CalendarEvent` collector stays untouched) and suggestion-line building (pure over the routines list). The pipeline computes suggestions non-fatally and passes them into the brief like `what_moved_context`. The `/routine` command reuses the `/task` plumbing: worker route → `workflow_dispatch` → `scripts/slack_run_routine.py` → `lib.routines.run_routine` → race-safe commit-back (note_add.yml pattern).

**Tech Stack:** Python 3.11 (googleapiclient, pytest+MagicMock), Cloudflare Worker JS, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-04-task-horizon-routines-design.md` — "Triggered routines (calendar OOO)" + "`/routine` Slack command" sections.

## Global Constraints

- OOO match: `eventType == "outOfOffice"` on the primary calendar, OR title regex `\bOOO\b|out of office` (case-insensitive) as fallback. Detection window: `[today, today + lead_days]`.
- Suggestion appears while `today < window.start` and the routine has NO run whose `trigger_key == "gcal:<event_id>"`; it goes quiet once the window starts or a keyed run exists. No suggestion-state file — recompute each morning from calendar + `runs` (idempotent).
- Suggestion text names the Slack activation: `OOO detected Aug 10–14 — activate 'Out of Office Prep': type `/routine Out of Office Prep` in Slack.`
- Trigger detection is NON-FATAL everywhere: calendar errors never break the brief or block a run (run proceeds with `trigger_key=None`).
- `/routine` (no args) lists routines; `/routine <name>` fuzzy-matches and runs. **Two deliberate spec deviations, called out for review:** (a) ambiguous match → text reply listing candidates ("be more specific"), NOT interactive buttons — the owner-resolution button flow would add a worker interactive branch for a rare case with ~2 routines; (b) recent-run guard on the Slack path → run anyway with a "last ran <date>" note appended (no confirm dialog exists mid-slash-command). Both differ from the spec's letter; the PR body must state them.
- `routine_run.yml` commit-back MUST `git add data/tasks.jsonl data/routines.json` and use the note_add.yml race-safe push loop (fetch → rebase → retry ×5), NOT task_add.yml's `|| true`.
- No UI changes this phase. Work on branch `feat/routine-triggers` off fresh `origin/main`. Tests: `python3 -m pytest tests/<file> -v` from repo root.
- Post-merge manual step (documented in PR, cannot be automated): register the `/routine` slash command in the Slack app config pointing at `https://<worker-domain>/slack/routine`.

---

### Task 1: `lib/ooo.py` — OOO window detection + suggestion lines

**Files:**
- Create: `lib/ooo.py`
- Test: `tests/test_ooo.py` (new)

**Interfaces:**
- Produces: `OooWindow` dataclass (`event_id: str, summary: str, start: date, end: date` — end inclusive); `trigger_key(window) -> str` (`"gcal:<event_id>"`); `detect_ooo_windows(service, lead_days: int, today: Optional[date] = None) -> list[OooWindow]`; `routine_suggestions(service, routines: list, today: Optional[date] = None) -> list[str]`.
- Consumes: a Google Calendar service object (injected; built by callers via `lib.google_auth.build_calendar_service`), routine dicts from `lib.routines` (fields `name`, `trigger`, `runs`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_ooo.py`:

```python
# tests/test_ooo.py
from datetime import date
from unittest.mock import MagicMock

from lib.ooo import OooWindow, detect_ooo_windows, routine_suggestions, trigger_key

TODAY = date(2026, 8, 3)


def _svc(items):
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": items}
    return service


def _ooo_event(eid="evt1", summary="Out of office", start="2026-08-10", end="2026-08-15",
               event_type="outOfOffice", all_day=True):
    key = "date" if all_day else "dateTime"
    ev = {"id": eid, "summary": summary,
          "start": {key: start}, "end": {key: end}}
    if event_type:
        ev["eventType"] = event_type
    return ev


# --- detect_ooo_windows ---

def test_detects_native_ooo_event():
    # all-day event 8/10–8/15 exclusive end → inclusive 8/10–8/14
    windows = detect_ooo_windows(_svc([_ooo_event()]), lead_days=7, today=TODAY)
    assert len(windows) == 1
    w = windows[0]
    assert (w.event_id, w.start, w.end) == ("evt1", date(2026, 8, 10), date(2026, 8, 14))
    assert trigger_key(w) == "gcal:evt1"


def test_detects_title_fallback_regular_event():
    ev = _ooo_event(eid="evt2", summary="OOO - Hawaii", event_type="default")
    assert len(detect_ooo_windows(_svc([ev]), 7, today=TODAY)) == 1
    ev2 = _ooo_event(eid="evt3", summary="Heading out of office Friday", event_type=None)
    assert len(detect_ooo_windows(_svc([ev2]), 7, today=TODAY)) == 1


def test_ignores_unrelated_events():
    ev = _ooo_event(eid="evt4", summary="Demo: Apex Fitness", event_type="default")
    assert detect_ooo_windows(_svc([ev]), 7, today=TODAY) == []


def test_title_word_boundary():
    ev = _ooo_event(eid="evt5", summary="Vroom party", event_type="default")
    assert detect_ooo_windows(_svc([ev]), 7, today=TODAY) == []


def test_datetime_event_midnight_end_is_previous_day():
    ev = _ooo_event(eid="evt6", start="2026-08-10T00:00:00-05:00",
                    end="2026-08-15T00:00:00-05:00", all_day=False)
    w = detect_ooo_windows(_svc([ev]), 14, today=TODAY)[0]
    assert (w.start, w.end) == (date(2026, 8, 10), date(2026, 8, 14))


def test_datetime_event_midday_end_is_same_day():
    ev = _ooo_event(eid="evt7", start="2026-08-10T09:00:00-05:00",
                    end="2026-08-10T17:00:00-05:00", all_day=False)
    w = detect_ooo_windows(_svc([ev]), 14, today=TODAY)[0]
    assert (w.start, w.end) == (date(2026, 8, 10), date(2026, 8, 10))


def test_query_window_uses_lead_days():
    svc = _svc([])
    detect_ooo_windows(svc, lead_days=5, today=TODAY)
    kwargs = svc.events.return_value.list.call_args.kwargs
    assert kwargs["calendarId"] == "primary"
    assert kwargs["singleEvents"] is True
    assert "2026-08-03" in kwargs["timeMin"]
    assert "2026-08-09" in kwargs["timeMax"]  # today + lead_days + 1


# --- routine_suggestions ---

def _routine(name="Out of Office Prep", lead=7, runs=None, trigger=True):
    return {
        "id": "ooo-prep", "name": name,
        "steps": [{"title": "a"}],
        "trigger": {"type": "calendar_ooo", "lead_days": lead} if trigger else None,
        "runs": runs or [],
    }


def test_suggests_upcoming_unrun_window():
    lines = routine_suggestions(_svc([_ooo_event()]), [_routine()], today=TODAY)
    assert len(lines) == 1
    assert "Aug 10" in lines[0] and "Aug 14" in lines[0]
    assert "Out of Office Prep" in lines[0]
    assert "/routine Out of Office Prep" in lines[0]


def test_quiet_once_window_started():
    started = _ooo_event(start="2026-08-03", end="2026-08-05")  # starts today
    assert routine_suggestions(_svc([started]), [_routine()], today=TODAY) == []


def test_quiet_after_keyed_run():
    runs = [{"date": "2026-08-01", "trigger_key": "gcal:evt1", "source": "slack"}]
    assert routine_suggestions(_svc([_ooo_event()]), [_routine(runs=runs)], today=TODAY) == []


def test_unkeyed_run_does_not_suppress():
    runs = [{"date": "2026-08-01", "trigger_key": None, "source": "ui"}]
    assert len(routine_suggestions(_svc([_ooo_event()]), [_routine(runs=runs)], today=TODAY)) == 1


def test_untriggered_routines_ignored_and_no_calendar_call():
    svc = _svc([_ooo_event()])
    assert routine_suggestions(svc, [_routine(trigger=False)], today=TODAY) == []
    svc.events.return_value.list.assert_not_called()


def test_single_day_window_format():
    ev = _ooo_event(start="2026-08-10", end="2026-08-11")  # all-day exclusive end → 8/10 only
    lines = routine_suggestions(_svc([ev]), [_routine()], today=TODAY)
    assert "Aug 10 —" in lines[0] and "Aug 10–" not in lines[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ooo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.ooo'`

- [ ] **Step 3: Implement `lib/ooo.py`**

```python
# lib/ooo.py
"""Google Calendar out-of-office detection for routine triggers.

Owns the OOO query (independent of collectors/calendar.py, which drops
eventType) and the brief's suggestion lines. All functions take the calendar
service as an argument — callers build it via lib.google_auth.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

_OOO_TITLE_RE = re.compile(r"\bOOO\b|out of office", re.IGNORECASE)


@dataclass
class OooWindow:
    event_id: str
    summary: str
    start: date
    end: date  # inclusive last day


def trigger_key(window: OooWindow) -> str:
    return f"gcal:{window.event_id}"


def _parse_day(value: dict, end: bool = False) -> Optional[date]:
    """Parse a Google event start/end. All-day events use {'date': 'YYYY-MM-DD'}
    with an EXCLUSIVE end; timed events use {'dateTime': ISO} where a midnight
    end also means "through the previous day"."""
    if "date" in value:
        d = date.fromisoformat(value["date"])
        return d - timedelta(days=1) if end else d
    if "dateTime" in value:
        dt = datetime.fromisoformat(value["dateTime"])
        d = dt.date()
        if end and dt.time() == time(0, 0):
            d -= timedelta(days=1)
        return d
    return None


def detect_ooo_windows(service, lead_days: int, today: Optional[date] = None) -> list:
    """OOO windows on the primary calendar within [today, today + lead_days]."""
    today = today or date.today()
    time_min = datetime.combine(today, datetime.min.time()).astimezone().isoformat()
    time_max = datetime.combine(
        today + timedelta(days=lead_days + 1), datetime.min.time()
    ).astimezone().isoformat()
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    windows = []
    for item in result.get("items", []):
        summary = item.get("summary", "")
        if item.get("eventType") != "outOfOffice" and not _OOO_TITLE_RE.search(summary):
            continue
        start = _parse_day(item.get("start", {}))
        if start is None:
            continue
        end = _parse_day(item.get("end", {}), end=True) or start
        windows.append(OooWindow(
            event_id=item["id"],
            summary=summary or "Out of office",
            start=start,
            end=max(end, start),
        ))
    return windows


def _span(w: OooWindow) -> str:
    if w.end == w.start:
        return w.start.strftime("%b %-d")
    return f"{w.start.strftime('%b %-d')}–{w.end.strftime('%b %-d')}"


def routine_suggestions(service, routines: list, today: Optional[date] = None) -> list:
    """Brief suggestion lines for calendar-triggered routines.

    A window is suggested while it hasn't started (today < start) and the
    routine has no run keyed to it. Recomputed from scratch each call — no
    suggestion state is stored anywhere.
    """
    today = today or date.today()
    lines = []
    windows_by_lead: dict = {}
    for r in routines:
        trig = r.get("trigger") or {}
        if trig.get("type") != "calendar_ooo":
            continue
        lead = int(trig.get("lead_days", 7))
        if lead not in windows_by_lead:
            windows_by_lead[lead] = detect_ooo_windows(service, lead, today=today)
        run_keys = {run.get("trigger_key") for run in (r.get("runs") or [])}
        for w in windows_by_lead[lead]:
            if w.start <= today:
                continue
            if trigger_key(w) in run_keys:
                continue
            lines.append(
                f"OOO detected {_span(w)} — activate '{r['name']}': "
                f"type `/routine {r['name']}` in Slack."
            )
    return lines
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ooo.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add lib/ooo.py tests/test_ooo.py
git commit -m "feat(triggers): OOO window detection and routine suggestion lines"
```

---

### Task 2: Brief integration — suggestions in the prompt

**Files:**
- Modify: `processors/brief.py` (`_build_prompt` signature + section; `generate_brief` signature + passthrough)
- Modify: `pipeline.py` (`generate_and_deliver`, directly after the What Moved block that ends ~line 826, before the `# Brief generation` comment)
- Test: `tests/test_brief.py`

**Interfaces:**
- Consumes: `lib.ooo.routine_suggestions(service, routines, today=None)`, `lib.routines.list_routines(storage)`, `lib.google_auth.build_calendar_service()`, `lib.storage.registry_storage(config)`.
- Produces: `_build_prompt(..., routine_suggestions_context: str = "")` and `generate_brief(..., routine_suggestions_context: str = "")`; prompt section header `## Routine Suggestions` when non-empty.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_brief.py` (mirrors the existing `_build_prompt` test pattern):

```python
def test_brief_includes_routine_suggestions_section(tmp_path):
    from lib.storage import LocalStorage
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary

    prompt = _build_prompt(
        today_events=[], tomorrow_events=[], projects=[], due_tasks=[],
        loop_summary=LoopSummary(), open_issues=[], meeting_prep=[],
        inbox_text="", storage=LocalStorage(str(tmp_path)),
        routine_suggestions_context="  OOO detected Aug 10–14 — activate 'OOO Prep': type `/routine OOO Prep` in Slack.",
    )
    assert "Routine Suggestions" in prompt
    assert "/routine OOO Prep" in prompt


def test_brief_omits_routine_suggestions_when_empty(tmp_path):
    from lib.storage import LocalStorage
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary

    prompt = _build_prompt(
        today_events=[], tomorrow_events=[], projects=[], due_tasks=[],
        loop_summary=LoopSummary(), open_issues=[], meeting_prep=[],
        inbox_text="", storage=LocalStorage(str(tmp_path)),
    )
    assert "Routine Suggestions" not in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_brief.py -v -k routine_suggestions`
Expected: FAIL — unexpected keyword argument `routine_suggestions_context`

- [ ] **Step 3: Implement `processors/brief.py`**

(a) Add `routine_suggestions_context: str = "",` to `_build_prompt`'s parameters (after `what_moved_context`). (b) Inside `_build_prompt`, directly after the "Surfaced Today" block from Phase 1 (still a top-level section append, NOT inside `if storage is not None:` — the context arrives pre-computed), add:

```python
    if routine_suggestions_context and routine_suggestions_context.strip():
        sections += [
            "## Routine Suggestions (upcoming OOO detected — put the activation hint in act_today)",
            routine_suggestions_context,
            "",
        ]
```

(c) Add `routine_suggestions_context: str = "",` to `generate_brief`'s parameters (after `what_moved_context`) and pass `routine_suggestions_context=routine_suggestions_context,` in its `_build_prompt(...)` call.

- [ ] **Step 4: Implement `pipeline.py`** — after the What Moved try/except block and before the `# Brief generation` comment, add:

```python
        # Routine trigger suggestions (calendar OOO) — non-fatal
        _routine_suggestions = ""
        try:
            from lib.ooo import routine_suggestions
            from lib.routines import list_routines
            from lib.storage import registry_storage as _reg_storage
            _routines = list_routines(_reg_storage(config))
            if any((r.get("trigger") or {}).get("type") == "calendar_ooo" for r in _routines):
                from lib.google_auth import build_calendar_service
                _suggestions = routine_suggestions(build_calendar_service(), _routines)
                _routine_suggestions = "\n".join(f"  {s}" for s in _suggestions)
        except Exception as e:
            print(f"⚠️  Routine trigger detection error (non-fatal): {e}", file=sys.stderr)
```

and add `routine_suggestions_context=_routine_suggestions,` to the `generate_brief(...)` call (after `what_moved_context=_what_moved_context,`).

Note the calendar service is built ONLY when at least one routine has a calendar trigger — zero API cost otherwise.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_brief.py tests/test_ooo.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add processors/brief.py pipeline.py tests/test_brief.py
git commit -m "feat(triggers): OOO routine suggestions in morning brief"
```

---

### Task 3: `scripts/slack_run_routine.py` + `routine_run.yml`

**Files:**
- Create: `scripts/slack_run_routine.py`
- Create: `.github/workflows/routine_run.yml`
- Test: `tests/test_slack_run_routine.py` (new)

**Interfaces:**
- Consumes: `lib.routines.list_routines/run_routine/ran_within/last_run_date`; `lib.ooo.detect_ooo_windows/trigger_key`; `lib.google_auth.build_calendar_service`; env `ROUTINE_QUERY`, `RESPONSE_URL`, `GOOGLE_OAUTH_JSON`.
- Produces: pure helpers `match_routines(query, routines) -> list`, `format_routine_list(routines) -> str`, `format_run_confirmation(routine, tasks, note=None) -> str`, `detect_trigger_key(routine) -> Optional[str]`; workflow `routine_run.yml` with inputs `routine_query`, `response_url`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_slack_run_routine.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.slack_run_routine import (
    match_routines, format_routine_list, format_run_confirmation,
)


def _r(name, rid=None, steps=1, trigger=None):
    return {"id": rid or name.lower().replace(" ", "-"), "name": name,
            "steps": [{"title": f"s{i}"} for i in range(steps)],
            "trigger": trigger, "runs": []}


def test_match_exact_and_substring():
    routines = [_r("Out of Office Prep"), _r("Weekly Review")]
    assert [m["name"] for m in match_routines("out of office prep", routines)] == ["Out of Office Prep"]
    assert [m["name"] for m in match_routines("weekly", routines)] == ["Weekly Review"]
    assert [m["name"] for m in match_routines("ooo-prep", routines)] == []  # id substring only when query matches id
    assert [m["name"] for m in match_routines("out-of-office-prep", routines)] == ["Out of Office Prep"]


def test_match_multiple_and_none():
    routines = [_r("OOO Prep"), _r("OOO Wrap-up")]
    assert len(match_routines("ooo", routines)) == 2
    assert match_routines("zzz", routines) == []


def test_format_routine_list():
    routines = [_r("OOO Prep", steps=3, trigger={"type": "calendar_ooo", "lead_days": 7}),
                _r("Weekly Review", steps=1)]
    out = format_routine_list(routines)
    assert "OOO Prep (3 steps · auto-OOO)" in out
    assert "Weekly Review (1 step)" in out
    assert "`/routine OOO Prep`" in out


def test_format_routine_list_empty():
    assert "No routines defined yet" in format_routine_list([])


def test_format_run_confirmation():
    routine = _r("OOO Prep")
    tasks = [{"title": "Cancel meetings"}, {"title": "Set responder"}]
    out = format_run_confirmation(routine, tasks)
    assert out.startswith("Ran 'OOO Prep' — created 2 tasks:")
    assert "• Cancel meetings" in out and "• Set responder" in out


def test_format_run_confirmation_with_note():
    out = format_run_confirmation(_r("R"), [{"title": "a"}], note="_Note: last ran 2026-07-01._")
    assert out.endswith("_Note: last ran 2026-07-01._")
    assert "created 1 task:" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/test_slack_run_routine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.slack_run_routine'`
(If `scripts/` lacks an `__init__.py`, check how `tests/test_slack_add_task.py` imports `scripts.slack_add_task` — it works today via the repo-root `sys.path` insert; mirror it exactly.)

- [ ] **Step 3: Implement `scripts/slack_run_routine.py`**

```python
#!/usr/bin/env python3
"""Run a routine from the /routine Slack slash command. Called by routine_run.yml.

/routine            -> list routines
/routine <name>     -> fuzzy-match and run; records the nearest upcoming OOO
                       window's trigger_key when the routine has a calendar
                       trigger, so the brief's suggestion goes quiet.
"""
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import LocalStorage
from lib.routines import last_run_date, list_routines, ran_within, run_routine


def _post_json(response_url: str, payload: dict) -> None:
    if not response_url:
        return
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        response_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Warning: failed to post to Slack response_url: {e}", file=sys.stderr)


def post_to_slack(response_url: str, text: str) -> None:
    _post_json(response_url, {"response_type": "ephemeral", "text": text})


def match_routines(query: str, routines: list) -> list:
    """Case-insensitive substring match on name or id, either direction."""
    q = query.lower().strip()
    if not q:
        return []
    return [
        r for r in routines
        if q in r["name"].lower() or r["name"].lower() in q or q == r["id"]
    ]


def format_routine_list(routines: list) -> str:
    if not routines:
        return "No routines defined yet — create one in the Registry UI (Work tab)."
    lines = ["Routines:"]
    for r in routines:
        n = len(r.get("steps") or [])
        trig = " · auto-OOO" if (r.get("trigger") or {}).get("type") == "calendar_ooo" else ""
        lines.append(f"• {r['name']} ({n} step{'s' if n != 1 else ''}{trig}) — `/routine {r['name']}`")
    return "\n".join(lines)


def format_run_confirmation(routine: dict, tasks: list, note: Optional[str] = None) -> str:
    lines = [f"Ran '{routine['name']}' — created {len(tasks)} task{'s' if len(tasks) != 1 else ''}:"]
    lines += [f"• {t['title']}" for t in tasks]
    if note:
        lines.append(note)
    return "\n".join(lines)


def detect_trigger_key(routine: dict) -> Optional[str]:
    """Nearest upcoming OOO window's key for a calendar-triggered routine.

    Non-fatal: any calendar failure returns None and the run proceeds unkeyed.
    """
    trig = routine.get("trigger") or {}
    if trig.get("type") != "calendar_ooo":
        return None
    try:
        from lib.google_auth import build_calendar_service
        from lib.ooo import detect_ooo_windows, trigger_key
        windows = [
            w for w in detect_ooo_windows(build_calendar_service(), int(trig.get("lead_days", 7)))
            if w.start >= date.today()
        ]
        if not windows:
            return None
        return trigger_key(min(windows, key=lambda w: w.start))
    except Exception as e:
        print(f"Warning: trigger detection failed (running without trigger_key): {e}", file=sys.stderr)
        return None


def main():
    query = os.environ.get("ROUTINE_QUERY", "").strip()
    response_url = os.environ.get("RESPONSE_URL", "")
    storage = LocalStorage(base_dir=str(ROOT / "data"))
    routines = list_routines(storage)

    if not query:
        msg = format_routine_list(routines)
        post_to_slack(response_url, msg)
        print(msg)
        return

    matches = match_routines(query, routines)
    if not matches:
        msg = f"No routine matches '{query}'.\n" + format_routine_list(routines)
        post_to_slack(response_url, msg)
        print(msg)
        return
    if len(matches) > 1:
        options = ", ".join(f"`/routine {r['name']}`" for r in matches)
        msg = f"'{query}' matches multiple routines — be more specific: {options}"
        post_to_slack(response_url, msg)
        print(msg)
        return

    routine = matches[0]
    if not routine.get("steps"):
        msg = f"'{routine['name']}' has no steps — edit it in the Registry UI first."
        post_to_slack(response_url, msg)
        print(msg)
        return

    note = None
    if ran_within(routine, days=7):
        note = f"_Note: this routine last ran {last_run_date(routine)}._"

    result = run_routine(storage, routine["id"], source="slack",
                         trigger_key=detect_trigger_key(routine))
    confirmation = format_run_confirmation(result["routine"], result["tasks"], note)
    post_to_slack(response_url, confirmation)
    print(confirmation)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_slack_run_routine.py tests/test_routines.py -v`
Expected: ALL PASS

- [ ] **Step 5: Create `.github/workflows/routine_run.yml`** (note_add.yml's race-safe push, BOTH data files added):

```yaml
name: Run Routine from Slack

on:
  workflow_dispatch:
    inputs:
      routine_query:
        description: "Routine name/id to run (empty = list routines)"
        required: false
        default: ""
      response_url:
        description: "Slack response_url for posting the confirmation"
        required: false
        default: ""

permissions:
  contents: write

jobs:
  run-routine:
    runs-on: ubuntu-latest
    env:
      TZ: America/Chicago
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run routine
        env:
          ROUTINE_QUERY: ${{ inputs.routine_query }}
          RESPONSE_URL: ${{ inputs.response_url }}
          GOOGLE_OAUTH_JSON: ${{ secrets.GOOGLE_OAUTH_JSON }}
        run: python scripts/slack_run_routine.py

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/tasks.jsonl data/routines.json
          if git diff --staged --quiet; then
            echo "No changes to commit."
            exit 0
          fi
          git commit -m "chore: run routine from slack [skip ci]"
          # Race-safe push (note_add.yml pattern): tasks.jsonl union-merges;
          # routines.json is plain JSON — a rebase conflict there fails loudly.
          for attempt in 1 2 3 4 5; do
            if git push origin HEAD:main; then
              echo "Pushed on attempt $attempt."
              exit 0
            fi
            echo "Push rejected (attempt $attempt) — fetching and rebasing onto origin/main."
            git fetch origin main
            git rebase origin/main || { echo "Rebase failed."; exit 1; }
          done
          echo "Failed to push after 5 attempts."
          exit 1
```

- [ ] **Step 6: Commit**

```bash
git add scripts/slack_run_routine.py tests/test_slack_run_routine.py .github/workflows/routine_run.yml
git commit -m "feat(triggers): /routine run script and workflow"
```

---

### Task 4: Cloudflare worker `/slack/routine` route

**Files:**
- Modify: `cloudflare/telegram-bridge.js` — new handler beside `handleSlackNote`, route registration in the `fetch` handler (after the `/slack/note` branch, ~line 285).

**Interfaces:**
- Consumes: existing `verifySlackSig`, `dispatchToGitHub`, `postEphemeral` helpers; workflow `routine_run.yml` inputs `routine_query`/`response_url` from Task 3.
- Produces: POST `/slack/routine` → dispatch + ephemeral ack.

- [ ] **Step 1: Add the handler** — insert after `handleSlackNote`'s closing brace:

```javascript
async function handleSlackRoutine(request, env, ctx) {
  const timestamp = request.headers.get("X-Slack-Request-Timestamp") || "";
  const signature = request.headers.get("X-Slack-Signature") || "";

  if (!timestamp || !signature) return new Response("Unauthorized", { status: 401 });

  const rawBody = await request.text();

  if (!await verifySlackSig(env.SLACK_SIGNING_SECRET, timestamp, rawBody, signature)) {
    return new Response("Unauthorized", { status: 401 });
  }

  const params = new URLSearchParams(rawBody);
  const text = (params.get("text") || "").trim();
  const responseUrl = params.get("response_url") || "";

  ctx.waitUntil(
    dispatchToGitHub(env, "routine_run.yml", {
      routine_query: text,
      response_url: responseUrl,
    }).then(ok => {
      if (!ok) return postEphemeral(responseUrl, "❌ Failed to queue routine — GitHub dispatch error. Try again or check the PAT.");
    })
  );

  return Response.json({
    response_type: "ephemeral",
    text: text ? `Running routine "${text}"...` : "Fetching routines...",
  });
}
```

- [ ] **Step 2: Register the route** — in the `fetch` handler, after the `/slack/note` branch:

```javascript
    if (url.pathname === "/slack/routine") {
      return handleSlackRoutine(request, env, ctx);
    }
```

- [ ] **Step 3: Verify**

Run: `node --check cloudflare/telegram-bridge.js`
Expected: no output (clean)

- [ ] **Step 4: Commit**

```bash
git add cloudflare/telegram-bridge.js
git commit -m "feat(triggers): /slack/routine worker route"
```

---

### Task 5: Full-suite verification + PR

- [ ] **Step 1: Full suite**

Run: `python3 -m pytest tests/ -q 2>&1 | tail -3`
Expected: ALL PASS (Phase 2 baseline: 844 passed, 3 skipped; this branch adds ~20)

- [ ] **Step 2: Live read-only detection check (controller)** — with the repo `.env` loaded (it holds `GOOGLE_OAUTH_JSON`), run a one-off snippet calling `detect_ooo_windows(build_calendar_service(), 60)` and print the windows. This is read-only against the real calendar and proves auth + query + parsing end-to-end. If no OOO events exist in the next 60 days, an empty list is a PASS (the query executed).

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin feat/routine-triggers
gh pr create --title "feat: routine triggers — OOO detection in brief + /routine Slack command" --body "$(cat <<'EOF'
Phase 3 (final) of the Horizon + Routines spec (docs/superpowers/specs/2026-07-04-task-horizon-routines-design.md).

- `lib/ooo.py`: OOO window detection on the primary calendar (`eventType == "outOfOffice"` + title fallback) and brief suggestion lines, deduped per calendar event via `runs[].trigger_key` — no suggestion-state file, recomputed each morning
- Brief: "Routine Suggestions" prompt section (non-fatal; calendar service built only when a triggered routine exists)
- `/routine` Slack command: worker route → `routine_run.yml` → `scripts/slack_run_routine.py`; no args lists routines, with a name fuzzy-matches and runs, recording the nearest upcoming OOO window's trigger_key; commit-back race-safe (note_add.yml pattern) and adds BOTH `data/tasks.jsonl` and `data/routines.json`

Deliberate spec deviations (flagged for review):
- Ambiguous routine name → text reply listing candidates instead of interactive buttons (owner-resolution-style buttons deemed not worth a new worker interactive branch at current routine counts)
- Recent-run guard on the Slack path runs anyway with a "last ran <date>" note (no confirm dialog exists mid-slash-command); the UI path keeps its confirm

Post-merge manual steps:
1. Register the `/routine` slash command in the Slack app config → Request URL `https://<worker-domain>/slack/routine` (worker auto-deploys via deploy-worker.yml on merge).
2. Smoke test: `/routine` (list), `/routine <name>` (run), and confirm the next brief suggests a test OOO event.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Merge on GitHub (server-side merge keeps local main from drifting ahead).
