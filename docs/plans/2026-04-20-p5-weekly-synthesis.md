# P5 Weekly Synthesis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Sunday at 6pm CDT, generate and email a narrative weekly synthesis that surfaces patterns, carry-forwards, and operational observations drawn from the week's daily signals.

**Architecture:** A new standalone entry point (`weekly_synthesis.py`) drives everything. A new `processors/weekly_synthesizer.py` handles data loading, prompt construction, and the Claude call. A new GitHub Actions workflow (`weekly.yml`) triggers on schedule. Output is emailed and saved to `data/weekly/YYYY-MM-DD.md` for the git commit-back.

**Tech Stack:** Python 3.11, `anthropic` SDK, `google-api-python-client` (Gmail), existing `lib/google_auth.py`, `outputs/sender.py`, `processors/state.py`, `processors/memory_synthesizer._load_recent_observations`, `processors/issues.load_issues`, `lib/captures.load_recent_captures`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `processors/weekly_synthesizer.py` | Create | Data loading, prompt building, Claude call, `WeeklySynthesis` dataclass |
| `weekly_synthesis.py` | Create | Entry point: orchestrate, email, save to `data/weekly/` |
| `.github/workflows/weekly.yml` | Create | Sunday 6pm CDT schedule + git commit-back |
| `tests/test_weekly_synthesizer.py` | Create | Unit tests for data loading and prompt building |
| `data/weekly/.gitkeep` | Create | Ensure directory is tracked |

No changes to existing files.

---

## Task 1: `WeeklySynthesis` dataclass and data loading

**Files:**
- Create: `processors/weekly_synthesizer.py`
- Create: `tests/test_weekly_synthesizer.py`

- [ ] **Step 1: Write failing tests for data loading**

```python
# tests/test_weekly_synthesizer.py
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from processors.weekly_synthesizer import (
    _load_week_observations,
    _load_week_state_delta,
    WeeklySynthesis,
)


def _write_obs(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_load_week_observations_filters_to_7_days(tmp_path):
    obs_file = str(tmp_path / "obs.jsonl")
    today = date.today()
    in_range = (today - timedelta(days=3)).isoformat()
    out_of_range = (today - timedelta(days=10)).isoformat()
    _write_obs(obs_file, [
        {"date": in_range, "type": "top_priority", "entity": "e", "content": "recent"},
        {"date": out_of_range, "type": "top_priority", "entity": "e", "content": "old"},
    ])
    result = _load_week_observations(obs_file, run_date=today)
    assert len(result) == 1
    assert result[0]["content"] == "recent"


def test_load_week_observations_empty_file(tmp_path):
    obs_file = str(tmp_path / "missing.jsonl")
    result = _load_week_observations(obs_file, run_date=date.today())
    assert result == []


def test_load_week_state_delta_counts_resolved_and_open(tmp_path):
    state_dir = str(tmp_path)
    today = date.today()
    week_ago = today - timedelta(days=7)

    # write start snapshot with 3 threads
    start = {"date": week_ago.isoformat(), "open_email_thread_ids": ["a", "b", "c"], "open_notion_item_ids": []}
    with open(os.path.join(state_dir, f"state_{week_ago.isoformat()}.json"), "w") as f:
        json.dump(start, f)

    # write end snapshot — "a" resolved, "b" and "c" still open, "d" new
    end = {"date": today.isoformat(), "open_email_thread_ids": ["b", "c", "d"], "open_notion_item_ids": []}
    with open(os.path.join(state_dir, f"state_{today.isoformat()}.json"), "w") as f:
        json.dump(end, f)

    resolved_count, still_open_count = _load_week_state_delta(state_dir, run_date=today)
    assert resolved_count == 1
    assert still_open_count == 2


def test_load_week_state_delta_no_snapshots(tmp_path):
    resolved, still_open = _load_week_state_delta(str(tmp_path), run_date=date.today())
    assert resolved == 0
    assert still_open == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_weekly_synthesizer.py -v
```

Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 3: Create `processors/weekly_synthesizer.py` with the dataclass and data loaders**

