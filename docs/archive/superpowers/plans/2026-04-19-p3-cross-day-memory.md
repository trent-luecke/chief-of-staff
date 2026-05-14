# P3 — Cross-Day Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the brief persistent cross-day memory — raw observations appended each run, Claude synthesizing patterns and decisions async after send, retrieved memory injected into the brief prompt before generation.

**Architecture:** Three new processors: `memory_observer` (append structured signals to `observations.jsonl`, no Claude call), `memory_synthesizer` (read observations → call Claude → write/update `data/memory/*.md` files, runs async after send), `memory_retriever` (read active memory files → return context string injected into brief prompt). Cold-start banner shown in brief for first 3 runs.

**Tech Stack:** Python standard library (`json`, `pathlib`), `anthropic` SDK (already installed), `python-frontmatter` for YAML frontmatter parsing

---

### Task 1: Install `python-frontmatter` and create `data/memory/` structure

**Files:**
- Modify: `requirements.txt`
- Create: `data/memory/.gitkeep`
- Create: `data/memory/decisions.md`
- Modify: `config.json`

- [ ] **Step 1: Add dependency**

Add to `requirements.txt`:
```
python-frontmatter>=1.0.0
```

Install:
```bash
pip install python-frontmatter
python -c "import frontmatter; print('OK')"
```
Expected: `OK`

- [ ] **Step 2: Create data/memory directory**

```bash
mkdir -p data/memory/archive
touch data/memory/.gitkeep
touch data/memory/archive/.gitkeep
```

- [ ] **Step 3: Create `data/memory/decisions.md`**

```markdown
# Decisions Log
# One entry per line: YYYY-MM-DD: <decision text>
# Observer reads this file and emits new lines as 'decision' observations.
# Example:
# 2026-04-19: Pausing Apex outreach until May fiscal year start
```

- [ ] **Step 4: Add memory config block to `config.json`**

Add inside the top-level JSON object:
```json
"memory": {
  "enabled": true,
  "dir": "data/memory",
  "observations_file": "data/memory/observations.jsonl",
  "decisions_file": "data/memory/decisions.md",
  "archive_dir": "data/memory/archive",
  "observation_lookback_days": 30,
  "default_ttl_days": 90,
  "activity_extension_days": 30,
  "cold_start_days": 3,
  "retrieval_token_budget": 1500
}
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt data/memory/ config.json
git commit -m "feat(p3): add memory config and data/memory/ directory structure"
```

---

### Task 2: Create `processors/memory_observer.py`

