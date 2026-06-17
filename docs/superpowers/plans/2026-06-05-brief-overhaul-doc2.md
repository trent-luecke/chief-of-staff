# Brief Overhaul Doc 2: Digest → 3-Block Brief

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the 9-field brief into 3 blocks — Act Today / What Moved / Metric Flags — wired to `evaluate_metrics()` output and a confirmed `what_moved` design.

**Architecture:** `BriefContent` shrinks to 3 fields. Claude generates `act_today` and `what_moved` from context; `metric_flags` are pre-computed by pipeline code from `evaluate_metrics()` and stored directly. `what_moved` is built from snapshot diffs (onboarding/pipeline caches) + Avoma demos + cancellations. The email template (`morning_brief.html`) gets the 3-block layout; `dashboard.html` is split out as a richer standalone template.

**Tech Stack:** Python dataclasses, Jinja2, pytest/mock, `lib/gtm_metrics.py`, `collectors/avoma.py`, `collectors/onboarding.py`, `data/state/` for prev snapshots.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `processors/brief.py` | Modify | New `BriefContent` (3 fields), new `SYSTEM_PROMPT` (2-key JSON), updated `_build_prompt()` + `generate_brief()` |
| `processors/what_moved.py` | **Create** | `build_what_moved_context()` — builds prompt section from 4 event sources, capped at 7 |
| `templates/morning_brief.html` | Modify | 3-block email layout: Act Today, What Moved, Metric Flags |
| `templates/dashboard.html` | **Create** | Richer local-dashboard template: 3 blocks + full metric table + calendar + projects |
| `outputs/dashboard.py` | Modify | Use `dashboard.html`; accept `metric_results` param |
| `pipeline.py` | Modify | Add `leads_data` collection; call `evaluate_metrics()`; call `build_what_moved_context()`; write prev snapshots; inject system warnings into `act_today` instead of `watch_outs` |
| `tests/test_brief.py` | Modify | Rewrite for new `BriefContent` (3 fields) |
| `tests/test_sender.py` | Modify | Update `make_brief()` helper and HTML assertions |
| `tests/test_what_moved.py` | **Create** | Unit tests for `build_what_moved_context()` |

---

## Task 1: Rewrite tests for new BriefContent shape

**Files:**
- Modify: `tests/test_brief.py`
- Modify: `tests/test_sender.py`

- [ ] **Step 1: Replace MOCK_BRIEF_JSON in test_brief.py**

Replace the existing `MOCK_BRIEF_JSON` constant (line 12) with the new 2-key shape Claude returns:

```python
MOCK_BRIEF_JSON = {
    "act_today": [
        "Close Apex Fitness — trial ends Friday, send contract today",
        "Reply to renewal email from SportsPlex — 3 days stale",
    ],
    "what_moved": [
        "CrossFit Box had a demo — strong interest in OS pricing",
    ],
}
```

- [ ] **Step 2: Rewrite test_generate_brief_returns_content**

```python
def test_generate_brief_returns_content(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(
        json.dumps(MOCK_BRIEF_JSON)
    )
    events = [CalendarEvent(id="e1", summary="Demo: Apex", start=datetime.now(), end=datetime.now())]
    projects = [Project(name="CRM", status="In Progress", next_step="Deploy")]
    tasks = [RecurringTask(name="Check trials", schedule="daily")]

    content = generate_brief(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        today_events=events,
        tomorrow_events=[],
        email_threads=[],
        projects=projects,
        due_tasks=tasks,
        loop_summary=LoopSummary(),
    )

    assert len(content.act_today) == 2
    assert "Apex Fitness" in content.act_today[0]
    assert content.what_moved == ["CrossFit Box had a demo — strong interest in OS pricing"]
    assert content.metric_flags == []
```

- [ ] **Step 3: Rewrite test_generate_brief_handles_markdown_wrapped_json**

```python
def test_generate_brief_handles_markdown_wrapped_json(mock_anthropic):
    wrapped = f"```json\n{json.dumps(MOCK_BRIEF_JSON)}\n```"
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(wrapped)

    content = generate_brief(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
    )
    assert len(content.act_today) == 2
```

- [ ] **Step 4: Add test for metric_flags pass-through**

Add after the existing tests:

```python
def test_generate_brief_stores_metric_flags(mock_anthropic):
    mock_anthropic.return_value.messages.create.return_value = make_mock_claude_response(
        json.dumps(MOCK_BRIEF_JSON)
    )
    flags = ["Leads MTD: tracking 40% below pace — next month tracking light"]

    content = generate_brief(
        api_key="sk-test",
        model="claude-haiku-4-5-20251001",
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        metric_flags=flags,
    )
    assert content.metric_flags == flags
```

- [ ] **Step 5: Update make_brief() in test_sender.py**

Replace the existing `make_brief()` function (lines 8–13) with:

```python
def make_brief() -> BriefContent:
    return BriefContent(
        act_today=["Close Apex", "Reply to contract email", "Check trials"],
        what_moved=["CrossFit Box had a demo"],
        metric_flags=["All GTM metrics in range"],
    )
```

