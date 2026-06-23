# Open Loops in the Daily Brief — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic "Open Loops" section to the morning brief email that surfaces every open meeting thread, bucketed into TODAY (meetings on today's calendar) and OTHER, grouped by meeting, each loop tagged with owner and age.

**Architecture:** A pure function in `lib/meetings.py` does all bucketing/owner-resolution/aging/capping. A thin wiring function in `pipeline.py` reads the git-anchored local stores (meetings + people registry) and the today's-meeting matcher, then calls the pure function. The result is attached to `BriefContent.open_loops` and rendered verbatim by the Jinja email template — bypassing the LLM, exactly like `metric_flags`.

**Tech Stack:** Python 3, Jinja2 templates, pytest.

## Global Constraints

- The brief LLM call only emits `act_today` / `what_moved`; open loops MUST render deterministically via the template, never through the LLM prompt. (spec: "Why this is a deterministic section")
- Meeting + people data is git-anchored — read it from the **local working tree** (`LocalStorage("data")` / `replay_local()`), NOT from `build_storage`/R2. (matches existing `build_meeting_prep`)
- The pure function takes an explicit `today: datetime.date` — no hidden `now()`. (`lib/meetings.py` determinism rule)
- Owner resolution: `person_id` → `canonical_name` via `people_registry.json`; unresolved id passes through as-is; null `person_id` → no owner.
- OTHER bucket capped at the 10 most recently created loops; overflow → `other_more` count. TODAY never capped.
- Within a meeting, loops sort oldest-first (most stale on top). Age `0` → "today", else `{N}d`.
- Zero open loops → section omitted entirely.

---

### Task 1: `open_loops_buckets` pure function

**Files:**
- Modify: `lib/meetings.py` (add function + a small `_age_days` helper after `last_session`, ~line 109)
- Test: `tests/test_meetings_lib.py` (append)

**Interfaces:**
- Consumes: nothing (pure; operates on already-replayed `state` dicts as produced by `replay_meetings_content`)
- Produces: `open_loops_buckets(state: dict, meeting_names: dict, today_ids: set, person_names: dict, today: datetime.date, other_cap: int = 10) -> dict`
  returning `{"today": [group], "other": [group], "other_more": int}` where each `group` is `{"meeting_name": str, "loops": [{"text": str, "owner": str|None, "age_days": int}]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_meetings_lib.py`:

```python
from datetime import date


def _mtg(slug, threads):
    return {"id": slug, "agenda": [], "threads": threads, "sessions": []}


def _thread(tid, text, person_id=None, closed=False, created_ts="2026-06-01T10:00:00"):
    return {"thread_id": tid, "text": text, "person_id": person_id,
            "task_id": None, "closed": closed, "closed_date": None, "created_ts": created_ts}


def test_open_loops_empty():
    out = m.open_loops_buckets({}, {}, set(), {}, date(2026, 6, 23))
    assert out == {"today": [], "other": [], "other_more": 0}


def test_open_loops_today_vs_other_and_closed_excluded():
    state = {
        "rev_dept_heads": _mtg("rev_dept_heads", [
            _thread("th-1", "quota model", person_id="quinn-kastle"),
            _thread("th-2", "done thing", closed=True),
        ]),
        "luke_1on1": _mtg("luke_1on1", [_thread("th-3", "loop luke in")]),
    }
    names = {"rev_dept_heads": "Rev Dept Heads", "luke_1on1": "Luke 1:1"}
    persons = {"quinn-kastle": "Quinn Kastle"}
    out = m.open_loops_buckets(state, names, {"rev_dept_heads"}, persons, date(2026, 6, 23))
    assert out["today"] == [
        {"meeting_name": "Rev Dept Heads",
         "loops": [{"text": "quota model", "owner": "Quinn Kastle", "age_days": 22}]}
    ]
    assert out["other"] == [
        {"meeting_name": "Luke 1:1",
         "loops": [{"text": "loop luke in", "owner": None, "age_days": 22}]}
    ]
    assert out["other_more"] == 0


def test_open_loops_owner_unresolved_passthrough():
    state = {"x": _mtg("x", [_thread("th-1", "t", person_id="ghost-id")])}
    out = m.open_loops_buckets(state, {"x": "X Meeting"}, set(), {}, date(2026, 6, 23))
    assert out["other"][0]["loops"][0]["owner"] == "ghost-id"


def test_open_loops_slug_name_fallback():
    state = {"os_sit_down": _mtg("os_sit_down", [_thread("th-1", "t")])}
    out = m.open_loops_buckets(state, {}, set(), {}, date(2026, 6, 23))
    assert out["other"][0]["meeting_name"] == "Os Sit Down"


def test_open_loops_age_today():
    state = {"x": _mtg("x", [_thread("th-1", "t", created_ts="2026-06-23T08:00:00")])}
    out = m.open_loops_buckets(state, {"x": "X"}, set(), {}, date(2026, 6, 23))
    assert out["other"][0]["loops"][0]["age_days"] == 0


def test_open_loops_other_cap_keeps_recent_displays_oldest_first():
    threads = [_thread(f"th-{i}", f"loop {i}", created_ts=f"2026-06-{i + 1:02d}T10:00:00")
               for i in range(13)]
    state = {"x": _mtg("x", threads)}
    out = m.open_loops_buckets(state, {"x": "X"}, set(), {}, date(2026, 7, 1), other_cap=10)
    kept = out["other"][0]["loops"]
    assert len(kept) == 10
    assert out["other_more"] == 3
    # cap drops the 3 oldest by creation (loop 0,1,2); display is oldest-first within the kept set
    assert kept[0]["text"] == "loop 3"
    assert kept[-1]["text"] == "loop 12"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_meetings_lib.py -k open_loops -v`