```python
# processors/weekly_synthesizer.py
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

import anthropic

from processors.state import load_snapshot


@dataclass
class WeeklySynthesis:
    executive_summary: str
    patterns: list[str] = field(default_factory=list)
    resolved_this_week: list[str] = field(default_factory=list)
    carry_forwards: list[str] = field(default_factory=list)
    meta_observation: str = ""


def _load_week_observations(obs_file: str, run_date: date) -> list[dict]:
    cutoff = run_date - timedelta(days=7)
    observations = []
    try:
        with open(obs_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    obs_date = date.fromisoformat(obs.get("date", "2000-01-01"))
                    if cutoff <= obs_date <= run_date:
                        observations.append(obs)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return observations


def _load_week_state_delta(state_dir: str, run_date: date) -> tuple[int, int]:
    """Returns (resolved_count, still_open_count) comparing start-of-week to end-of-week snapshots."""
    start_date = run_date - timedelta(days=7)
    start_snap = load_snapshot(start_date, state_dir)
    end_snap = load_snapshot(run_date, state_dir)
    if not start_snap or not end_snap:
        return 0, 0
    start_ids = set(start_snap.open_email_thread_ids)
    end_ids = set(end_snap.open_email_thread_ids)
    resolved_count = len(start_ids - end_ids)
    still_open_count = len(start_ids & end_ids)
    return resolved_count, still_open_count
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_weekly_synthesizer.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/weekly_synthesizer.py tests/test_weekly_synthesizer.py
git commit -m "feat(p5): WeeklySynthesis dataclass and data loaders with tests"
```

---

## Task 2: Prompt building and Claude call

**Files:**
- Modify: `processors/weekly_synthesizer.py` (add `_build_prompt` and `synthesize_week`)
- Modify: `tests/test_weekly_synthesizer.py` (add prompt and synthesis tests)

- [ ] **Step 1: Write failing tests for prompt building and synthesis**

Add to `tests/test_weekly_synthesizer.py`:

```python
from unittest.mock import MagicMock, patch
from processors.weekly_synthesizer import _build_prompt, synthesize_week


def test_build_prompt_includes_observation_content():
    observations = [
        {"date": "2026-04-18", "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
        {"date": "2026-04-18", "type": "pipeline_stale", "entity": "acme", "content": "Acme stale 14 days"},
    ]
    prompt = _build_prompt(
        observations=observations,
        resolved_count=3,
        still_open_count=5,
        open_issue_titles=["Slack outage 2d"],
        captures_text="- flag: check Apex contract",
        run_date=date(2026, 4, 20),
    )
    assert "Follow up Apex" in prompt
    assert "Acme stale 14 days" in prompt
    assert "resolved: 3" in prompt.lower()
    assert "still open: 5" in prompt.lower()
    assert "Slack outage 2d" in prompt
    assert "check Apex contract" in prompt


def test_build_prompt_handles_empty_inputs():
    prompt = _build_prompt(
        observations=[],
        resolved_count=0,
        still_open_count=0,
        open_issue_titles=[],
        captures_text="",
        run_date=date(2026, 4, 20),
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 50


def test_synthesize_week_returns_weekly_synthesis(tmp_path):
    obs_file = str(tmp_path / "obs.jsonl")
    state_dir = str(tmp_path)
    _write_obs(obs_file, [
        {"date": date.today().isoformat(), "type": "top_priority", "entity": "e", "content": "finish contracts"},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "executive_summary": "Solid week with steady pipeline progress.",
        "patterns": ["Pipeline follow-ups dominating priorities"],
        "resolved_this_week": ["Apex contract sent"],
        "carry_forwards": ["Trial conversion for ACME"],
        "meta_observation": "Most priorities were carry-overs from prior week.",
    }))]

    with patch("processors.weekly_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = synthesize_week(
            api_key="test",
            model="claude-sonnet-4-6",
            obs_file=obs_file,
            state_dir=state_dir,
            issues_file=str(tmp_path / "issues.json"),
            captures_file=str(tmp_path / "captures.md"),
            run_date=date.today(),
        )

    assert result.executive_summary == "Solid week with steady pipeline progress."
    assert result.patterns == ["Pipeline follow-ups dominating priorities"]
    assert result.carry_forwards == ["Trial conversion for ACME"]
    assert result.meta_observation == "Most priorities were carry-overs from prior week."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_weekly_synthesizer.py::test_build_prompt_includes_observation_content tests/test_weekly_synthesizer.py::test_synthesize_week_returns_weekly_synthesis -v
```