- [ ] **Step 6: Update HTML assertions in test_sender.py**

Replace `test_build_html_email_contains_summary` (which asserts `executive_summary`):

```python
def test_build_html_email_contains_act_today():
    html = build_html_email(
        brief=make_brief(),
        today_events=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        template_dir="templates",
    )
    assert "Close Apex" in html
    assert "CrossFit Box had a demo" in html
    assert "All GTM metrics in range" in html
```

Keep `test_build_html_email_contains_no_open_loops_message`, `test_send_brief_email_*`, and `test_build_html_email_contains_feedback_footer` unchanged.

- [ ] **Step 7: Run tests to verify they fail for the right reason**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_brief.py tests/test_sender.py -v 2>&1 | head -50
```

Expected: failures because `BriefContent` still has old fields.

- [ ] **Step 8: Commit the failing tests**

```bash
git add tests/test_brief.py tests/test_sender.py
git commit -m "test: rewrite brief tests for 3-block BriefContent schema"
```

---

## Task 2: Rewrite BriefContent, SYSTEM_PROMPT, and generate_brief

**Files:**
- Modify: `processors/brief.py`

- [ ] **Step 1: Replace SYSTEM_PROMPT (lines 16–45)**

Replace the entire `SYSTEM_PROMPT` string with:

```python
SYSTEM_PROMPT = """\
You are an AI Chief of Staff for Trent Luecke — VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches) and founder of Vero (gym AI side project). You also help with his personal life, LinkedIn content, and a weekly content podcast.

Deliver a morning brief readable in ~2 minutes. Two blocks only (metric flags are pre-computed and not your responsibility).

act_today — everything that needs Trent today. Collapse priorities, watch-outs, drafts, meeting prep, and pipeline attention into one ruthlessly prioritized list. Max 7 items. Each item is a plain action sentence with context and urgency woven in naturally — no brackets, no source tags. Multi-day open issues and customer-facing problems are highest priority. Issues with age (from the Open Issues section) belong here as plain sentences: "The Midwest deal has been stalled 3 days — follow up today." Omit if genuinely nothing to do.

what_moved — read-only awareness of what changed since yesterday. Only restate items from the "What Moved Yesterday" section of the prompt. Do not invent or infer events not listed there. One plain sentence per item, past tense. If no events section was provided, return an empty list. Max 7 items.

Respond ONLY in JSON with these exact keys:
{
  "act_today": ["action items as plain sentences — context and urgency woven in"],
  "what_moved": ["read-only awareness items, past tense, one sentence each"]
}
"""
```

- [ ] **Step 2: Replace BriefContent dataclass (lines 48–58)**

```python
@dataclass
class BriefContent:
    act_today: list[str] = field(default_factory=list)
    what_moved: list[str] = field(default_factory=list)
    metric_flags: list[str] = field(default_factory=list)
```

- [ ] **Step 3: Add what_moved_context param to _build_prompt() (line 61)**

Add `what_moved_context: str = ""` as the last parameter of `_build_prompt()`:

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
    memory_context: str = "",
    captures_context: str = "",
    brief_feedback_context: str = "",
    brief_prefs_context: str = "",
    storage=None,
    what_moved_context: str = "",
) -> str:
```

- [ ] **Step 4: Inject what_moved_context into the prompt body**

In `_build_prompt()`, add this block just before the pipeline_attention section (after the gym_scout section around line 194):

```python
    if what_moved_context and what_moved_context.strip():
        sections += [what_moved_context, ""]
```

- [ ] **Step 5: Update generate_brief() signature (line 199)**

Add two new parameters at the end of the signature:

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
    memory_context: str = "",
    captures_context: str = "",
    brief_feedback_context: str = "",
    brief_prefs_context: str = "",
    storage=None,
    metric_flags: list[str] = None,
    what_moved_context: str = "",
) -> BriefContent:
```

- [ ] **Step 6: Pass what_moved_context through to _build_prompt()**

In the `_build_prompt()` call inside `generate_brief()` (around line 222), add:

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
        memory_context=memory_context,
        captures_context=captures_context,
        brief_feedback_context=brief_feedback_context,
        brief_prefs_context=brief_prefs_context,
        storage=storage,
        what_moved_context=what_moved_context,
    )
```

- [ ] **Step 7: Replace the BriefContent construction at the bottom of generate_brief() (lines 254–264)**

```python
    return BriefContent(
        act_today=data.get("act_today", []),
        what_moved=data.get("what_moved", []),
        metric_flags=metric_flags or [],
    )
```

- [ ] **Step 8: Run tests**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_brief.py tests/test_sender.py -v 2>&1 | tail -30
```

Expected: `test_brief.py` passes. `test_sender.py` has template-related failures (template still has old fields) — those fix in Task 6.

- [ ] **Step 9: Commit**

```bash
git add processors/brief.py
git commit -m "feat: collapse BriefContent to 3 fields (act_today, what_moved, metric_flags)"
```

---

## Task 3: Write failing tests for what_moved, then implement processors/what_moved.py

**Files:**
- Create: `tests/test_what_moved.py`
- Create: `processors/what_moved.py`

- [ ] **Step 1: Create tests/test_what_moved.py**

```python
import pytest
from datetime import date
from processors.what_moved import build_what_moved_context, WHAT_MOVED_CAP
from unittest.mock import MagicMock