**Files:**
- Create: `processors/memory_observer.py`
- Create: `tests/test_memory_observer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_observer.py`:
```python
import json
import os
import tempfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from processors.memory_observer import observe, _load_known_decision_dates
from collectors.gmail import EmailThread
from collectors.pipeline import PipelineLead
from processors.brief import BriefContent
from processors.issues import Issue


def make_email_thread(id="t1", subject="Test", days_open=3) -> EmailThread:
    return EmailThread(
        id=id, subject=subject, last_sender="sender@example.com",
        snippet="test snippet", last_message_date=None, needs_reply=True,
    )


def make_stale_lead(name="Apex", days=20) -> PipelineLead:
    return PipelineLead(
        name=name, contact="Jane", email="jane@apex.com",
        status="In-Trial", last_contacted=None, days_since_contact=days,
        estimated_value=10000, stale=True,
    )


def make_issue(id="i1", title="Payment fire", channel="support", age=3) -> Issue:
    return Issue(
        id=id, title=title, source="slack", channel=channel,
        created_date="2026-04-16", last_seen_date="2026-04-19",
        status="open",
    )


def make_brief(priorities=None) -> BriefContent:
    return BriefContent(
        executive_summary="Busy day",
        top_3_priorities=priorities or ["Follow up on Apex contract"],
    )


@pytest.fixture
def obs_file(tmp_path):
    return str(tmp_path / "observations.jsonl")


@pytest.fixture
def decisions_file(tmp_path):
    f = tmp_path / "decisions.md"
    f.write_text("# Decisions\n")
    return str(f)


def test_observe_appends_email_loop(obs_file, decisions_file):
    still_open = {"email": ["t1"], "notion": []}
    threads = [make_email_thread(id="t1", subject="Contract renewal")]
    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=threads,
        still_open_ids=still_open,
        pipeline_leads=[],
        brief=make_brief(),
        issues=[],
    )
    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    email_obs = [o for o in lines if o["type"] == "email_loop"]
    assert len(email_obs) == 1
    assert email_obs[0]["entity"] == "thread:Contract renewal"


def test_observe_appends_pipeline_stale(obs_file, decisions_file):
    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[make_stale_lead(name="Apex", days=20)],
        brief=make_brief(),
        issues=[],
    )
    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    stale_obs = [o for o in lines if o["type"] == "pipeline_stale"]
    assert len(stale_obs) == 1
    assert "apex" in stale_obs[0]["entity"].lower()


def test_observe_appends_top_priority(obs_file, decisions_file):
    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(priorities=["Follow up on Apex contract renewal"]),
        issues=[],
    )
    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    priority_obs = [o for o in lines if o["type"] == "top_priority"]
    assert len(priority_obs) == 1


def test_observe_appends_issue_pattern(obs_file, decisions_file):
    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(),
        issues=[make_issue(title="Payment processing down")],
    )
    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    issue_obs = [o for o in lines if o["type"] == "issue_pattern"]
    assert len(issue_obs) == 1
    assert "Payment processing down" in issue_obs[0]["content"]


def test_observe_emits_new_decisions(obs_file, tmp_path):
    decisions_file = str(tmp_path / "decisions.md")
    with open(decisions_file, "w") as f:
        f.write("# Decisions\n2026-04-19: Pausing Apex outreach\n")
    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(),
        issues=[],
    )
    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    decision_obs = [o for o in lines if o["type"] == "decision"]
    assert len(decision_obs) == 1
    assert "Pausing Apex outreach" in decision_obs[0]["content"]


def test_observe_does_not_emit_duplicate_decisions(obs_file, tmp_path):
    decisions_file = str(tmp_path / "decisions.md")
    with open(decisions_file, "w") as f:
        f.write("# Decisions\n2026-04-19: Pausing Apex outreach\n")
    # Prepopulate obs with the same decision already recorded
    with open(obs_file, "w") as f:
        f.write(json.dumps({
            "date": "2026-04-19", "type": "decision", "entity": "manual",
            "content": "Pausing Apex outreach", "source": "manual"
        }) + "\n")
    observe(
        obs_file=obs_file,
        decisions_file=decisions_file,
        email_threads=[],
        still_open_ids={"email": [], "notion": []},
        pipeline_leads=[],
        brief=make_brief(),
        issues=[],
    )
    with open(obs_file) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    decision_obs = [o for o in lines if o["type"] == "decision"]
    assert len(decision_obs) == 1  # not duplicated
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_memory_observer.py -v
```
Expected: `ImportError` (module not yet created)

- [ ] **Step 3: Create `processors/memory_observer.py`**

```python
import json
from datetime import date
from typing import Optional

from collectors.gmail import EmailThread
from collectors.pipeline import PipelineLead
from processors.brief import BriefContent
from processors.issues import Issue


def _load_known_decision_dates(obs_file: str) -> set[str]:
    known = set()
    try:
        with open(obs_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    if obs.get("type") == "decision":
                        known.add(obs.get("content", "").strip())
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return known


def _read_decisions(decisions_file: str, known_contents: set[str]) -> list[dict]:
    observations = []
    try:
        with open(decisions_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Format: YYYY-MM-DD: <text>
                if ":" not in line:
                    continue
                date_part, _, text = line.partition(":")
                text = text.strip()
                if text and text not in known_contents:
                    observations.append({
                        "date": date.today().isoformat(),
                        "type": "decision",
                        "entity": "manual",
                        "content": text,
                        "source": "manual",
                    })
    except FileNotFoundError:
        pass
    return observations


def observe(
    obs_file: str,
    decisions_file: str,
    email_threads: list[EmailThread],
    still_open_ids: dict,
    pipeline_leads: list[PipelineLead],
    brief: BriefContent,
    issues: list[Issue],
) -> None:
    today = date.today().isoformat()
    observations = []

    # email_loop: threads open >= 2 days (still_open from state diff)
    still_open_email = set(still_open_ids.get("email", []))
    thread_map = {t.id: t for t in email_threads}
    for thread_id in still_open_email:
        thread = thread_map.get(thread_id)
        if thread:
            observations.append({
                "date": today,
                "type": "email_loop",
                "entity": f"thread:{thread.subject}",
                "content": f"Thread open multiple days, no reply",
                "source": "state",
                "context": thread.snippet[:200] if thread.snippet else "",
            })

    # pipeline_stale
    for lead in pipeline_leads:
        if lead.stale or (lead.days_since_contact and lead.days_since_contact > 7):
            days = lead.days_since_contact or 0
            observations.append({
                "date": today,
                "type": "pipeline_stale",
                "entity": lead.name.lower().replace(" ", "-"),
                "content": f"{lead.name} stale {days} days, status: {lead.status}",
                "source": "pipeline",
            })

    # top_priority
    for priority in (brief.top_3_priorities or []):
        observations.append({
            "date": today,
            "type": "top_priority",
            "entity": "priorities",
            "content": priority,
            "source": "brief",
        })

    # issue_pattern
    for issue in issues:
        observations.append({
            "date": today,
            "type": "issue_pattern",
            "entity": issue.channel or issue.source,
            "content": f"{issue.title} (age: {issue.age_days}d, status: {issue.status})",
            "source": "issues",
            "context": f"source: {issue.source}#{issue.channel}",
        })

    # decisions from decisions.md (only new ones)
    known_decision_contents = _load_known_decision_dates(obs_file)
    observations.extend(_read_decisions(decisions_file, known_decision_contents))

    if not observations:
        return

    with open(obs_file, "a") as f:
        for obs in observations:
            f.write(json.dumps(obs) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_memory_observer.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add processors/memory_observer.py tests/test_memory_observer.py
git commit -m "feat(p3): add memory_observer to capture structured daily observations"
```

