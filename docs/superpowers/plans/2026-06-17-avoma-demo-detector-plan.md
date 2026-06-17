# Avoma Demo Detector (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Prerequisite:** Plan A (`OS-Metric-Sync/docs/superpowers/plans/2026-06-17-avoma-demo-engine-plan.md`) must be deployed and `POST /api/demos/ingest` verified live.

**Goal:** Detect OS demos from Avoma transcripts in chief-of-staff and push them to the engine: resolve the owning rep by fuzzy name, hook detection into the nightly Avoma sync, add a one-time backfill, and repoint meeting-prep's demo count at the engine snapshot.

**Architecture:** Reuse `collectors/avoma.py`'s transcript fetch + Claude `os_interested`/`call_type` analysis. A demo = `call_type=='demo'` AND `os_interested` AND rep ∈ the 5. The rep is resolved by fuzzy name (transcript `is_rep` speaker first). Detected demos are pushed via `metrics_client.push_demos` to the engine, which is the single store.

**Tech Stack:** Python 3, `requests`, `anthropic`, pytest.

## Global Constraints

- Repo: `/Users/trentluecke/dev/Claude-Projects/chief-of-staff`. Tests: `python3 -m pytest tests/ -v`.
- Demo record shape pushed to the engine (contract with Plan A): `{avoma_uuid, rep, start_at, title, invitee_names, invitee_emails}` — `rep` is the full canonical name, `start_at` ISO 8601, the two invitee fields are lists.
- **5 reps counted** (full name → match variants): Ryan Allwein, Luke Martin, Chris Reynolds, Jeff Davidson, Trent Luecke. **Quinn excluded.**
- A demo qualifies iff `call_type == "demo"` AND `os_interested == True` AND the resolved rep is one of the 5. Unresolved rep → `"Unassigned"` (still pushed/counted).
- All Avoma/engine failures are non-fatal: log and continue; the nightly job must never hard-fail.
- Engine auth: `requests` with `auth=("", METRICS_PASSWORD)`; base `METRICS_BASE_URL`. Both already GitHub Secrets + in `.env`.
- The full suite has pre-existing unrelated failures; ensure your new tests pass and you add no new failures.

---

### Task 1: `resolve_demo_rep` + `AvomaTranscript.rep_name`

**Files:**
- Modify: `collectors/avoma.py` (add `rep_name` field to `AvomaTranscript`; add `resolve_demo_rep` + `DEMO_REP_ROSTER`)
- Test: `tests/test_resolve_demo_rep.py`

**Interfaces:**
- Produces:
  - `AvomaTranscript.rep_name: str = ""` (new dataclass field, default empty).
  - `DEMO_REP_ROSTER: dict[str, list[str]]` — canonical full name → lowercase match tokens.
  - `resolve_demo_rep(speakers: list[dict], attendees: list[dict], roster: dict[str, list[str]]) -> str | None` — returns the canonical full name, or `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolve_demo_rep.py
from collectors.avoma import resolve_demo_rep, DEMO_REP_ROSTER


def test_matches_is_rep_speaker_by_full_name():
    speakers = [{"name": "Ryan Allwein", "is_rep": True},
                {"name": "Tristan Coles", "is_rep": False}]
    assert resolve_demo_rep(speakers, [], DEMO_REP_ROSTER) == "Ryan Allwein"


def test_falls_back_to_attendee_name_when_no_is_rep():
    attendees = [{"name": "Jeff Davidson", "email": ""}, {"name": "Prospect Co"}]
    assert resolve_demo_rep([], attendees, DEMO_REP_ROSTER) == "Jeff Davidson"


def test_matches_on_last_name_token():
    speakers = [{"name": "Luke A. Martin", "is_rep": True}]
    assert resolve_demo_rep(speakers, [], DEMO_REP_ROSTER) == "Luke Martin"


def test_quinn_not_in_roster_returns_none():
    speakers = [{"name": "Quinn Smith", "is_rep": True}]
    assert resolve_demo_rep(speakers, [], DEMO_REP_ROSTER) is None


def test_no_match_returns_none():
    assert resolve_demo_rep([{"name": "iPad", "is_rep": False}], [], DEMO_REP_ROSTER) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_resolve_demo_rep.py -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement in `collectors/avoma.py`**

Add `rep_name: str = ""` to the `AvomaTranscript` dataclass (with the other defaulted fields). Then add near the top-level helpers:

```python
DEMO_REP_ROSTER: dict[str, list[str]] = {
    "Ryan Allwein": ["ryan allwein", "ryan", "allwein"],
    "Luke Martin": ["luke martin", "luke", "martin", "lmartin"],
    "Chris Reynolds": ["chris reynolds", "chris", "reynolds"],
    "Jeff Davidson": ["jeff davidson", "jeff", "davidson"],
    "Trent Luecke": ["trent luecke", "trent", "luecke"],
}