def _make_transcript(call_type: str, start_at: str, participants: list[str], summary: str):
    t = MagicMock()
    t.call_type = call_type
    t.start_at = start_at
    t.participants = participants
    t.summary = summary
    return t


def _make_onboarding(page_id: str, customer_name: str, status: str, current_phase: str = "Phase 1"):
    return {"page_id": page_id, "customer_name": customer_name, "status": status, "current_phase": current_phase}


def _make_lead(name: str, status: str = "Demo Scheduled"):
    return {"name": name, "status": status, "last_contacted": None}


def test_returns_empty_string_when_no_events():
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_includes_cancellation_from_yesterday():
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/4", "account_name": "Iron Works", "reason": "budget"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Iron Works" in result
    assert "budget" in result


def test_excludes_cancellation_not_from_yesterday():
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/1", "account_name": "Old Gym", "reason": "price"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_includes_unhosted_demo_from_yesterday():
    t = _make_transcript(
        call_type="demo",
        start_at="2026-06-04T15:00:00Z",
        participants=["Alex Smith"],
        summary="Strong interest in OS pricing.",
    )
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[t],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Alex Smith" in result
    assert "Strong interest" in result


def test_excludes_non_demo_avoma_call():
    t = _make_transcript(
        call_type="onboarding",
        start_at="2026-06-04T15:00:00Z",
        participants=["Alex Smith"],
        summary="Phase 1 complete.",
    )
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[t],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_excludes_demo_not_from_yesterday():
    t = _make_transcript(
        call_type="demo",
        start_at="2026-06-02T15:00:00Z",
        participants=["Old Lead"],
        summary="Old demo.",
    )
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[t],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_detects_new_onboarding_entry():
    current = [_make_onboarding("abc", "Apex Gym", "In Progress", "Phase 1 — Initial Setup")]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=current,
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Apex Gym" in result
    assert "entered onboarding" in result


def test_detects_onboarding_phase_change():
    prev = [_make_onboarding("abc", "Apex Gym", "In Progress", "Phase 1 — Initial Setup")]
    current = [_make_onboarding("abc", "Apex Gym", "In Progress", "Phase 2 — Member Profile Upload")]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=current,
        onboarding_prev=prev,
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "Apex Gym" in result
    assert "Phase 1" in result
    assert "Phase 2" in result


def test_no_event_for_unchanged_onboarding():
    entry = _make_onboarding("abc", "Apex Gym", "In Progress", "Phase 1 — Initial Setup")
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[entry],
        onboarding_prev=[entry],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_detects_new_pipeline_lead():
    current = [_make_lead("New Gym LLC", "Demo Scheduled")]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=current,
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "New Gym LLC" in result
    assert "entered pipeline" in result


def test_existing_pipeline_lead_not_included():
    lead = _make_lead("Existing Gym", "Demo Scheduled")
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[lead],
        pipeline_prev=[lead],
        today=date(2026, 6, 5),
    )
    assert result == ""