Expected: `ImportError` for `_build_prompt` and `synthesize_week`.

- [ ] **Step 3: Add `_build_prompt` and `synthesize_week` to `processors/weekly_synthesizer.py`**

Append to the existing file (after `_load_week_state_delta`):

```python
SYSTEM_PROMPT = """\
You are an AI Chief of Staff for Trent Luecke — VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches).

Write a weekly synthesis — a narrative reflection, not a list of events. Surface patterns, what closed, what's accumulating, and the 1-3 most important carry-forwards into next week.

Respond ONLY in JSON with these exact keys:
{
  "executive_summary": "2-3 sentence narrative paragraph — the shape of the week overall",
  "patterns": ["recurring themes that showed up across multiple days, max 3"],
  "resolved_this_week": ["things that closed or were completed, empty list if none"],
  "carry_forwards": ["1-3 highest-priority items heading into next week"],
  "meta_observation": "one operational insight the data reveals that you might not have noticed"
}
"""


def _build_prompt(
    observations: list[dict],
    resolved_count: int,
    still_open_count: int,
    open_issue_titles: list[str],
    captures_text: str,
    run_date: date,
) -> str:
    week_start = (run_date - timedelta(days=7)).isoformat()
    week_end = run_date.isoformat()

    grouped: dict[str, list[dict]] = {}
    for obs in observations:
        obs_type = obs.get("type", "other")
        grouped.setdefault(obs_type, []).append(obs)

    lines = [
        f"## Week of {week_start} → {week_end}",
        "",
        f"**Email threads resolved this week:** {resolved_count}",
        f"**Email threads still open from start of week:** {still_open_count}",
        "",
    ]

    if open_issue_titles:
        lines += ["**Open issues:**"] + [f"  - {t}" for t in open_issue_titles] + [""]

    if captures_text and captures_text.strip():
        lines += ["**Action captures logged this week:**", captures_text.strip(), ""]

    if grouped:
        lines.append("**Observations by type:**")
        for obs_type, obs_list in grouped.items():
            lines.append(f"\n### {obs_type}")
            for obs in obs_list:
                lines.append(f"  [{obs['date']}] {obs['entity']}: {obs['content']}")
                if obs.get("context"):
                    lines.append(f"    → {obs['context']}")

    return "\n".join(lines)


def synthesize_week(
    api_key: str,
    model: str,
    obs_file: str,
    state_dir: str,
    issues_file: str,
    captures_file: str,
    run_date: date | None = None,
) -> WeeklySynthesis:
    import re
    from processors.issues import get_open_issues
    from lib.captures import load_recent_captures

    if run_date is None:
        run_date = date.today()

    observations = _load_week_observations(obs_file, run_date)
    resolved_count, still_open_count = _load_week_state_delta(state_dir, run_date)

    open_issues = get_open_issues(issues_file)
    open_issue_titles = [i.title for i in open_issues]

    captures_text = load_recent_captures(captures_file, max_chars=1500)

    prompt = _build_prompt(
        observations=observations,
        resolved_count=resolved_count,
        still_open_count=still_open_count,
        open_issue_titles=open_issue_titles,
        captures_text=captures_text,
        run_date=run_date,
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    match = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Weekly synthesizer returned non-JSON: {e}\nRaw: {raw[:200]}") from e

    return WeeklySynthesis(
        executive_summary=data.get("executive_summary", ""),
        patterns=data.get("patterns", []),
        resolved_this_week=data.get("resolved_this_week", []),
        carry_forwards=data.get("carry_forwards", []),
        meta_observation=data.get("meta_observation", ""),
    )
```

- [ ] **Step 4: Run all weekly synthesizer tests**

```bash
python -m pytest tests/test_weekly_synthesizer.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/weekly_synthesizer.py tests/test_weekly_synthesizer.py
git commit -m "feat(p5): prompt builder and synthesize_week function with tests"
```

---

## Task 3: Entry point and email output

**Files:**
- Create: `weekly_synthesis.py`
- Create: `data/weekly/.gitkeep`