def _name_matches_roster(name: str, roster: dict[str, list[str]]) -> str | None:
    """Return canonical name if `name` matches a roster entry, else None."""
    n = (name or "").strip().lower()
    if not n:
        return None
    tokens = set(re.split(r"[\s.,]+", n))
    for canonical, variants in roster.items():
        # full-string contains, or last-name/first-name token hit
        for v in variants:
            if v == n or v in tokens or (" " in v and v in n):
                return canonical
    return None


def resolve_demo_rep(speakers, attendees, roster) -> str | None:
    """Resolve the owning rep by fuzzy name. is_rep speaker first, attendee fallback."""
    for s in speakers or []:
        if s.get("is_rep"):
            hit = _name_matches_roster(s.get("name", ""), roster)
            if hit:
                return hit
    for a in attendees or []:
        hit = _name_matches_roster(a.get("name", ""), roster)
        if hit:
            return hit
    return None
```

(`re` is already imported in `avoma.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_resolve_demo_rep.py -v`
Expected: PASS (all five).

- [ ] **Step 5: Commit**

```bash
git add collectors/avoma.py tests/test_resolve_demo_rep.py
git commit -m "feat(avoma): resolve_demo_rep fuzzy name matcher + rep_name field"
```

---

### Task 2: Populate `rep_name` during fetch (optional roster)

**Files:**
- Modify: `collectors/avoma.py` (`fetch_recent_meetings` — add `rep_roster` param; resolve rep_name; name-gate when roster given)
- Test: `tests/test_fetch_rep_name.py`

**Interfaces:**
- Consumes: Task 1 `resolve_demo_rep`, `DEMO_REP_ROSTER`.
- Produces: `fetch_recent_meetings(..., rep_roster: dict | None = None)`. When `rep_roster` is provided: a meeting is included if a roster name matches its attendee names OR an `is_rep` speaker name (in addition to the existing email gate), and each returned transcript's `rep_name` is set via `resolve_demo_rep`. When `rep_roster` is None: behavior unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_rep_name.py
import collectors.avoma as av
from collectors.avoma import AvomaTranscript, DEMO_REP_ROSTER


def test_fetch_sets_rep_name_from_speakers(monkeypatch):
    meeting = {"uuid": "u1", "subject": "Acme demo", "start_at": "2026-06-10T15:00:00Z",
               "transcript_ready": True, "attendees": [{"name": "Acme", "email": "a@acme.com"}]}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"results": [meeting], "next": None}
    monkeypatch.setattr(av.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(av, "_fetch_transcript",
                        lambda key, uuid: ([{"name": "Ryan Allwein", "is_rep": True}], [{"speaker_id": "1", "transcript": "hi"}]))
    monkeypatch.setattr(av, "_analyze_with_claude",
                        lambda *a, **k: {"os_interested": True, "call_type": "demo", "summary": "s",
                                         "features_covered": [], "gaps": [], "objections": [],
                                         "buying_signals": [], "competitors": [],
                                         "onboarding_completed": [], "onboarding_next_steps": [], "action_items": []})

    out = av.fetch_recent_meetings("k", "ak", "m", lookback_hours=72,
                                   rep_roster=DEMO_REP_ROSTER, filter_internal=False)
    assert len(out) == 1
    assert out[0].rep_name == "Ryan Allwein"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_fetch_rep_name.py -v`