---

### Task 3: Create `processors/memory_synthesizer.py`

**Files:**
- Create: `processors/memory_synthesizer.py`
- Create: `tests/test_memory_synthesizer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_synthesizer.py`:
```python
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from processors.memory_synthesizer import (
    synthesize,
    _load_recent_observations,
    _is_expired,
    _archive_expired_files,
)


def write_obs(obs_file, observations):
    with open(obs_file, "w") as f:
        for obs in observations:
            f.write(json.dumps(obs) + "\n")


@pytest.fixture
def memory_dir(tmp_path):
    (tmp_path / "archive").mkdir()
    return tmp_path


@pytest.fixture
def obs_file(memory_dir):
    return str(memory_dir / "observations.jsonl")


def test_load_recent_observations_returns_within_lookback(obs_file):
    today = date.today().isoformat()
    old_date = (date.today() - timedelta(days=40)).isoformat()
    write_obs(obs_file, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
        {"date": old_date, "type": "top_priority", "entity": "apex", "content": "Old entry"},
    ])
    result = _load_recent_observations(obs_file, lookback_days=30)
    assert len(result) == 1
    assert result[0]["content"] == "Follow up Apex"


def test_is_expired_returns_true_for_past_date():
    assert _is_expired("2026-01-01") is True


def test_is_expired_returns_false_for_future_date():
    future = (date.today() + timedelta(days=30)).isoformat()
    assert _is_expired(future) is False


def test_is_expired_returns_false_when_pinned():
    assert _is_expired("2026-01-01", pinned=True) is False


def test_archive_expired_files_moves_file(memory_dir):
    expired_file = memory_dir / "old-topic.md"
    expired_file.write_text("""---
topic: old-topic
expires: 2026-01-01
pinned: false
---
Old memory
""")
    archive_dir = str(memory_dir / "archive")
    _archive_expired_files(str(memory_dir), archive_dir)
    assert not expired_file.exists()
    assert (memory_dir / "archive" / "old-topic.md").exists()


def test_synthesize_creates_memory_file(obs_file, memory_dir):
    today = date.today().isoformat()
    write_obs(obs_file, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex contract"},
        {"date": today, "type": "pipeline_stale", "entity": "apex", "content": "Apex stale 20 days"},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([{
        "topic": "apex",
        "filename": "apex.md",
        "synthesized_memory": "**Pattern:** Apex appearing repeatedly. **Watch:** Stale 20 days.",
        "decision_candidates": [],
    }]))]

    with patch("processors.memory_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        synthesize(
            obs_file=obs_file,
            memory_dir=str(memory_dir),
            archive_dir=str(memory_dir / "archive"),
            api_key="test-key",
            model="claude-sonnet-4-6",
            lookback_days=30,
            default_ttl_days=90,
            activity_extension_days=30,
        )

    memory_file = memory_dir / "apex.md"
    assert memory_file.exists()
    content = memory_file.read_text()
    assert "## Synthesized Memory" in content
    assert "Apex appearing repeatedly" in content
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_memory_synthesizer.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `processors/memory_synthesizer.py`**

```python
import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import anthropic
import frontmatter