Expected: FAIL — `AttributeError: module 'lib.meetings' has no attribute 'open_loops_buckets'`

- [ ] **Step 3: Write the implementation**

In `lib/meetings.py`, after `last_session` (~line 109), add:

```python
def _age_days(created_ts: str, today) -> int:
    """Whole days between a thread's creation date and `today` (>= 0)."""
    from datetime import date
    try:
        created = date.fromisoformat(created_ts[:10])
    except (ValueError, TypeError):
        return 0
    return max(0, (today - created).days)


def open_loops_buckets(state, meeting_names, today_ids, person_names, today, other_cap=10):
    """Bucket open meeting threads for the daily brief.

    Returns {"today": [group], "other": [group], "other_more": int}, where each
    group is {"meeting_name": str, "loops": [{"text", "owner", "age_days"}]}.
    Loops within a meeting sort oldest-first. The OTHER bucket keeps the
    `other_cap` most recently created loops; the remainder count into other_more.
    `today` is a datetime.date. `person_names` maps person_id -> display name;
    unresolved ids pass through as-is, a null person_id yields owner None.
    """
    def owner_for(pid):
        if not pid:
            return None
        return person_names.get(pid, pid)

    today_pairs = {}   # meeting_name -> [(created_ts, loop)]
    other_flat = []    # [(created_ts, meeting_name, loop)]
    for slug, mtg in state.items():
        name = meeting_names.get(slug) or slug.replace("_", " ").title()
        for th in mtg.get("threads", []):
            if th.get("closed"):
                continue
            cts = th.get("created_ts", "")
            loop = {
                "text": th.get("text", ""),
                "owner": owner_for(th.get("person_id")),
                "age_days": _age_days(cts, today),
            }
            if slug in today_ids:
                today_pairs.setdefault(name, []).append((cts, loop))
            else:
                other_flat.append((cts, name, loop))

    def build_groups(name_to_pairs):
        groups = []
        for name in sorted(name_to_pairs):
            pairs = sorted(name_to_pairs[name], key=lambda p: p[0])  # oldest-first
            groups.append({"meeting_name": name, "loops": [p[1] for p in pairs]})
        return groups

    other_flat.sort(key=lambda t: t[0], reverse=True)  # most recent first
    kept = other_flat[:other_cap]
    other_more = len(other_flat) - len(kept)
    other_pairs = {}
    for cts, name, loop in kept:
        other_pairs.setdefault(name, []).append((cts, loop))

    return {
        "today": build_groups(today_pairs),
        "other": build_groups(other_pairs),
        "other_more": other_more,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_meetings_lib.py -k open_loops -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/meetings.py tests/test_meetings_lib.py
git commit -m "feat: open_loops_buckets pure function for brief open-loops section"
```

