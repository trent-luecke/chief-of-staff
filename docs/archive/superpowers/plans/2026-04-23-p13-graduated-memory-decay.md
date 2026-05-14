# P13 — Graduated Memory Decay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add abandonment-based TTL shortening to the memory synthesizer so memories with no recent observations expire faster, preventing stale context pollution.

**Architecture:** Single new function `_apply_abandonment_decay()` in `memory_synthesizer.py` runs before archiving each synthesis cycle. If `activity_last_seen` is older than `abandon_threshold_days`, the file's expiry is shortened to `today + abandon_ttl_days`. Also fixes a bug where `synthesize()` was hardcoding `pinned=False` and `suppress=False` on every write, silently clearing manually-set flags.

**Tech Stack:** Python, `python-frontmatter`, `pytest`

---

## File Map

| File | Change |
|------|--------|
| `processors/memory_synthesizer.py` | Add `_apply_abandonment_decay()`, fix pinned/suppress preservation, add two params to `synthesize()` |
| `tests/test_memory_synthesizer.py` | Add tests for abandonment decay and pinned preservation |
| `config.json` | Add `abandon_threshold_days` and `abandon_ttl_days` to `memory` block |
| `main.py` | Pass new config values through to `synthesize()` call |

---

## Task 1: `_apply_abandonment_decay()` — test and implement

**Files:**
- Modify: `processors/memory_synthesizer.py`
- Test: `tests/test_memory_synthesizer.py`

- [ ] **Step 1: Add import to test file**

Open `tests/test_memory_synthesizer.py`. Add `_apply_abandonment_decay` to the existing import:

```python
from processors.memory_synthesizer import (
    synthesize,
    _load_recent_observations,
    _is_expired,
    _archive_expired_files,
    _apply_abandonment_decay,
)
```

- [ ] **Step 2: Write failing test — shortens TTL for abandoned file**

Add to `tests/test_memory_synthesizer.py`:

```python
def test_apply_abandonment_decay_shortens_expired_ttl(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    memory_file = memory_dir / "stale-topic.md"
    post = fm.Post(
        "## Synthesized Memory\n\nSome old content",
        topic="stale-topic",
        created=old_date,
        last_updated=old_date,
        expires=far_expires,
        activity_last_seen=old_date,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    expected_expires = (date.today() + timedelta(days=14)).isoformat()
    assert str(updated["expires"]) == expected_expires
```

- [ ] **Step 3: Write failing test — skips pinned files**

```python
def test_apply_abandonment_decay_skips_pinned(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    memory_file = memory_dir / "pinned-topic.md"
    post = fm.Post(
        "## Synthesized Memory\n\nPinned content",
        topic="pinned-topic",
        created=old_date,
        last_updated=old_date,
        expires=far_expires,
        activity_last_seen=old_date,
        pinned=True,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    assert str(updated["expires"]) == far_expires
```

- [ ] **Step 4: Write failing test — skips recently active files**

```python
def test_apply_abandonment_decay_skips_recent_file(memory_dir):
    import frontmatter as fm
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    memory_file = memory_dir / "active-topic.md"
    post = fm.Post(
        "## Synthesized Memory\n\nRecent content",
        topic="active-topic",
        created=recent_date,
        last_updated=recent_date,
        expires=far_expires,
        activity_last_seen=recent_date,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    assert str(updated["expires"]) == far_expires
```

- [ ] **Step 5: Write failing test — skips files already expiring soon**

```python
def test_apply_abandonment_decay_skips_already_short_ttl(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    soon_expires = (date.today() + timedelta(days=5)).isoformat()
    memory_file = memory_dir / "nearly-dead.md"
    post = fm.Post(
        "## Synthesized Memory\n\nAlmost gone",
        topic="nearly-dead",
        created=old_date,
        last_updated=old_date,
        expires=soon_expires,
        activity_last_seen=old_date,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    assert str(updated["expires"]) == soon_expires
```