def _load_recent_observations(obs_file: str, lookback_days: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback_days)
    observations = []
    try:
        with open(obs_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    obs_date = date.fromisoformat(obs.get("date", "2000-01-01"))
                    if obs_date >= cutoff:
                        observations.append(obs)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return observations


def _is_expired(expires: str, pinned: bool = False) -> bool:
    if pinned:
        return False
    try:
        return date.fromisoformat(expires) < date.today()
    except (ValueError, TypeError):
        return False


def _archive_expired_files(memory_dir: str, archive_dir: str) -> None:
    for path in Path(memory_dir).glob("*.md"):
        try:
            post = frontmatter.load(str(path))
            if _is_expired(str(post.get("expires", "")), pinned=bool(post.get("pinned", False))):
                shutil.move(str(path), str(Path(archive_dir) / path.name))
        except Exception:
            continue


def _load_existing_human_section(memory_file: Path) -> str:
    if not memory_file.exists():
        return ""
    try:
        post = frontmatter.load(str(memory_file))
        content = post.content
        # Human section is everything before ## Synthesized Memory
        if "## Synthesized Memory" in content:
            return content.split("## Synthesized Memory")[0].strip()
        return content.strip()
    except Exception:
        return ""


def _build_synthesis_prompt(observations: list[dict]) -> str:
    grouped: dict[str, list[dict]] = {}
    for obs in observations:
        entity = obs.get("entity", "general")
        grouped.setdefault(entity, []).append(obs)

    lines = ["Observations grouped by entity (last 30 days):\n"]
    for entity, obs_list in grouped.items():
        lines.append(f"### {entity}")
        for obs in obs_list:
            lines.append(f"  [{obs['date']}] [{obs['type']}] {obs['content']}")
            if obs.get("context"):
                lines.append(f"    context: {obs['context']}")
        lines.append("")

    lines.append("""
Analyze these observations and return a JSON array. Each element represents one memory file to create/update:

[
  {
    "topic": "short-slug",
    "filename": "short-slug.md",
    "synthesized_memory": "Markdown content for ## Synthesized Memory section. Use **Pattern:**, **Decision:**, **Watch:** headers. Be concise.",
    "decision_candidates": ["candidate text if inferred from context, else empty list"]
  }
]

Rules:
- Group related entities into one file (e.g., multiple apex observations → apex.md)
- Only create files for entities with meaningful patterns (2+ observations or a clear decision)
- Keep synthesized_memory under 200 words
- decision_candidates: only include if you can infer a clear decision from the context field of email/slack observations
- Respond ONLY with the JSON array, no other text
""")
    return "\n".join(lines)


def synthesize(
    obs_file: str,
    memory_dir: str,
    archive_dir: str,
    api_key: str,
    model: str,
    lookback_days: int = 30,
    default_ttl_days: int = 90,
    activity_extension_days: int = 30,
) -> None:
    observations = _load_recent_observations(obs_file, lookback_days)
    if not observations:
        return

    _archive_expired_files(memory_dir, archive_dir)

    prompt = _build_synthesis_prompt(observations)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    try:
        memories = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            memories = json.loads(match.group(0))
        else:
            return

    today = date.today().isoformat()
    expires = (date.today() + timedelta(days=default_ttl_days)).isoformat()

    for memory in memories:
        filename = memory.get("filename", "")
        if not filename or not filename.endswith(".md"):
            continue

        memory_path = Path(memory_dir) / filename
        human_section = _load_existing_human_section(memory_path)

        # Build content
        synthesized = memory.get("synthesized_memory", "")
        decision_candidates = memory.get("decision_candidates", [])
        if decision_candidates:
            synthesized += "\n\n**Decision Candidates (unconfirmed):**\n"
            for dc in decision_candidates:
                synthesized += f"• {dc}\n"

        content_parts = []
        if human_section:
            content_parts.append(f"<!-- Human-written — never modified by synthesis -->\n{human_section}")
        content_parts.append(f"## Synthesized Memory\n\n{synthesized}\n\n_Last synthesized: {today}_")
        content = "\n\n".join(content_parts)

        # Check if file exists to preserve created date and extend TTL
        created = today
        if memory_path.exists():
            try:
                existing = frontmatter.load(str(memory_path))
                created = str(existing.get("created", today))
                existing_expires = str(existing.get("expires", ""))
                try:
                    ext_date = date.fromisoformat(existing_expires) + timedelta(days=activity_extension_days)
                    expires = max(
                        date.fromisoformat(expires),
                        ext_date,
                    ).isoformat()
                except ValueError:
                    pass
            except Exception:
                pass

        post = frontmatter.Post(
            content,
            topic=memory.get("topic", filename.replace(".md", "")),
            created=created,
            last_updated=today,
            expires=expires,
            activity_last_seen=today,
            pinned=False,
            suppress=False,
        )
        with open(memory_path, "wb") as f:
            frontmatter.dump(post, f)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_memory_synthesizer.py -v
```
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add processors/memory_synthesizer.py tests/test_memory_synthesizer.py
git commit -m "feat(p3): add memory_synthesizer for async pattern synthesis"
```

---

### Task 4: Create `processors/memory_retriever.py`

**Files:**
- Create: `processors/memory_retriever.py`
- Create: `tests/test_memory_retriever.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_retriever.py`:
```python
from datetime import date, timedelta
from pathlib import Path

import frontmatter
import pytest

from processors.memory_retriever import retrieve_memories, get_cold_start_message


def write_memory(memory_dir, filename, topic, synthesized, suppress=False, expires_days=90, pinned=False):
    expires = (date.today() + timedelta(days=expires_days)).isoformat()
    content = f"## Synthesized Memory\n\n{synthesized}\n\n_Last synthesized: {date.today().isoformat()}_"
    post = frontmatter.Post(
        content,
        topic=topic,
        created=date.today().isoformat(),
        last_updated=date.today().isoformat(),
        expires=expires,
        activity_last_seen=date.today().isoformat(),
        pinned=pinned,
        suppress=suppress,
    )
    path = Path(memory_dir) / filename
    with open(path, "wb") as f:
        frontmatter.dump(post, f)


@pytest.fixture
def memory_dir(tmp_path):
    return tmp_path


def test_retrieve_memories_returns_context_string(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "**Pattern:** Apex stuck 4 weeks.")
    result = retrieve_memories(str(memory_dir), token_budget=1500)
    assert "apex" in result.lower()
    assert "Pattern" in result


def test_retrieve_memories_excludes_suppressed(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "Apex content", suppress=True)
    result = retrieve_memories(str(memory_dir), token_budget=1500)
    assert "apex" not in result.lower()


def test_retrieve_memories_excludes_expired(memory_dir):
    write_memory(memory_dir, "old.md", "old-topic", "Old content", expires_days=-1)
    result = retrieve_memories(str(memory_dir), token_budget=1500)
    assert "Old content" not in result


def test_retrieve_memories_returns_empty_string_when_no_files(memory_dir):
    result = retrieve_memories(str(memory_dir), token_budget=1500)
    assert result == ""


def test_retrieve_memories_respects_token_budget(memory_dir):
    for i in range(20):
        write_memory(memory_dir, f"topic-{i}.md", f"topic-{i}", "A" * 500)
    result = retrieve_memories(str(memory_dir), token_budget=500)
    # Result should be shorter than if all files were included
    assert len(result) < 20 * 500


def test_retrieve_memories_never_truncates_pinned(memory_dir):
    write_memory(memory_dir, "pinned.md", "pinned-topic", "Critical pinned memory", pinned=True)
    for i in range(20):
        write_memory(memory_dir, f"topic-{i}.md", f"topic-{i}", "A" * 500)
    result = retrieve_memories(str(memory_dir), token_budget=200)
    assert "Critical pinned memory" in result


def test_get_cold_start_message_day_one(memory_dir):
    msg = get_cold_start_message(str(memory_dir / "observations.jsonl"), cold_start_days=3)
    assert "day 1" in msg.lower()


def test_get_cold_start_message_none_after_threshold(memory_dir, tmp_path):
    obs_file = str(tmp_path / "observations.jsonl")
    # Simulate 4 days of observations
    with open(obs_file, "w") as f:
        for i in range(4):
            d = (date.today() - timedelta(days=i)).isoformat()
            f.write(f'{{"date": "{d}", "type": "top_priority", "entity": "x", "content": "x"}}\n')
    msg = get_cold_start_message(obs_file, cold_start_days=3)
    assert msg is None
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_memory_retriever.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `processors/memory_retriever.py`**

```python
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import frontmatter


def _count_distinct_days(obs_file: str) -> int:
    days = set()
    try:
        import json
        with open(obs_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    days.add(obs.get("date", ""))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return len(days)


def get_cold_start_message(obs_file: str, cold_start_days: int = 3) -> Optional[str]:
    distinct_days = _count_distinct_days(obs_file)
    if distinct_days >= cold_start_days:
        return None
    day_num = distinct_days + 1
    if day_num == 1:
        return f"Memory building — context improves with each run (day 1 of {cold_start_days})"
    return f"Memory building — patterns will emerge after a few more runs (day {day_num} of {cold_start_days})"


def retrieve_memories(memory_dir: str, token_budget: int = 1500) -> str:
    today = date.today()
    pinned_sections = []
    regular_sections = []

    for path in sorted(Path(memory_dir).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue

        if post.get("suppress", False):
            continue

        expires_str = str(post.get("expires", ""))
        pinned = bool(post.get("pinned", False))
        try:
            if not pinned and date.fromisoformat(expires_str) < today:
                continue
        except ValueError:
            pass

        topic = post.get("topic", path.stem)
        last_updated = post.get("last_updated", "")

        # Extract only the ## Synthesized Memory section for token efficiency
        content = post.content
        if "## Synthesized Memory" in content:
            synthesized = content.split("## Synthesized Memory")[1].strip()
            # Remove the "_Last synthesized: ..." line
            lines = [l for l in synthesized.splitlines() if not l.startswith("_Last synthesized")]
            synthesized = "\n".join(lines).strip()
        else:
            synthesized = content.strip()

        section = f"**{topic}** (updated: {last_updated})\n{synthesized}"

        if pinned:
            pinned_sections.append(section)
        else:
            regular_sections.append(section)

    if not pinned_sections and not regular_sections:
        return ""

    # Build output respecting token budget (rough estimate: 1 token ≈ 4 chars)
    char_budget = token_budget * 4
    output_parts = ["## Cross-Day Memory\n"]

    for section in pinned_sections:
        output_parts.append(section)

    remaining = char_budget - sum(len(p) for p in output_parts)
    for section in regular_sections:
        if len(section) > remaining:
            break
        output_parts.append(section)
        remaining -= len(section)

    return "\n\n".join(output_parts)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_memory_retriever.py -v
```
Expected: 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add processors/memory_retriever.py tests/test_memory_retriever.py
git commit -m "feat(p3): add memory_retriever for brief context injection"
```

---

### Task 5: Update `processors/brief.py`

**Files:**
- Modify: `processors/brief.py`
- Modify: `tests/test_brief.py`

Add `memory_context` parameter to `generate_brief` and `_build_prompt`, inject as `## Cross-Day Memory` section.

- [ ] **Step 1: Write failing test**

Add to `tests/test_brief.py`:
```python
def test_build_prompt_includes_memory_context():
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary
    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        memory_context="## Cross-Day Memory\n\n**apex** Apex stuck 4 weeks.",
    )
    assert "Cross-Day Memory" in prompt
    assert "apex" in prompt


def test_build_prompt_omits_memory_section_when_empty():
    from processors.brief import _build_prompt
    from processors.loops import LoopSummary
    prompt = _build_prompt(
        today_events=[],
        tomorrow_events=[],
        email_threads=[],
        projects=[],
        due_tasks=[],
        loop_summary=LoopSummary(),
        open_issues=[],
        drafts=[],
        meeting_prep=[],
        inbox_text="",
        memory_context="",
    )
    assert "Cross-Day Memory" not in prompt
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_brief.py -k "memory" -v
```
Expected: FAIL (`_build_prompt` doesn't accept `memory_context` yet)

- [ ] **Step 3: Update `processors/brief.py`**

**a)** Add `memory_context: str = ""` to `_build_prompt` signature.

**b)** Prepend the memory context as the first section (before `## People Context`). Add at the beginning of the `sections` list:

```python
    sections = []
    if memory_context:
        sections += [memory_context, ""]
    sections += [
        "## People Context (background — use to identify missed deliverables and add relationship context to existing sections, do not create a new section)",
        people_context if people_context else "  (no contacts matched today)",
        "",
        # ... rest of existing sections unchanged ...
    ]
```

**c)** Add `memory_context: str = ""` to `generate_brief` signature.

**d)** Pass it through to `_build_prompt`:

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
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_brief.py tests/test_brief_extended.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add processors/brief.py tests/test_brief.py
git commit -m "feat(p3): add memory_context parameter to brief prompt builder"
```

---

### Task 6: Wire memory pipeline into `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add imports to `main.py`**