Expected: FAIL — `rep_roster` is not a param / `rep_name` not set.

- [ ] **Step 3: Edit `fetch_recent_meetings` in `collectors/avoma.py`**

1. Add `rep_roster: dict | None = None` to the signature.
2. In the per-meeting loop, after computing `attendees` and before/around the rep gate (~line 282-294), when `rep_roster` is set, also allow name matches. Replace the gate block with:

```python
            attendees = m.get("attendees", [])
            attendee_names = [a.get("name", "") for a in attendees]

            name_match = None
            if rep_roster:
                name_match = next((resolve_demo_rep([], [{"name": n}], rep_roster)
                                   for n in attendee_names
                                   if resolve_demo_rep([], [{"name": n}], rep_roster)), None)

            if rep_emails_lower or rep_roster:
                attendee_emails = {(a.get("email") or "").lower() for a in attendees}
                email_hit = bool(rep_emails_lower.intersection(attendee_emails))
                if not email_hit and not name_match:
                    continue
```

3. After `speakers, utterances = _fetch_transcript(...)` (where `speakers` is available, ~line 296) and before building the transcript, resolve the rep:

```python
            resolved_rep = resolve_demo_rep(speakers, attendees, rep_roster) if rep_roster else ""
```

4. Pass `rep_name=resolved_rep or ""` into the `AvomaTranscript(...)` constructor (add the kwarg).

- [ ] **Step 4: Run test + existing avoma tests**

Run: `python3 -m pytest tests/test_fetch_rep_name.py tests/test_avoma*.py -v`
Expected: PASS; existing Avoma tests unaffected (rep_roster defaults None → unchanged path).

- [ ] **Step 5: Commit**

```bash
git add collectors/avoma.py tests/test_fetch_rep_name.py
git commit -m "feat(avoma): optional rep_roster name gate + rep_name resolution"
```

---

### Task 3: `metrics_client.push_demos`

**Files:**
- Modify: `lib/metrics_client.py` (add `push_demos`)
- Test: `tests/test_metrics_client.py` (extend)

**Interfaces:**
- Produces: `push_demos(base_url: str, password: str, demos: list[dict], timeout: int = 60) -> dict` — POSTs `{"demos": demos}` to `/api/demos/ingest`; returns the parsed result, or `{"status": "error", "error": str}` on failure (never raises).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_client.py — add
import lib.metrics_client as mc


def test_push_demos_happy(monkeypatch):
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"inserted": 2, "updated": 0, "skipped": 0}
    monkeypatch.setattr(mc.requests, "post", lambda *a, **k: Resp())
    out = mc.push_demos("http://x", "pw", [{"avoma_uuid": "u1"}])
    assert out["inserted"] == 2