---

### Task 2: `BriefContent.open_loops` field + email template section

**Files:**
- Modify: `processors/brief.py:31-35` (add field to `BriefContent`)
- Modify: `templates/morning_brief.html` (new section after Act Today, ~line 40)
- Test: `tests/test_sender.py` (append render tests)

**Interfaces:**
- Consumes: the dict shape produced by `open_loops_buckets` (Task 1).
- Produces: `BriefContent.open_loops: dict` (default `{}`); a rendered `<div class="section">` with `<h2>Open Loops</h2>` present iff `open_loops.today` or `open_loops.other` is non-empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sender.py`:

```python
from outputs.sender import build_html_email
from processors.brief import BriefContent


def test_open_loops_section_renders():
    brief = BriefContent(act_today=["x"], open_loops={
        "today": [{"meeting_name": "Rev Dept Heads",
                   "loops": [{"text": "quota model", "owner": "Quinn Kastle", "age_days": 9}]}],
        "other": [{"meeting_name": "Luke 1:1",
                   "loops": [{"text": "loop luke", "owner": None, "age_days": 0}]}],
        "other_more": 3,
    })
    html = build_html_email(brief, [], [], [], {})
    assert "Open Loops" in html
    assert "Rev Dept Heads" in html
    assert "Quinn Kastle" in html
    assert "9d" in html
    assert "today</span>" in html          # age 0 -> "today"
    assert "+3 more open loops" in html


def test_open_loops_section_absent_when_empty():
    brief = BriefContent(act_today=["x"], open_loops={"today": [], "other": [], "other_more": 0})
    html = build_html_email(brief, [], [], [], {})
    assert "Open Loops" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sender.py -k open_loops -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'open_loops'`

- [ ] **Step 3: Add the field**

In `processors/brief.py`, in the `BriefContent` dataclass (currently ends at line 35 with `metric_flags`), add:

```python
@dataclass
class BriefContent:
    act_today: list[str] = field(default_factory=list)
    what_moved: list[str] = field(default_factory=list)
    metric_flags: list[str] = field(default_factory=list)
    open_loops: dict = field(default_factory=dict)