Add after the existing processor imports:
```python
from processors.memory_observer import observe
from processors.memory_synthesizer import synthesize
from processors.memory_retriever import retrieve_memories, get_cold_start_message
```

- [ ] **Step 2: Add memory retrieval and cold-start detection before brief generation**

In `run()`, after the `people_context` block and before the `generate_brief` call, add:

```python
    memory_context = ""
    memory_cold_start_msg = None
    memory_cfg = config.get("memory", {})
    if memory_cfg.get("enabled"):
        memory_context = retrieve_memories(
            memory_dir=memory_cfg["dir"],
            token_budget=memory_cfg.get("retrieval_token_budget", 1500),
        )
        memory_cold_start_msg = get_cold_start_message(
            obs_file=memory_cfg["observations_file"],
            cold_start_days=memory_cfg.get("cold_start_days", 3),
        )
        if memory_cold_start_msg:
            print(f"   ℹ️  {memory_cold_start_msg}")
```

- [ ] **Step 3: Pass `memory_context` to `generate_brief`**

In the `generate_brief(...)` call, add:
```python
            memory_context=memory_context,
```

- [ ] **Step 4: Add cold-start banner to brief watch_outs**

After the `generate_brief` call, add before the pipeline stale check:
```python
    if memory_cold_start_msg:
        brief.watch_outs = [memory_cold_start_msg] + brief.watch_outs
```