def test_push_demos_non_fatal(monkeypatch):
    def boom(*a, **k): raise mc.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(mc.requests, "post", boom)
    out = mc.push_demos("http://x", "pw", [{"avoma_uuid": "u1"}])
    assert out["status"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_metrics_client.py::test_push_demos_happy -v`
Expected: FAIL — no attribute `push_demos`.

- [ ] **Step 3: Add `push_demos` to `lib/metrics_client.py`**

```python
def push_demos(base_url: str, password: str, demos: list[dict], timeout: int = 60) -> dict:
    """POST detected demos to the engine /api/demos/ingest. Never raises."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/demos/ingest",
            auth=("", password),
            json={"demos": demos},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"⚠️  Demo push failed (non-fatal): {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)[:200]}
```

(`sys` and `requests` are already imported in the module.)

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_metrics_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/metrics_client.py tests/test_metrics_client.py
git commit -m "feat(metrics): push_demos to engine ingest endpoint"
```

---

### Task 4: `lib/demo_detect.py` — filter + map transcripts to demo records

**Files:**
- Create: `lib/demo_detect.py`
- Test: `tests/test_demo_detect.py`

**Interfaces:**
- Consumes: `AvomaTranscript` (has `uuid, title, start_at, participants, call_type, os_interested, rep_name`).
- Produces: `detect_demos(transcripts: list, counted_reps: set[str]) -> list[dict]` — returns demo records `{avoma_uuid, rep, start_at, title, invitee_names, invitee_emails}` for transcripts where `call_type=='demo'` AND `os_interested` AND (`rep_name in counted_reps` OR rep_name falsy→`"Unassigned"`). `rep` = `rep_name` or `"Unassigned"`. `invitee_names`/`invitee_emails` derived from `participants` (names without `@`, emails with `@`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_demo_detect.py
from dataclasses import dataclass, field
from lib.demo_detect import detect_demos

COUNTED = {"Ryan Allwein", "Luke Martin", "Chris Reynolds", "Jeff Davidson", "Trent Luecke"}


@dataclass
class T:
    uuid: str; title: str; start_at: str; call_type: str; os_interested: bool
    rep_name: str = ""; participants: list = field(default_factory=list)


def test_includes_demo_os_interested_with_rep():
    out = detect_demos([T("u1", "Acme", "2026-06-10T15:00:00Z", "demo", True, "Ryan Allwein",
                          ["Ryan Allwein", "ProspectGuy", "p@acme.com"])], COUNTED)
    assert len(out) == 1
    r = out[0]
    assert r["avoma_uuid"] == "u1" and r["rep"] == "Ryan Allwein"
    assert r["invitee_emails"] == ["p@acme.com"]
    assert "ProspectGuy" in r["invitee_names"]


def test_excludes_non_demo_and_non_os():
    ts = [T("u2", "x", "2026-06-10T15:00:00Z", "follow_up", True, "Ryan Allwein"),
          T("u3", "x", "2026-06-10T15:00:00Z", "demo", False, "Ryan Allwein")]
    assert detect_demos(ts, COUNTED) == []


def test_unmatched_rep_becomes_unassigned_but_counted():
    out = detect_demos([T("u4", "x", "2026-06-10T15:00:00Z", "demo", True, "")], COUNTED)
    assert len(out) == 1 and out[0]["rep"] == "Unassigned"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_demo_detect.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `lib/demo_detect.py`**

```python
"""Filter analyzed Avoma transcripts down to countable OS demos and map to
engine-ingest records."""

from __future__ import annotations


def _split_participants(participants: list[str]) -> tuple[list[str], list[str]]:
    names = [p for p in (participants or []) if p and "@" not in p]
    emails = [p for p in (participants or []) if p and "@" in p]
    return names, emails


def detect_demos(transcripts: list, counted_reps: set[str]) -> list[dict]:
    """Return engine demo records for demo+os_interested calls.

    A transcript qualifies when call_type=='demo' AND os_interested is true.
    rep_name in counted_reps is kept as-is; an unresolved rep is bucketed
    "Unassigned" (still counted). Other reps' demos (e.g. Quinn, if ever
    resolved) are dropped.
    """
    records = []
    for t in transcripts:
        if t.call_type != "demo" or not t.os_interested:
            continue
        rep = getattr(t, "rep_name", "") or ""
        if rep and rep not in counted_reps:
            continue  # a resolved non-counted rep (e.g. Quinn) — drop
        names, emails = _split_participants(getattr(t, "participants", []))
        records.append({
            "avoma_uuid": t.uuid,
            "rep": rep if rep in counted_reps else "Unassigned",
            "start_at": t.start_at,
            "title": t.title,
            "invitee_names": names,
            "invitee_emails": emails,
        })
    return records
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_demo_detect.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add lib/demo_detect.py tests/test_demo_detect.py
git commit -m "feat(demos): detect_demos filter + record mapping"
```

---

### Task 5: Config — demo roster + lookback

**Files:**
- Modify: `config.json` (add a `demos` block)
- Test: `tests/test_config_demos.py`

**Interfaces:**
- Produces: `config["demos"]` = `{"counted_reps": [the 5 full names], "lookback_hours": 72}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_demos.py
import json


def test_demos_config_present():
    c = json.load(open("config.json"))
    d = c["demos"]
    assert set(d["counted_reps"]) == {"Ryan Allwein", "Luke Martin", "Chris Reynolds",
                                      "Jeff Davidson", "Trent Luecke"}
    assert d["lookback_hours"] == 72
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config_demos.py -v`
Expected: FAIL — KeyError.

- [ ] **Step 3: Add to `config.json`**

Add a top-level block:
```json
  "demos": {
    "counted_reps": ["Ryan Allwein", "Luke Martin", "Chris Reynolds", "Jeff Davidson", "Trent Luecke"],
    "lookback_hours": 72
  },
```
Validate: `python3 -c "import json; json.load(open('config.json'))"`.

- [ ] **Step 4: Run test + commit**

Run: `python3 -m pytest tests/test_config_demos.py -v` → PASS.
```bash
git add config.json tests/test_config_demos.py
git commit -m "feat(demos): config — counted_reps + lookback_hours"
```

---

### Task 6: Hook detection + push into nightly `avoma_sync.py` (with Slack UUID-dedup)

**Files:**
- Modify: `scripts/avoma_sync.py`
- Test: manual run (Task 9) + the unit-tested pieces it composes (Tasks 1-4)

**Interfaces:**
- Consumes: `fetch_recent_meetings(rep_roster=...)`, `detect_demos`, `metrics_client.push_demos`, `DEMO_REP_ROSTER`, `config["demos"]`.

- [ ] **Step 1: Widen lookback to config + pass the roster**

In `scripts/avoma_sync.py`:
- Replace `_LOOKBACK_HOURS = 24` usage: read `lookback = config.get("demos", {}).get("lookback_hours", 72)`.
- In the `fetch_recent_meetings(...)` call, set `lookback_hours=lookback` and add `rep_roster=__import__("collectors.avoma", fromlist=["DEMO_REP_ROSTER"]).DEMO_REP_ROSTER` (or import `DEMO_REP_ROSTER` at the top alongside `fetch_recent_meetings`).

- [ ] **Step 2: Add Slack UUID-dedup so the wider window doesn't re-DM**

Add a seen-UUID state file so calls already reported aren't reported again. Near the top:
```python
_SEEN_PATH = _ROOT / "data" / "state" / "avoma_sync_seen.json"


def _load_seen() -> set[str]:
    try:
        return set(json.loads(_SEEN_PATH.read_text()))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    _SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SEEN_PATH.write_text(json.dumps(sorted(seen)))
```
After fetching `transcripts`, build the Slack `pipeline_updates`/`onboarding_updates` **only from transcripts whose `uuid` is not in `_load_seen()`**, then add those uuids to the seen set and `_save_seen(...)` after a successful Slack send. (Demos are pushed from ALL fetched transcripts regardless of seen — the engine dedups by UUID.)

- [ ] **Step 3: Add the demo detection + push block**

After the transcripts are fetched (and before/after the Slack send — independent), add:
```python
    # ── Push detected OS demos to the metrics engine (idempotent by UUID) ──
    try:
        from lib.demo_detect import detect_demos
        from lib import metrics_client
        counted = set(config.get("demos", {}).get("counted_reps", []))
        base_url = os.environ.get("METRICS_BASE_URL", "")
        password = os.environ.get("METRICS_PASSWORD", "")
        demo_records = detect_demos(transcripts, counted)
        if demo_records and base_url:
            result = metrics_client.push_demos(base_url, password, demo_records)
            print(f"   Demos pushed: {len(demo_records)} → {result}")
        else:
            print(f"   Demos detected: {len(demo_records)} (push skipped: no base_url)" if not base_url
                  else "   No demos detected this window.")
    except Exception as e:
        print(f"⚠️  Demo detection/push error (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 4: Local dry check (no Slack/engine writes required to compile)**

Run: `python3 -c "import ast; ast.parse(open('scripts/avoma_sync.py').read()); print('parse ok')"`
Then run the broader suite to ensure imports resolve: `python3 -m pytest tests/test_demo_detect.py tests/test_resolve_demo_rep.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/avoma_sync.py
git commit -m "feat(avoma-sync): detect+push OS demos; 72h window with Slack UUID-dedup"
```

---

### Task 7: meeting-prep demo line from the engine snapshot

**Files:**
- Modify: `processors/meeting_prep.py` (the demos KPI line ~313-318)
- Test: `tests/test_meeting_prep_demos.py`

**Interfaces:**
- Consumes: `metrics_client.fetch_snapshot` (returns dict with `demos_data.count`, or cached/None).
- Produces: the "Demos MTD" line sources `count` from the engine snapshot; on snapshot unavailable, prints "Demos MTD: (unavailable)". Sales MTD line unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meeting_prep_demos.py
import processors.meeting_prep as mp


def test_demo_line_uses_snapshot(monkeypatch):
    monkeypatch.setattr(mp, "_demo_count_from_engine", lambda: 7, raising=False)
    line = mp._format_demos_line()
    assert "Demos MTD: 7" in line


def test_demo_line_unavailable(monkeypatch):
    monkeypatch.setattr(mp, "_demo_count_from_engine", lambda: None, raising=False)
    assert "unavailable" in mp._format_demos_line().lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_meeting_prep_demos.py -v`
Expected: FAIL — helpers don't exist.

- [ ] **Step 3: Edit `processors/meeting_prep.py`**

Add helpers near the top of the module:
```python
def _demo_count_from_engine():
    """Current-month demo count from the engine snapshot, or None."""
    try:
        import os
        from lib import metrics_client
        from lib.storage import build_storage  # use the module's existing storage accessor
        base = os.environ.get("METRICS_BASE_URL", "")
        if not base:
            return None
        snap = metrics_client.fetch_snapshot(base, os.environ.get("METRICS_PASSWORD", ""), build_storage())
        return (snap or {}).get("demos_data", {}).get("count")
    except Exception:
        return None


def _format_demos_line() -> str:
    n = _demo_count_from_engine()
    return f"• Demos MTD: {n}" if n is not None else "• Demos MTD: (unavailable)"
```
(If `lib.storage.build_storage` is not the correct accessor in this repo, use the same storage object the brief/meeting-prep already constructs — match the existing pattern; the point is `fetch_snapshot` needs a storage for its cache fallback.)

Then in the demos KPI block (~313-318), replace the `fetch_demos_mtd`-based demo lines with:
```python
            if demos_sheet_id:  # keep the guard; demos now come from the engine
                kpi_lines.append(_format_demos_line())
```
Remove the now-unused `fetch_demos_mtd` import from this block (keep `fetch_sales_mtd`/`month_label` for the sales line).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_meeting_prep_demos.py tests/test_meeting_prep.py -v`
Expected: PASS (sales tests in test_meeting_prep.py unaffected).

- [ ] **Step 5: Commit**

```bash
git add processors/meeting_prep.py tests/test_meeting_prep_demos.py
git commit -m "feat(meeting-prep): demo count from engine snapshot, not dead sheet"
```

---

### Task 8: One-time backfill script

**Files:**
- Create: `scripts/backfill_demos.py`
- Test: none (operational one-shot; composes already-tested units)

**Interfaces:**
- Consumes: `fetch_recent_meetings(rep_roster=...)`, `detect_demos`, `metrics_client.push_demos`.

- [ ] **Step 1: Create `scripts/backfill_demos.py`**

```python
#!/usr/bin/env python3
"""One-time backfill: detect OS demos over a wide window and push to the engine.