```

- [ ] **Step 4: Add the template section**

In `templates/morning_brief.html`, immediately after the Act Today section's closing `</div>` (after line 40, before the `{% if brief.what_moved %}` block), insert:

```html
  {% if brief.open_loops and (brief.open_loops.today or brief.open_loops.other) %}
  <div class="section">
    <h2>Open Loops</h2>
    {% if brief.open_loops.today %}
    <div style="font-size:11px;font-weight:700;letter-spacing:0.06em;color:#4a6cf7;margin:0 0 8px;">TODAY</div>
    {% for group in brief.open_loops.today %}
    <div style="font-size:14px;font-weight:600;margin:0 0 4px;">{{ group.meeting_name }}</div>
    <ul class="action-list" style="margin-bottom:12px;">
      {% for loop in group.loops %}
      <li>{{ loop.text }}{% if loop.owner %} — {{ loop.owner }}{% endif %} <span style="color:#aaa;font-size:12px;">· {% if loop.age_days == 0 %}today{% else %}{{ loop.age_days }}d{% endif %}</span></li>
      {% endfor %}
    </ul>
    {% endfor %}
    {% endif %}
    {% if brief.open_loops.other %}
    <div style="font-size:11px;font-weight:700;letter-spacing:0.06em;color:#888;margin:8px 0 8px;">OTHER</div>
    {% for group in brief.open_loops.other %}
    <div style="font-size:14px;font-weight:600;margin:0 0 4px;">{{ group.meeting_name }}</div>
    <ul class="action-list" style="margin-bottom:12px;">
      {% for loop in group.loops %}
      <li>{{ loop.text }}{% if loop.owner %} — {{ loop.owner }}{% endif %} <span style="color:#aaa;font-size:12px;">· {% if loop.age_days == 0 %}today{% else %}{{ loop.age_days }}d{% endif %}</span></li>
      {% endfor %}
    </ul>
    {% endfor %}
    {% if brief.open_loops.other_more > 0 %}
    <div style="font-size:13px;color:#888;">+{{ brief.open_loops.other_more }} more open loops</div>
    {% endif %}
    {% endif %}
  </div>
  {% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_sender.py -k open_loops -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add processors/brief.py templates/morning_brief.html tests/test_sender.py
git commit -m "feat: render Open Loops section in brief email template"
```

---

### Task 3: `build_open_loops` wiring in the pipeline

**Files:**
- Modify: `pipeline.py` — add `build_open_loops` (near `build_meeting_prep`, ~line 152); add `open_loops` field to `ProcessedContext` (~line 111); compute it in the process stage (~line 590); assign onto `brief` after generation (~line 865)
- Test: `tests/test_pipeline_open_loops.py` (create)

**Interfaces:**
- Consumes: `meetings_lib.open_loops_buckets` (Task 1); `BriefContent.open_loops` (Task 2); existing `meetings_lib.replay_local(data_dir)`, `find_meeting_for_event(event, configs)`, `MeetingConfig` (`.meeting_id` property, `.name`), `LocalStorage(data_dir).read_json(key, default)`.
- Produces: `build_open_loops(today_events, meeting_configs, data_dir="data") -> dict` (the `open_loops_buckets` shape); `ProcessedContext.open_loops`; `brief.open_loops` populated before email render.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_open_loops.py`:

```python
import json
from processors.meeting_memory import MeetingConfig
from pipeline import build_open_loops


def test_build_open_loops_reads_local_stores(tmp_path):
    (tmp_path / "meetings.jsonl").write_text("\n".join([
        json.dumps({"event": "create_meeting", "id": "luke_1on1", "ts": "2026-06-01T10:00:00"}),
        json.dumps({"event": "add_thread", "id": "luke_1on1", "ts": "2026-06-01T11:00:00",
                    "thread_id": "th-1", "text": "loop luke", "person_id": "luke-green"}),
    ]) + "\n")
    (tmp_path / "people_registry.json").write_text(json.dumps(
        {"version": 1, "people": [{"id": "luke-green", "canonical_name": "Luke Green"}]}))
    configs = [MeetingConfig(calendar_pattern="luke 1:1",
                             memory_file="data/luke_1on1.md", name="Luke 1:1")]

    # no calendar events today -> the loop falls to OTHER
    out = build_open_loops([], configs, data_dir=str(tmp_path))

    assert out["today"] == []
    assert out["other"] == [
        {"meeting_name": "Luke 1:1",
         "loops": [{"text": "loop luke", "owner": "Luke Green",
                    "age_days": out["other"][0]["loops"][0]["age_days"]}]}
    ]
    assert out["other"][0]["loops"][0]["age_days"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_open_loops.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_open_loops' from 'pipeline'`

- [ ] **Step 3: Add `build_open_loops`**

In `pipeline.py`, after `build_meeting_prep` (ends ~line 167), add:

```python
def build_open_loops(today_events, meeting_configs, data_dir: str = "data") -> dict:
    """Bucket every open meeting thread into TODAY / OTHER for the brief.

    Reads the git-anchored local stores (meetings + people registry), not R2.
    """
    from datetime import datetime
    from lib.storage import LocalStorage
    state = meetings_lib.replay_local(data_dir)
    today_ids = set()
    for event in today_events:
        cfg = find_meeting_for_event(event, meeting_configs)
        if cfg:
            today_ids.add(cfg.meeting_id)
    meeting_names = {c.meeting_id: c.name for c in meeting_configs if c.name}
    reg = LocalStorage(data_dir).read_json("people_registry.json", default={"people": []})
    person_names = {p["id"]: p.get("canonical_name", p["id"]) for p in reg.get("people", [])}
    return meetings_lib.open_loops_buckets(
        state, meeting_names, today_ids, person_names, datetime.now().date()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_open_loops.py -v`
Expected: PASS

- [ ] **Step 5: Add the `ProcessedContext` field**

In `pipeline.py`, in the `ProcessedContext` dataclass, next to `meeting_prep` (line 111), add:

```python
    meeting_prep: list = field(default_factory=list)
    open_loops: dict = field(default_factory=dict)
```

- [ ] **Step 6: Compute it in the process stage**

In `pipeline.py`, right after the existing line 590
`ctx.meeting_prep = build_meeting_prep(collected.today_events, meeting_configs, storage)`, add:

```python
        ctx.open_loops = build_open_loops(collected.today_events, meeting_configs)
```

- [ ] **Step 7: Assign onto the brief after generation**

In `pipeline.py`, find the post-generation warning-insert block ending with
`brief.act_today.append(_stale_warn)` (~line 865). Immediately after that block (before the brief is used to build the email), add:

```python
        brief.open_loops = ctx.open_loops
```

- [ ] **Step 8: Run the full brief/meeting test suite**

Run: `python -m pytest tests/test_pipeline_open_loops.py tests/test_meetings_lib.py tests/test_sender.py tests/test_brief.py -v`
Expected: PASS (all)

- [ ] **Step 9: Commit**

```bash
git add pipeline.py tests/test_pipeline_open_loops.py
git commit -m "feat: wire open loops into brief pipeline and email"
```

---

### Task 4: End-to-end smoke + full suite

**Files:** none (verification only)

- [ ] **Step 1: Generate a brief locally without sending**

Run: `python main.py --no-email`
Expected: completes; console shows brief built. (Open Loops render is in the HTML email body; the console summary won't list it — that's expected.)

- [ ] **Step 2: Confirm the rendered HTML contains the section when loops exist**

Run:
```bash
python -c "
from pipeline import build_open_loops
from processors.meeting_memory import load_meeting_index
cfgs = load_meeting_index('data/meeting_index.json')
ol = build_open_loops([], cfgs)
print('today groups:', len(ol['today']), 'other groups:', len(ol['other']), 'more:', ol['other_more'])
for g in ol['today'] + ol['other']:
    print(g['meeting_name'], '->', [f\"{l['text']} ({l['owner']}, {l['age_days']}d)\" for l in g['loops']])
"
```
Expected: prints the current open loops bucketed by meeting with owners + ages (proves it reads real `data/meetings.jsonl`). If there are genuinely no open loops, prints zeros — that's correct.

- [ ] **Step 3: Run the whole test suite**

Run: `python -m pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/open-loops-in-brief
```

---

## Self-Review

**Spec coverage:**
- Deterministic section (not LLM) → Task 2 (template) + Task 3 (assignment). ✓
- TODAY vs OTHER buckets, today via calendar matcher → Task 3 `today_ids`; Task 1 bucketing. ✓
- Grouped by meeting, display name w/ slug fallback → Task 1 `build_groups` + fallback; tested. ✓
- Owner resolution (resolved / unresolved passthrough / null) → Task 1 `owner_for`; tested. ✓
- Age tag, `today` for 0 → Task 1 `_age_days` + Task 2 template; tested. ✓
- Oldest-first within meeting → Task 1 `build_groups` sort; tested. ✓
- OTHER cap 10 + `+N more` → Task 1 cap logic + Task 2 template; tested. ✓
- Zero loops → section omitted → Task 2 `{% if %}`; tested by `test_open_loops_section_absent_when_empty`. ✓
- Git-anchored reads, not R2 → Task 3 uses `replay_local` + `LocalStorage`. ✓
- Out of scope (agenda, LLM feed, Slack prep, auto-promotion) → untouched. ✓

**Placeholder scan:** none — every code/test step shows full content.

**Type consistency:** `open_loops_buckets` return shape `{"today","other","other_more"}` with group `{"meeting_name","loops":[{"text","owner","age_days"}]}` is identical across Task 1 (def + tests), Task 2 (template fields + tests), Task 3 (build + test). `BriefContent.open_loops: dict`, `ProcessedContext.open_loops: dict`. `MeetingConfig.meeting_id` (property) and `.name` used as defined in `processors/meeting_memory.py`. ✓