- [ ] **Step 5: Add observation capture after `save_snapshot`**

After the `save_snapshot(...)` call, add:
```python
    if memory_cfg.get("enabled"):
        observe(
            obs_file=memory_cfg["observations_file"],
            decisions_file=memory_cfg["decisions_file"],
            email_threads=email_threads,
            still_open_ids=still_open if previous_state else {"email": [], "notion": []},
            pipeline_leads=list(trial_leads) + list(attention_leads),
            brief=brief,
            issues=open_issues,
        )
        print("🧠  Observations captured.")
```

- [ ] **Step 6: Run synthesis after observations**

Add after the observe call. Synthesis runs after the brief is already sent — no user-facing latency. In a cron job, synchronous is simpler and more reliable than a daemon thread (which gets killed when the process exits):

```python
        print("🔄  Running memory synthesis...")
        synthesize(
            obs_file=memory_cfg["observations_file"],
            memory_dir=memory_cfg["dir"],
            archive_dir=memory_cfg["archive_dir"],
            api_key=api_key,
            model=config["ai_model"],
            lookback_days=memory_cfg.get("observation_lookback_days", 30),
            default_ttl_days=memory_cfg.get("default_ttl_days", 90),
            activity_extension_days=memory_cfg.get("activity_extension_days", 30),
        )
        print("✅  Memory synthesis complete.")
```

- [ ] **Step 7: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/test_notion_inbox.py
```
Expected: All PASS

- [ ] **Step 8: Dry-run locally**

```bash
python main.py --no-email
```
Expected: Brief generates. Console shows `Observations captured.` and `Memory synthesis started (async).` Day 1 cold-start message appears in brief watch_outs.

- [ ] **Step 9: Commit**

```bash
git add main.py
git commit -m "feat(p3): wire memory observer, synthesizer, and retriever into main run loop"
```

---

### Task 7: Final wiring and verification

- [ ] **Step 1: Commit data/memory structure**

```bash
git add data/memory/
git commit -m "feat(p3): add data/memory directory with decisions.md template"
```

- [ ] **Step 2: Run full test suite one final time**

```bash
pytest tests/ -v --ignore=tests/test_notion_inbox.py
```
Expected: All PASS

- [ ] **Step 3: Run with `--dry-run` to verify no email side effects**

```bash
python main.py --dry-run
```
Expected: No errors. `data/memory/observations.jsonl` has entries. After ~30 seconds, `data/memory/*.md` files may appear (synthesis async).

- [ ] **Step 4: Final commit**

```bash
git add -u
git status  # verify nothing unexpected
git push
```