def test_cap_is_enforced():
    # 10 new pipeline leads — should be capped at WHAT_MOVED_CAP
    current = [_make_lead(f"Gym {i}") for i in range(10)]
    result = build_what_moved_context(
        cancellations={"entries": []},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=current,
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    lines = [l for l in result.split("\n") if l.strip().startswith("Gym")]
    assert len(lines) == WHAT_MOVED_CAP


def test_priority_order_cancellation_before_lead():
    current = [_make_lead("New Gym LLC")]
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/4", "account_name": "Iron Works", "reason": "budget"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=current,
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    iron_pos = result.index("Iron Works")
    gym_pos = result.index("New Gym LLC")
    assert iron_pos < gym_pos


def test_includes_header_when_events_present():
    result = build_what_moved_context(
        cancellations={"entries": [{"date": "6/4", "account_name": "Iron Works", "reason": "budget"}]},
        avoma_transcripts=[],
        onboarding_current=[],
        onboarding_prev=[],
        pipeline_current=[],
        pipeline_prev=[],
        today=date(2026, 6, 5),
    )
    assert "What Moved Yesterday" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_what_moved.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'processors.what_moved'`

- [ ] **Step 3: Create processors/what_moved.py**

```python
from datetime import date, datetime, timedelta

WHAT_MOVED_CAP = 7


def _parse_date_m_d(date_str: str, year: int) -> date | None:
    try:
        parts = date_str.strip().split("/")
        return date(year, int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def _is_yesterday_m_d(date_str: str, today: date) -> bool:
    d = _parse_date_m_d(date_str, today.year)
    return d is not None and (today - d).days == 1


def _is_yesterday_iso(iso_str: str, today: date) -> bool:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.date() == today - timedelta(days=1)
    except (ValueError, TypeError):
        return False


def build_what_moved_context(
    cancellations: dict,
    avoma_transcripts: list,
    onboarding_current: list[dict],
    onboarding_prev: list[dict],
    pipeline_current: list[dict],
    pipeline_prev: list[dict],
    today: date | None = None,
) -> str:
    """Build What Moved context section for the brief prompt.

    Returns a formatted string for injection into _build_prompt(), or empty
    string if no events found. Capped at WHAT_MOVED_CAP items sorted by
    priority (1=cancellation, 2=demo, 3=onboarding, 4=new lead) then
    oldest-to-newest for overflow ordering.
    """
    _today = today or date.today()
    events: list[dict] = []

    # 1. Cancellations (yesterday's date, M/D format)
    for entry in cancellations.get("entries", []):
        if _is_yesterday_m_d(entry.get("date", ""), _today):
            events.append({
                "priority": 1,
                "sort_key": entry.get("date", ""),
                "text": f"{entry.get('account_name', 'Unknown')} cancelled — {entry.get('reason', 'no reason given')}",
            })

    # 2. Unhosted demos from Avoma (yesterday only, call_type == "demo")
    for t in avoma_transcripts:
        if t.call_type == "demo" and _is_yesterday_iso(t.start_at, _today):
            participant = next((p for p in t.participants if p), "unknown participant")
            events.append({
                "priority": 2,
                "sort_key": t.start_at,
                "text": f"{participant} had a demo — {t.summary}",
            })

    # 3. Onboarding stage/phase changes (snapshot diff)
    prev_map = {r["page_id"]: r for r in onboarding_prev}
    for r in onboarding_current:
        prev = prev_map.get(r.get("page_id", ""))
        if prev is None:
            events.append({
                "priority": 3,
                "sort_key": r.get("start_date") or _today.isoformat(),
                "text": f"{r['customer_name']} entered onboarding ({r.get('status', 'unknown')})",
            })
        elif prev.get("status") != r.get("status") or prev.get("current_phase") != r.get("current_phase"):
            old = prev.get("current_phase") or prev.get("status", "unknown")
            new = r.get("current_phase") or r.get("status", "unknown")
            events.append({
                "priority": 3,
                "sort_key": _today.isoformat(),
                "text": f"{r['customer_name']} advanced: {old} → {new}",
            })

    # 4. New pipeline leads (name not in previous snapshot)
    prev_names = {r.get("name", "").strip().lower() for r in pipeline_prev}
    for r in pipeline_current:
        name = r.get("name", "").strip()
        if name and name.lower() not in prev_names:
            events.append({
                "priority": 4,
                "sort_key": r.get("last_contacted") or _today.isoformat(),
                "text": f"{name} entered pipeline ({r.get('status', 'unknown')})",
            })

    # Sort: priority first, then chronological (oldest first for cap overflow)
    events.sort(key=lambda e: (e["priority"], e["sort_key"] or ""))
    capped = events[:WHAT_MOVED_CAP]

    if not capped:
        return ""

    lines = [
        "## What Moved Yesterday (read-only — restate these as-is, do not add items)",
        *[f"  {e['text']}" for e in capped],
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_what_moved.py -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add processors/what_moved.py tests/test_what_moved.py
git commit -m "feat: add processors/what_moved.py with build_what_moved_context()"
```

---

## Task 4: Rewrite email template and create dashboard template

**Files:**
- Modify: `templates/morning_brief.html`
- Create: `templates/dashboard.html`
- Modify: `outputs/dashboard.py`
- Modify: `tests/test_sender.py` (sender test assertions)

- [ ] **Step 1: Rewrite templates/morning_brief.html**

Replace the entire file with the 3-block email layout:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 680px; margin: 0 auto; color: #1a1a1a; background: #f9f9f9; }
  .header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 28px 32px; border-radius: 8px 8px 0 0; }
  .header h1 { margin: 0; font-size: 22px; font-weight: 600; }
  .header .date { margin: 4px 0 0; font-size: 14px; opacity: 0.75; }
  .body { background: white; padding: 28px 32px; border-radius: 0 0 8px 8px; border: 1px solid #e5e5e5; border-top: none; }
  .section { margin-bottom: 28px; }
  .section h2 { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #888; margin: 0 0 12px; }
  .action-list { list-style: none; padding: 0; margin: 0; }
  .action-list li { padding: 8px 12px; margin-bottom: 6px; background: #fafafa; border: 1px solid #e5e5e5; border-radius: 6px; font-size: 14px; }
  .action-list li::before { content: "▸ "; color: #4a6cf7; font-weight: bold; }
  .moved-list { list-style: none; padding: 0; margin: 0; }
  .moved-list li { padding: 6px 12px; margin-bottom: 4px; font-size: 14px; color: #444; border-left: 2px solid #e0e0e0; }
  .flag-breach { padding: 8px 12px; margin-bottom: 6px; background: #fff8f0; border-left: 3px solid #ff9800; border-radius: 0 6px 6px 0; font-size: 14px; }
  .flag-ok { padding: 6px 12px; font-size: 13px; color: #888; }
  .footer { text-align: center; padding: 16px; font-size: 12px; color: #aaa; }
</style>
</head>
<body>
<div class="header">
  <h1>☀️ Morning Brief</h1>
  <div class="date">{{ date_str }} · Generated {{ generated_at }}</div>
</div>
<div class="body">

  <div class="section">
    <h2>Act Today</h2>
    <ul class="action-list">
      {% for item in brief.act_today %}
      <li>{{ item }}</li>
      {% endfor %}
      {% if not brief.act_today %}
      <li style="color:#aaa">Nothing urgent today</li>
      {% endif %}
    </ul>
  </div>

  {% if brief.what_moved %}
  <div class="section">
    <h2>What Moved</h2>
    <ul class="moved-list">
      {% for item in brief.what_moved %}
      <li>{{ item }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  <div class="section">
    <h2>Metric Flags</h2>
    {% for flag in brief.metric_flags %}
      {% if "All GTM metrics in range" in flag %}
      <div class="flag-ok">{{ flag }}</div>
      {% else %}
      <div class="flag-breach">{{ flag }}</div>
      {% endif %}
    {% endfor %}
    {% if not brief.metric_flags %}
    <div class="flag-ok">No metric data available</div>
    {% endif %}
  </div>

</div>
<div class="footer">Generated by AI Chief of Staff · {{ generated_at }}</div>
</body>
</html>
```

- [ ] **Step 2: Create templates/dashboard.html**

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>GTM Dashboard</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; color: #1a1a1a; background: #f9f9f9; padding: 20px; }
  .header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 28px 32px; border-radius: 8px 8px 0 0; }
  .header h1 { margin: 0; font-size: 22px; font-weight: 600; }
  .header .date { margin: 4px 0 0; font-size: 14px; opacity: 0.75; }
  .body { background: white; padding: 28px 32px; border-radius: 0 0 8px 8px; border: 1px solid #e5e5e5; border-top: none; }
  .section { margin-bottom: 32px; }
  .section h2 { font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #888; margin: 0 0 12px; border-bottom: 1px solid #f0f0f0; padding-bottom: 8px; }
  .action-list { list-style: none; padding: 0; margin: 0; }
  .action-list li { padding: 8px 12px; margin-bottom: 6px; background: #fafafa; border: 1px solid #e5e5e5; border-radius: 6px; font-size: 14px; }
  .action-list li::before { content: "▸ "; color: #4a6cf7; font-weight: bold; }
  .moved-list { list-style: none; padding: 0; margin: 0; }
  .moved-list li { padding: 6px 12px; margin-bottom: 4px; font-size: 14px; color: #444; border-left: 2px solid #e0e0e0; }
  .metric-table { width: 100%; border-collapse: collapse; font-size: 14px; }
  .metric-table th { text-align: left; padding: 8px 12px; background: #f5f5f5; border-bottom: 2px solid #e5e5e5; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: #666; }
  .metric-table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; }
  .metric-table tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .badge-breach { background: #fff3e0; color: #e65100; }
  .badge-ok { background: #e8f5e9; color: #2e7d32; }
  .badge-stale { background: #fff8e1; color: #f57f17; }
  .badge-na { background: #f5f5f5; color: #9e9e9e; }
  .event-row { display: flex; align-items: baseline; padding: 6px 0; border-bottom: 1px solid #f0f0f0; font-size: 14px; }
  .event-time { width: 80px; flex-shrink: 0; color: #888; font-size: 13px; }
  .project-row { padding: 6px 0; font-size: 14px; border-bottom: 1px solid #f5f5f5; }
  .status-badge { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; margin-left: 6px; background: #e8eaf6; color: #3949ab; }
  .footer { text-align: center; padding: 16px; font-size: 12px; color: #aaa; margin-top: 20px; }
</style>
</head>
<body>
<div class="header">
  <h1>📊 GTM Dashboard</h1>
  <div class="date">{{ date_str }} · Generated {{ generated_at }}</div>
</div>
<div class="body">

  <div class="section">
    <h2>Act Today</h2>
    <ul class="action-list">
      {% for item in brief.act_today %}
      <li>{{ item }}</li>
      {% endfor %}
      {% if not brief.act_today %}
      <li style="color:#aaa">Nothing urgent today</li>
      {% endif %}
    </ul>
  </div>

  {% if brief.what_moved %}
  <div class="section">
    <h2>What Moved</h2>
    <ul class="moved-list">
      {% for item in brief.what_moved %}
      <li>{{ item }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  {% if metric_results %}
  <div class="section">
    <h2>GTM Metrics</h2>
    <table class="metric-table">
      <thead>
        <tr>
          <th>Metric</th>
          <th>Current</th>
          <th>Target</th>
          <th>Status</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody>
        {% for r in metric_results %}
        <tr>
          <td>{{ r.label }}</td>
          <td>{{ r.current if r.current is not none else "—" }}</td>
          <td>{{ r.target if r.target is not none else "—" }}</td>
          <td>
            {% if r.stale %}
              <span class="badge badge-stale">Stale</span>
            {% elif r.breach %}
              <span class="badge badge-breach">Breach</span>
            {% elif r.current is not none %}
              <span class="badge badge-ok">OK</span>
            {% else %}
              <span class="badge badge-na">N/A</span>
            {% endif %}
          </td>
          <td style="color:#666; font-size:13px">
            {% if r.stale %}{{ r.stale_reason }}
            {% elif r.breach %}{{ r.breach_reason }}
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  <div class="section">
    <h2>Today's Calendar</h2>
    {% if today_events %}
      {% for e in today_events %}
      <div class="event-row">
        <span class="event-time">{{ e.start.strftime('%I:%M%p').lstrip('0') }}</span>
        <span>{{ e.summary }}</span>
      </div>
      {% endfor %}
    {% else %}
      <span style="color:#aaa; font-size:14px">No events today</span>
    {% endif %}
  </div>

  <div class="section">
    <h2>Active Projects</h2>
    {% for p in projects %}
    <div class="project-row">
      <strong>{{ p.name }}</strong>
      <span class="status-badge">{{ p.status }}</span>
      {% if p.next_step %}<div style="color:#666; font-size:13px; margin-top:2px">→ {{ p.next_step }}</div>{% endif %}
    </div>
    {% endfor %}
    {% if not projects %}<span style="color:#aaa; font-size:14px">No active projects</span>{% endif %}
  </div>

</div>
<div class="footer">AI Chief of Staff · {{ generated_at }}</div>
</body>
</html>
```

- [ ] **Step 3: Update outputs/dashboard.py to use dashboard.html**

Replace the entire `outputs/dashboard.py` file:

```python
import os
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from collectors.calendar import CalendarEvent
from collectors.local_data import Project, RecurringTask
from processors.brief import BriefContent
from processors.loops import LoopSummary


def write_dashboard(
    brief: BriefContent,
    today_events: list[CalendarEvent],
    projects: list[Project],
    due_tasks: list[RecurringTask],
    loop_summary: LoopSummary,
    output_path: str = "output/dashboard.html",
    template_dir: str = "templates",
    metric_results: list = None,
) -> None:
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("dashboard.html")
    now = datetime.now()
    html = template.render(
        brief=brief,
        today_events=today_events,
        projects=projects,
        due_tasks=due_tasks,
        loop_summary=loop_summary,
        metric_results=metric_results or [],
        date_str=now.strftime("%A, %B ") + str(now.day),
        generated_at=now.strftime("%I:%M %p").lstrip("0"),
    )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
```

- [ ] **Step 4: Run sender tests**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_sender.py -v 2>&1 | tail -20
```

Expected: all pass (template now has `act_today`, `what_moved`, `metric_flags` fields matching new BriefContent).

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_brief.py tests/test_sender.py tests/test_what_moved.py -v 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add templates/morning_brief.html templates/dashboard.html outputs/dashboard.py
git commit -m "feat: 3-block email template; split dashboard template; update write_dashboard()"
```

---

## Task 5: Add leads_data collection to pipeline.py

**Files:**
- Modify: `pipeline.py`

This adds `leads_data` to `CollectedData` and calls `fetch_leads_mtd()` in the sheets block so `evaluate_metrics()` can evaluate the leads pace metric with staleness detection.

- [ ] **Step 1: Add leads_data field to CollectedData**

In `pipeline.py`, find the `CollectedData` dataclass (around line 85, in the `# Sheets` block). Add `leads_data` after `demos_data`:

```python
    # Sheets
    sales_data: dict | None = None
    demos_data: dict | None = None
    leads_data: dict | None = None
    cancellations: dict = field(default_factory=lambda: {"count": 0, "entries": []})
```

- [ ] **Step 2: Add fetch_leads_mtd() call in the sheets collection block**

Find the sheets collection block (around line 475). The block currently calls `fetch_cancellations_mtd`, `fetch_sales_mtd`, and `fetch_demos_mtd`. After the `demos_data` fetch (around line 500), add:

```python
                    kpi_sheet_id = sheets_cfg.get("kpi_spreadsheet_id", "")
                    kpi_leads_tab = sheets_cfg.get("kpi_leads_tab_name", "Leads")
                    if kpi_sheet_id:
                        data.leads_data = fetch_leads_mtd(sheets_svc, kpi_sheet_id, kpi_leads_tab)
                        print(f"   Leads MTD: {data.leads_data['count']} lead(s)")
```

Also update the import line (around line 488) to include `fetch_leads_mtd`:

```python
                    from collectors.sheets import fetch_cancellations_mtd, fetch_sales_mtd, fetch_demos_mtd, fetch_leads_mtd, month_label
```

- [ ] **Step 3: Verify the code parses correctly**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -c "import pipeline; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pipeline.py
git commit -m "feat: collect leads_data from KPI sheet for evaluate_metrics() wiring"
```

---

## Task 6: Wire evaluate_metrics, build_what_moved_context, and snapshot diffs in pipeline.py

**Files:**
- Modify: `pipeline.py`

This is the core wiring task. All changes are in `generate_and_deliver()`.

- [ ] **Step 1: Add helper function _format_metric_flags() near the top of generate_and_deliver()**

Add this function at module level in `pipeline.py`, after the imports and before `generate_and_deliver()`:

```python
def _format_metric_flags(metric_results: list, dashboard_path: str) -> list[str]:
    """Format MetricResult objects into brief-ready flag strings."""
    breached = [r for r in metric_results if r.breach]
    stale = [r for r in metric_results if r.stale and not r.breach]
    if not breached and not stale:
        return [f"All GTM metrics in range — dashboard: {dashboard_path}"]
    flags = []
    horizon_label = {"next-month": "next month tracking", "this-month": "this month"}
    for r in breached:
        label = horizon_label.get(r.horizon, r.horizon)
        flags.append(f"{r.label}: {r.breach_reason} ({label})")
    for r in stale:
        flags.append(f"{r.label}: {r.stale_reason}")
    return flags
```

- [ ] **Step 2: Add evaluate_metrics() call in generate_and_deliver(), before the brief generation block**

In `generate_and_deliver()` (around line 741, just before the `# Brief generation` comment), add:

```python
        # GTM metrics evaluation
        _metric_results = []
        _metric_flags = []
        try:
            from lib.gtm_metrics import evaluate_metrics
            from collectors.onboarding import load_onboarding_active
            gtm_cfg = config.get("gtm", {})
            onboarding_cfg = config.get("onboarding", {})
            active_statuses = onboarding_cfg.get("active_statuses", ["In Progress", "Awaiting Customer", "Ready to Go Live"])
            onboarding_cache_path = onboarding_cfg.get("cache_path", "data/onboarding_cache.json")
            onboarding_active = load_onboarding_active(onboarding_cache_path, active_statuses)
            _metric_results = evaluate_metrics(
                leads_data=collected.leads_data,
                demos_data=collected.demos_data,
                sales_data=collected.sales_data,
                onboarding_active=onboarding_active,
                cancellations=collected.cancellations if collected.cancellations.get("count", 0) > 0 else None,
                cfg=gtm_cfg,
            )
            _metric_flags = _format_metric_flags(_metric_results, config.get("dashboard_path", "output/dashboard.html"))
        except Exception as e:
            print(f"⚠️  Metric evaluation error (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 3: Add build_what_moved_context() call, also before brief generation**

Immediately after the metric evaluation block above, add:

```python
        # What Moved context (snapshot diff)
        _what_moved_context = ""
        try:
            import json as _json
            from processors.what_moved import build_what_moved_context
            onboarding_cache_path = config.get("onboarding", {}).get("cache_path", "data/onboarding_cache.json")
            try:
                with open(onboarding_cache_path) as _f:
                    _onboarding_all = _json.load(_f).get("records", [])
            except (FileNotFoundError, _json.JSONDecodeError):
                _onboarding_all = []
            _onboarding_prev = storage.read_json("state/onboarding_prev.json") or []
            try:
                with open("data/pipeline_cache.json") as _f:
                    _pipeline_all = _json.load(_f).get("leads", [])
            except (FileNotFoundError, _json.JSONDecodeError):
                _pipeline_all = []
            _pipeline_prev = storage.read_json("state/pipeline_prev.json") or []
            _what_moved_context = build_what_moved_context(
                cancellations=collected.cancellations,
                avoma_transcripts=collected.avoma_transcripts,
                onboarding_current=_onboarding_all,
                onboarding_prev=_onboarding_prev,
                pipeline_current=_pipeline_all,
                pipeline_prev=_pipeline_prev,
            )
            # Snapshot writes live here on the success path — not after save_snapshot().
            # json.load() is atomic (complete list or exception), so _onboarding_all and
            # _pipeline_all are always either [] or fully valid when we reach this line.
            if _onboarding_all:
                storage.write_json("state/onboarding_prev.json", _onboarding_all)
            if _pipeline_all:
                storage.write_json("state/pipeline_prev.json", _pipeline_all)
        except Exception as e:
            print(f"⚠️  What Moved context error (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 4: Pass metric_flags and what_moved_context into generate_brief()**

In the `generate_brief()` call (around line 744), add the two new keyword arguments:

```python
                brief = generate_brief(
                    api_key=api_key,
                    model=config["ai_model"],
                    today_events=collected.today_events,
                    tomorrow_events=collected.tomorrow_events,
                    email_threads=collected.email_threads,
                    projects=collected.projects,
                    due_tasks=collected.due_tasks,
                    loop_summary=ctx.loop_summary,
                    open_issues=collected.open_issues,
                    drafts=ctx.todays_drafts,
                    meeting_prep=ctx.meeting_prep,
                    inbox_text=collected.inbox_text,
                    attention_leads=collected.attention_leads,
                    gym_scout_leads=collected.gym_scout_leads,
                    people_context=ctx.people_context,
                    memory_context=ctx.memory_context,
                    captures_context=ctx.captures_context,
                    brief_feedback_context=ctx.brief_feedback_context,
                    brief_prefs_context=ctx.brief_prefs_context,
                    storage=storage,
                    metric_flags=_metric_flags,
                    what_moved_context=_what_moved_context,
                )
```

- [ ] **Step 5: Update the brief error fallback (around line 769)**

The fallback `BriefContent(...)` call uses old fields. Replace it:

```python
                brief = BriefContent(
                    act_today=[
                        "Brief generation failed — check logs.",
                        f"Retry: python main.py --no-email",
                    ],
                    metric_flags=[f"Brief error: {str(e)[:150]}"],
                )
```

- [ ] **Step 6: Update system-warning injection sites (around lines 785, 791, 798)**

The code injects system warnings into `brief.watch_outs` — a field that no longer exists. Replace each with `act_today` inserts:

Replace (line ~785):
```python
            brief.watch_outs = [ctx.memory_cold_start_msg] + (brief.watch_outs or [])
```
With:
```python
            brief.act_today.insert(0, ctx.memory_cold_start_msg)
```

Replace (line ~791):
```python
            brief.watch_outs = [_cal_warn] + (brief.watch_outs or [])
```
With:
```python
            brief.act_today.insert(0, _cal_warn)
```

Replace (line ~798):
```python
            brief.watch_outs.append(_stale_warn)
```
With:
```python
            brief.act_today.append(_stale_warn)
```

- [ ] **Step 7: Pass metric_results into write_dashboard()**

Find the `write_dashboard()` call (around line 804). Add `metric_results=_metric_results`:

```python
        write_dashboard(
            brief=brief,
            today_events=collected.today_events,
            projects=collected.projects,
            due_tasks=collected.due_tasks,
            loop_summary=ctx.loop_summary,
            output_path=config["dashboard_path"],
            metric_results=_metric_results,
        )
```

- [ ] **Step 8: Verify the module parses correctly**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -c "import pipeline; print('OK')"
```

Expected: `OK`

- [ ] **Step 10: Run full test suite**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
pytest tests/test_brief.py tests/test_sender.py tests/test_what_moved.py -v 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add pipeline.py
git commit -m "feat: wire evaluate_metrics + build_what_moved_context into brief pipeline; write prev snapshots"
```

---

## Self-Review

After writing this plan, checking spec coverage and type consistency.

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| BriefContent → 3 fields (act_today, what_moved, metric_flags) | Task 1, 2 |
| SYSTEM_PROMPT updated with 3-key JSON | Task 2 |
| Templates updated for 3-block layout | Task 4 |
| what_moved — confirmed 4 sources, capped at 7, oldest-first | Task 3 |
| what_moved — cancellations from yesterday | Task 3 |
| what_moved — unhosted demos, previous day only | Task 3 |
| what_moved — onboarding stage advance via snapshot diff | Task 3 |
| what_moved — new pipeline lead via snapshot diff | Task 3 |
| metric_flags from evaluate_metrics(), only breached | Task 6 |
| metric_flags all-clear line if no breaches | Task 6 (_format_metric_flags) |
| evaluate_metrics() receives FULL source objects (leads_data with entries[], cancellations with entries[]) | Task 5 (leads_data collection), Task 6 (pass cancellations with entries) |
| leads staleness — suppressed flag, staleness surfaced | handled by evaluate_metrics() (doc 1 owns); _format_metric_flags renders stale_reason |
| System warnings (calendar, pipeline stale, memory cold start) move to act_today | Task 6, step 6 |
| Reply-to-feedback footer preserved | unchanged in outputs/sender.py |
| brief_prefs_context injection preserved | unchanged param in generate_brief() |
| Thread handling preserved | unchanged in outputs/sender.py |
| kpi_snapshot writes preserved | unchanged (not removed) |
| Dashboard template separated from email template | Task 4 |
| Dashboard gets full metric table | Task 4 (dashboard.html) |
| First run after deploy: no diff items (silent) | handled by empty prev snapshots returning "" from build_what_moved_context |
| Backlog: rep_escalations field on AvomaTranscript | **Not in plan** — confirmed deferred |

**Type consistency check:**
- `BriefContent.act_today: list[str]` — used consistently in Task 2, Task 6 fallback, Task 6 warning inserts, Task 4 template
- `BriefContent.metric_flags: list[str]` — set in generate_brief() from `metric_flags` param; formatted in `_format_metric_flags()` as `list[str]`
- `build_what_moved_context()` returns `str` — passed as `what_moved_context: str` to `generate_brief()` then to `_build_prompt()`
- `_metric_results` is `list[MetricResult]` — passed to `write_dashboard()` as `metric_results: list` (typed loosely to avoid import in signature)
- `_onboarding_all` and `_pipeline_all` are assigned via `json.load()` (atomic — complete list or exception, never partial). Snapshot writes are co-located at the end of the What Moved try block so they only execute on the success path and never read cross-block state.

**Placeholder scan:** No TBD, TODO, or "similar to" references found. All code blocks are complete.

---

## Backlog

- `rep_escalations: list[str]` on `AvomaTranscript` — extract "I'll need to ask/confirm" signals from rep utterances in demo transcripts. Requires: new field on the dataclass, updated extraction tool schema in `collectors/avoma.py`, updated Claude prompt instructions. Wire into `what_moved` event type #5 once infrastructure exists.