Usage: python3 scripts/backfill_demos.py [--hours 840]   # default ~35 days
"""
import json, os, sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def main():
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    from collectors.avoma import fetch_recent_meetings, DEMO_REP_ROSTER
    from lib.demo_detect import detect_demos
    from lib import metrics_client

    hours = 840
    if "--hours" in sys.argv:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])

    config = json.load(open(_ROOT / "config.json"))
    counted = set(config.get("demos", {}).get("counted_reps", []))
    model = config.get("ai_model", "claude-sonnet-4-6")

    print(f"Backfilling demos over last {hours}h...")
    transcripts = fetch_recent_meetings(
        api_key=os.environ["AVOMA_API_KEY"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        model=model,
        lookback_hours=hours,
        rep_roster=DEMO_REP_ROSTER,
        filter_internal=config.get("avoma", {}).get("filter_internal", True),
    )
    records = detect_demos(transcripts, counted)
    print(f"  Detected {len(records)} OS demo(s).")
    result = metrics_client.push_demos(
        os.environ["METRICS_BASE_URL"], os.environ["METRICS_PASSWORD"], records)
    print(f"  Push result: {result}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Syntax check + commit**

Run: `python3 -c "import ast; ast.parse(open('scripts/backfill_demos.py').read()); print('ok')"`
```bash
git add scripts/backfill_demos.py
git commit -m "feat(demos): one-time backfill script"
```

---

### Task 9: End-to-end verify (controller-run)

**Files:** none.

- [ ] **Step 1: Run the backfill against the live engine**

Run: `python3 scripts/backfill_demos.py --hours 840`
Expected: prints "Detected N OS demo(s)" and a push result `{inserted, updated, skipped}`.

- [ ] **Step 2: Confirm the engine + snapshot reflect them**

```bash
URL=$METRICS_BASE_URL; PW=$METRICS_PASSWORD
curl -s -u ":$PW" "$URL/api/demos?scope=month" | python3 -m json.tool | head
curl -s -u ":$PW" "$URL/api/metrics/snapshot" | python3 -c "import sys,json;print('demos_mtd:', json.load(sys.stdin)['demos_data']['count'])"
```
Expected: the demos list shows detected rows; `demos_mtd` is non-zero (matching real demos this month).

- [ ] **Step 3: Dry-run the nightly path**

Run: `python3 scripts/avoma_sync.py` (sends a real Slack DM — expected) and confirm it logs `Demos pushed: N`.

- [ ] **Step 4: Confirm the brief picks it up**

Run: `python3 main.py --no-email` and confirm the metric flags / `Metrics snapshot: ... demos=N` reflect the real count (no longer 0).

---

## Self-Review

- **Spec coverage:** fuzzy name match via is_rep speaker ✓ (T1-2); demo = demo+os_interested, 5 reps, Quinn excluded ✓ (T4-5); push to engine ✓ (T3); hook nightly + 72h + Slack dedup + single pass ✓ (T6); meeting-prep onto snapshot ✓ (T7); one-time backfill ✓ (T8); Unassigned bucket ✓ (T4); UUID dedup is engine-side (Plan A) + idempotent push ✓.
- **Placeholders:** none. The one "match the existing storage accessor" note in T7 is paired with the concrete reason (fetch_snapshot needs a storage) and a fallback instruction.
- **Type consistency:** demo record shape `{avoma_uuid, rep, start_at, title, invitee_names, invitee_emails}` (Global Constraints) is produced by `detect_demos` (T4), sent by `push_demos` (T3), and consumed by Plan A's `/api/demos/ingest`. `DEMO_REP_ROSTER` (T1) used by T2/T6/T8. `counted_reps` (T5 config) used by `detect_demos` (T4/T6/T8). `rep_name` field (T1) set in T2, read in T4.