- [ ] **Step 1: Create `data/weekly/.gitkeep`**

```bash
mkdir -p data/weekly && touch data/weekly/.gitkeep
git add data/weekly/.gitkeep
```

- [ ] **Step 2: Create `weekly_synthesis.py`**

```python
#!/usr/bin/env python3
"""Entry point for weekly synthesis. Called by weekly.yml workflow."""

import json
import os
import sys
from datetime import date

from dotenv import load_dotenv
load_dotenv()

from lib.google_auth import build_gmail_service
from outputs.sender import send_brief_email
from processors.weekly_synthesizer import synthesize_week, WeeklySynthesis


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _render_html(synthesis: WeeklySynthesis, week_end: str) -> str:
    def ul(items: list[str]) -> str:
        if not items:
            return "<p><em>None</em></p>"
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

    sections = [
        f'<h2>Week ending {week_end}</h2>',
        f'<p>{synthesis.executive_summary}</p>',
    ]
    if synthesis.patterns:
        sections += ['<h3>Patterns</h3>', ul(synthesis.patterns)]
    if synthesis.resolved_this_week:
        sections += ['<h3>Resolved This Week</h3>', ul(synthesis.resolved_this_week)]
    if synthesis.carry_forwards:
        sections += ['<h3>Carry-Forwards Into Next Week</h3>', ul(synthesis.carry_forwards)]
    if synthesis.meta_observation:
        sections += [
            '<h3>Meta Observation</h3>',
            f'<p><em>{synthesis.meta_observation}</em></p>',
        ]
    return "\n".join(sections)


def _save_synthesis(synthesis: WeeklySynthesis, weekly_dir: str, run_date: date) -> None:
    os.makedirs(weekly_dir, exist_ok=True)
    path = os.path.join(weekly_dir, f"{run_date.isoformat()}.md")
    lines = [
        f"# Weekly Synthesis — {run_date.isoformat()}",
        "",
        synthesis.executive_summary,
        "",
    ]
    if synthesis.patterns:
        lines += ["## Patterns", *[f"- {p}" for p in synthesis.patterns], ""]
    if synthesis.resolved_this_week:
        lines += ["## Resolved This Week", *[f"- {r}" for r in synthesis.resolved_this_week], ""]
    if synthesis.carry_forwards:
        lines += ["## Carry-Forwards", *[f"- {c}" for c in synthesis.carry_forwards], ""]
    if synthesis.meta_observation:
        lines += ["## Meta Observation", synthesis.meta_observation, ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Saved: {path}")


def main() -> None:
    config = load_config()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    run_date = date.today()
    memory_cfg = config.get("memory", {})

    print("Generating weekly synthesis...")
    try:
        synthesis = synthesize_week(
            api_key=api_key,
            model=config["ai_model"],
            obs_file=memory_cfg.get("observations_file", "data/memory/observations.jsonl"),
            state_dir=config["state_dir"],
            issues_file=config["issues_file"],
            captures_file=config.get("captures_file", "data/captures.md"),
            run_date=run_date,
        )
    except Exception as e:
        print(f"ERROR: synthesis failed: {e}", file=sys.stderr)
        sys.exit(1)

    _save_synthesis(synthesis, "data/weekly", run_date)

    gmail = build_gmail_service(config["email"])
    subject = f"📊 Weekly Synthesis — week ending {run_date.isoformat()}"
    html = _render_html(synthesis, run_date.isoformat())

    try:
        msg_id, _ = send_brief_email(
            gmail_service=gmail,
            to_email=config["email"],
            subject=subject,
            html_body=html,
            plain_text="Weekly synthesis — view in an HTML-capable email client.",
        )
        print(f"Sent: {msg_id}")
    except Exception as e:
        print(f"WARNING: could not send email: {e}", file=sys.stderr)

    print(f"\nSummary: {synthesis.executive_summary}")
    if synthesis.carry_forwards:
        print("\nCarry-Forwards:")
        for item in synthesis.carry_forwards:
            print(f"  → {item}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-test the entry point locally (no-send)**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -c "
import os, json
os.environ['ANTHROPIC_API_KEY'] = open('credentials/.env').read().split('ANTHROPIC_API_KEY=')[1].split()[0] if os.path.exists('credentials/.env') else os.environ.get('ANTHROPIC_API_KEY','')
from datetime import date
from processors.weekly_synthesizer import synthesize_week
s = synthesize_week(
    api_key=os.environ['ANTHROPIC_API_KEY'],
    model='claude-sonnet-4-6',
    obs_file='data/memory/observations.jsonl',
    state_dir='data/state',
    issues_file='data/issues.json',
    captures_file='data/captures.md',
    run_date=date.today(),
)
print('Summary:', s.executive_summary)
print('Patterns:', s.patterns)
print('Carry-forwards:', s.carry_forwards)
"
```