- [ ] **Step 6: Run tests to confirm they all fail**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python -m pytest tests/test_memory_synthesizer.py::test_apply_abandonment_decay_shortens_expired_ttl tests/test_memory_synthesizer.py::test_apply_abandonment_decay_skips_pinned tests/test_memory_synthesizer.py::test_apply_abandonment_decay_skips_recent_file tests/test_memory_synthesizer.py::test_apply_abandonment_decay_skips_already_short_ttl -v
```

Expected: 4 failures with `ImportError: cannot import name '_apply_abandonment_decay'`

- [ ] **Step 7: Implement `_apply_abandonment_decay()` in `memory_synthesizer.py`**

Add after the `_archive_expired_files()` function (around line 43):

```python
def _apply_abandonment_decay(
    memory_dir: str,
    abandon_threshold_days: int,
    abandon_ttl_days: int,
) -> None:
    cutoff = date.today() - timedelta(days=abandon_threshold_days)
    new_expires = (date.today() + timedelta(days=abandon_ttl_days)).isoformat()

    for path in Path(memory_dir).glob("*.md"):
        try:
            post = frontmatter.load(str(path))
            if post.get("pinned", False):
                continue
            activity_str = str(post.get("activity_last_seen", ""))
            if not activity_str:
                continue
            try:
                if date.fromisoformat(activity_str) >= cutoff:
                    continue
            except ValueError:
                continue
            current_expires = str(post.get("expires", ""))
            try:
                if date.fromisoformat(current_expires) <= date.fromisoformat(new_expires):
                    continue
            except ValueError:
                pass
            post["expires"] = new_expires
            with open(path, "wb") as f:
                frontmatter.dump(post, f)
        except Exception:
            continue
```

- [ ] **Step 8: Run tests — confirm all 4 pass**

```bash
python -m pytest tests/test_memory_synthesizer.py::test_apply_abandonment_decay_shortens_expired_ttl tests/test_memory_synthesizer.py::test_apply_abandonment_decay_skips_pinned tests/test_memory_synthesizer.py::test_apply_abandonment_decay_skips_recent_file tests/test_memory_synthesizer.py::test_apply_abandonment_decay_skips_already_short_ttl -v
```

Expected: 4 PASSED

- [ ] **Step 9: Commit**

```bash
git add processors/memory_synthesizer.py tests/test_memory_synthesizer.py
git commit -m "feat(p13): add _apply_abandonment_decay to memory synthesizer"
```

---

## Task 2: Fix pinned/suppress preservation on synthesis write

**Files:**
- Modify: `processors/memory_synthesizer.py`
- Test: `tests/test_memory_synthesizer.py`

- [ ] **Step 1: Write failing test — pinned flag survives re-synthesis**

Add to `tests/test_memory_synthesizer.py`:

```python
def test_synthesize_preserves_pinned_flag(obs_file, memory_dir):
    import frontmatter as fm
    today = date.today().isoformat()

    # Pre-create a memory file with pinned=True
    memory_file = memory_dir / "apex.md"
    post = fm.Post(
        "## Synthesized Memory\n\nExisting content",
        topic="apex",
        created=today,
        last_updated=today,
        expires=(date.today() + timedelta(days=90)).isoformat(),
        activity_last_seen=today,
        pinned=True,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    write_obs(obs_file, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([{
        "topic": "apex",
        "filename": "apex.md",
        "synthesized_memory": "**Pattern:** Apex updated.",
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
        )

    updated = fm.load(str(memory_file))
    assert updated["pinned"] is True
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_memory_synthesizer.py::test_synthesize_preserves_pinned_flag -v
```

Expected: FAIL — `assert False is True` (synthesis overwrites pinned to False)

- [ ] **Step 3: Fix `synthesize()` to preserve pinned and suppress**

In `memory_synthesizer.py`, find the block inside the `for memory in memories:` loop that reads the existing file (around line 130). Replace it:

```python
        created = today
        file_expires = expires
        existing_pinned = False
        existing_suppress = False
        if memory_path.exists():
            try:
                existing = frontmatter.load(str(memory_path))
                created = str(existing.get("created", today))
                existing_pinned = bool(existing.get("pinned", False))
                existing_suppress = bool(existing.get("suppress", False))
                existing_expires = str(existing.get("expires", ""))
                try:
                    ext_date = date.fromisoformat(existing_expires) + timedelta(days=activity_extension_days)
                    file_expires = max(
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
            expires=file_expires,
            activity_last_seen=today,
            pinned=existing_pinned,
            suppress=existing_suppress,
        )
```

- [ ] **Step 4: Run test — confirm it passes**

```bash
python -m pytest tests/test_memory_synthesizer.py::test_synthesize_preserves_pinned_flag -v
```

Expected: PASS

- [ ] **Step 5: Run full synthesizer test suite — confirm no regressions**

```bash
python -m pytest tests/test_memory_synthesizer.py -v
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add processors/memory_synthesizer.py tests/test_memory_synthesizer.py
git commit -m "fix(p13): preserve pinned and suppress flags on memory synthesis write"
```

---

## Task 3: Wire abandonment decay into `synthesize()`, config, and main

**Files:**
- Modify: `processors/memory_synthesizer.py`
- Modify: `config.json`
- Modify: `main.py`

- [ ] **Step 1: Add params to `synthesize()` and call `_apply_abandonment_decay()`**

In `memory_synthesizer.py`, update the `synthesize()` signature to add two new params with defaults:

```python
def synthesize(
    obs_file: str,
    memory_dir: str,
    archive_dir: str,
    api_key: str,
    model: str,
    lookback_days: int = 30,
    default_ttl_days: int = 90,
    activity_extension_days: int = 30,
    abandon_threshold_days: int = 60,
    abandon_ttl_days: int = 14,
) -> None:
    observations = _load_recent_observations(obs_file, lookback_days)
    if not observations:
        return

    _apply_abandonment_decay(memory_dir, abandon_threshold_days, abandon_ttl_days)
    _archive_expired_files(memory_dir, archive_dir)
    # ... rest unchanged
```

- [ ] **Step 2: Run full synthesizer test suite — confirm defaults preserve existing behavior**

```bash
python -m pytest tests/test_memory_synthesizer.py -v
```

Expected: all PASSED

- [ ] **Step 3: Add config keys to `config.json`**

In `config.json`, add two keys to the existing `memory` block:

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
    "retrieval_token_budget": 550,
    "abandon_threshold_days": 60,
    "abandon_ttl_days": 14
  }
```

- [ ] **Step 4: Pass new config values through in `main.py`**

Find the `synthesize()` call in `main.py` (around line 328). Add two kwargs to the existing call — do not rewrite the whole call, just append:

```python
            abandon_threshold_days=memory_cfg.get("abandon_threshold_days", 60),
            abandon_ttl_days=memory_cfg.get("abandon_ttl_days", 14),
```

- [ ] **Step 5: Smoke test — run main with --no-email to confirm no errors**

```bash
cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff
python main.py --no-email --dry-run 2>&1 | head -40
```

Expected: runs without error, synthesis step completes

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_watcher.py
```

Expected: all PASSED (test_watcher.py is known-broken per backlog, excluded)

- [ ] **Step 7: Commit**

```bash
git add processors/memory_synthesizer.py config.json main.py
git commit -m "feat(p13): wire abandon_threshold_days and abandon_ttl_days through config and main"
```

---

## Task 4: Push

- [ ] **Step 1: Pull and push**

```bash
git pull --rebase origin main
git push origin main
```

- [ ] **Step 2: Update BACKLOG.md — mark P13 complete**

In `BACKLOG.md`, change the P13 section header and add a shipped line:

```markdown
## ✅ P13 — Graduated Memory Decay (complete)

**Shipped 2026-04-23.** Abandonment-based TTL shortening in `memory_synthesizer.py`. Files with no new observations for 60+ days have their expiry shortened to today + 14 days. Pinned memories are immune. Also fixed a bug where synthesis was hardcoding `pinned=False` and `suppress=False` on every write. Config params: `abandon_threshold_days` (default 60), `abandon_ttl_days` (default 14). Will produce visible effects from ~mid-June onward.
```

Remove the "What's needed" and "When to do it" bullets from the P13 section.

Also update the status summary at the bottom of BACKLOG.md — add P13 to the completed list.

- [ ] **Step 3: Commit and push backlog**

```bash
git add BACKLOG.md
git commit -m "docs: mark P13 graduated memory decay complete"
git push origin main
```