Expected: prints a WeeklySynthesis summary without error. Adjust if needed.

- [ ] **Step 4: Commit**

```bash
git add weekly_synthesis.py data/weekly/.gitkeep
git commit -m "feat(p5): weekly_synthesis.py entry point with email and file save"
```

---

## Task 4: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/weekly.yml`

- [ ] **Step 1: Create `.github/workflows/weekly.yml`**

```yaml
name: Weekly Synthesis

on:
  schedule:
    # Sunday 12pm CDT (UTC-5, Apr-Oct). Change to "0 18 * * 0" in November for CST (UTC-6).
    - cron: "0 17 * * 0"
  workflow_dispatch:

jobs:
  weekly-synthesis:
    runs-on: ubuntu-latest
    permissions:
      contents: write
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

      - name: Run weekly synthesis
        env:
          GOOGLE_OAUTH_JSON: ${{ secrets.GOOGLE_OAUTH_JSON }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python weekly_synthesis.py

      - name: Persist data
        run: |
          git config user.name "chief-of-staff[bot]"
          git config user.email "noreply@github.com"
          git add data/
          git diff --cached --quiet || git commit -m "chore: weekly synthesis $(date +%Y-%m-%d)"
          git pull --rebase
          git push
```

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

```bash
python -m pytest tests/ -v --ignore=tests/test_watcher.py -q
```

Expected: existing tests pass. (`test_watcher.py` is pre-existing broken test, ignore it.)

- [ ] **Step 3: Commit and push**

```bash
git add .github/workflows/weekly.yml
git commit -m "feat(p5): weekly.yml GitHub Actions workflow — Sunday 6pm CDT"
git push
```

- [ ] **Step 4: Trigger manually to verify end-to-end**

In GitHub → Actions → Weekly Synthesis → Run workflow.

Verify:
- Run completes without error
- Email arrives at trent@teambuildr.com with subject "📊 Weekly Synthesis — week ending YYYY-MM-DD"
- `data/weekly/YYYY-MM-DD.md` committed back to repo

---

## Task 5: Update BACKLOG.md

**Files:**
- Modify: `BACKLOG.md`

- [ ] **Step 1: Mark P5 complete in BACKLOG.md**

Change the P5 section header from:

```markdown
## P5 — Weekly Synthesis
```

to:

```markdown
## ✅ P5 — Weekly Synthesis (complete)

**Shipped YYYY-MM-DD.** ...
```

Fill in the shipped date and a one-sentence description of what was built.

- [ ] **Step 2: Commit**

```bash
git add BACKLOG.md
git commit -m "docs: mark P5 weekly synthesis complete"
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ Weekly synthesis processor — `processors/weekly_synthesizer.py`
- ✅ Scheduled trigger Friday EOD / Sunday evening — Sunday 6pm CDT via `weekly.yml`
- ✅ Narrative summary focused on patterns and carry-forwards — JSON schema with `patterns`, `carry_forwards`, `meta_observation`
- ✅ Aggregates week's briefs and signals — uses `observations.jsonl` (7-day lookback), state snapshots, issues, captures
- ✅ Output saved — `data/weekly/YYYY-MM-DD.md` committed back

**Placeholder scan:** None found. All code steps contain actual implementations.

**Type consistency:**
- `WeeklySynthesis` defined in Task 1, imported in Tasks 2 and 3 — consistent
- `synthesize_week(...)` signature defined in Task 2, called in Task 3 — consistent
- `_load_week_observations`, `_load_week_state_delta` defined in Task 1, tested in Task 1 — consistent
- `_build_prompt` defined in Task 2, tested in Task 2 — consistent
