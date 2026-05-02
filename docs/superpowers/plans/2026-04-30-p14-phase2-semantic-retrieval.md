# P14 Phase 2 — Semantic Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the recency-based memory retriever with semantic search against Pinecone, producing a brief context block split into ranked synthesized memories (`### Context`) and supporting raw observations (`### Recent Signals`).

**Architecture:** Extend `memory_retriever.py` with `build_query_string`, `query_pinecone`, `_load_memory_section`, `_retrieve_memories_file_based`, and `_retrieve_memories_semantic`. The public `retrieve_memories` signature gains two optional parameters (`pinecone_config`, `query_signals`) and stays backward-compatible — existing callers without those params continue hitting the file-based path unchanged. `main.py` builds the config dict and signal dict from already-collected data and passes them in. Pinned memories always bypass ranking. Any Pinecone failure in `retrieval_mode="auto"` (the default) transparently falls back to the existing file-based path.

**Tech Stack:** `pinecone` SDK, `voyageai` SDK, `python-frontmatter` (all added in Phase 1)

**Design spec:** `docs/superpowers/plans/2026-04-29-p14-vector-memory-layer-design.md`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `config.json` | **Modify** | Add `retrieval_mode: "auto"` to vector block |
| `processors/memory_retriever.py` | **Modify** | Add `build_query_string`, `query_pinecone`, `_load_memory_section`, `_retrieve_memories_file_based`, `_retrieve_memories_semantic`; extend `retrieve_memories` public signature |
| `main.py` | **Modify** | Build and pass `pinecone_config` + `query_signals` to `retrieve_memories` |
| `tests/test_memory_retriever.py` | **Modify** | Add tests for query building, semantic path, deduplication, fallback, output format |
| `tests/test_memory_retriever_integration.py` | **Create** | Integration test against live Pinecone (skipped when API keys absent) |

---

## Task 1: Add retrieval_mode to config.json

**Files:**
- Modify: `config.json`

- [ ] **Step 1: Add retrieval_mode to the vector block**

In `config.json`, add `"retrieval_mode"` as the last field inside the `"vector"` object:

```json
"vector": {
  "enabled": true,
  "index_name": "chief-of-staff",
  "embedding_model": "voyage-3-lite",
  "embedding_dimension": 512,
  "observations_namespace": "observations",
  "memories_namespace": "memories",
  "ingest_state_file": "data/vector_ingest_state.json",
  "retrieval_mode": "auto"
}
```

Valid values: `"auto"` (try Pinecone, fall back to file-based on any error), `"semantic"` (Pinecone only, raise on error), `"file"` (file-based always, Pinecone never called).

- [ ] **Step 2: Commit**

```bash
git add config.json
git commit -m "feat(p14): add retrieval_mode config field to vector block"
```

---

## Task 2: build_query_string (TDD)

**Files:**
- Modify: `processors/memory_retriever.py`
- Modify: `tests/test_memory_retriever.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `tests/test_memory_retriever.py`:

```python
from processors.memory_retriever import build_query_string


def test_build_query_string_combines_all_signal_types():
    signals = {
        "calendar_events": ["Team standup", "Demo with Apex"],
        "email_subjects": ["Contract renewal"],
        "pipeline_lead_names": ["Apex Gym", "TGMC"],
        "issue_titles": ["Follow up on stale leads"],
    }
    result = build_query_string(signals)
    assert "Team standup" in result
    assert "Demo with Apex" in result
    assert "Contract renewal" in result
    assert "Apex Gym" in result
    assert "TGMC" in result
    assert "Follow up on stale leads" in result


def test_build_query_string_deduplicates_case_insensitively():
    signals = {
        "calendar_events": ["Apex Gym"],
        "email_subjects": ["apex gym"],  # same name, different case
        "pipeline_lead_names": ["Apex Gym"],
        "issue_titles": [],
    }
    result = build_query_string(signals)
    # "Apex Gym" should appear only once
    assert result.count("Apex Gym") + result.count("apex gym") == 1


def test_build_query_string_limits_email_subjects_to_ten():
    signals = {
        "calendar_events": [],
        "email_subjects": [f"Subject {i}" for i in range(15)],
        "pipeline_lead_names": [],
        "issue_titles": [],
    }
    result = build_query_string(signals)
    # Only first 10 email subjects should be included
    assert "Subject 9" in result
    assert "Subject 10" not in result


def test_build_query_string_returns_empty_string_for_empty_signals():
    result = build_query_string({})
    assert result == ""


def test_build_query_string_skips_empty_strings_in_signals():
    signals = {
        "calendar_events": ["", "Real event"],
        "email_subjects": [],
        "pipeline_lead_names": [],
        "issue_titles": [],
    }
    result = build_query_string(signals)
    assert result == "Real event"
```

- [ ] **Step 2: Run to verify tests fail**

```bash
cd /path/to/chief-of-staff
pytest tests/test_memory_retriever.py::test_build_query_string_combines_all_signal_types -v
```
Expected: `ImportError: cannot import name 'build_query_string'`

- [ ] **Step 3: Implement build_query_string in memory_retriever.py**

Add after the existing imports (keep existing imports, add nothing new — `build_query_string` needs no new imports):

```python
def build_query_string(query_signals: dict) -> str:
    """Build a Voyage AI query string from today's collected signals."""
    parts = []
    parts.extend(query_signals.get("calendar_events", []))
    parts.extend(query_signals.get("email_subjects", [])[:10])
    parts.extend(query_signals.get("pipeline_lead_names", []))
    parts.extend(query_signals.get("issue_titles", []))

    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        if not p:
            continue
        key = p.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(p.strip())

    return " | ".join(unique)
```

Place this function before `_count_distinct_days`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_memory_retriever.py -k "build_query_string" -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add processors/memory_retriever.py tests/test_memory_retriever.py
git commit -m "feat(p14): add build_query_string for semantic retrieval query construction"
```

---

## Task 3: Semantic retrieval path (TDD)

**Files:**
- Modify: `processors/memory_retriever.py`
- Modify: `tests/test_memory_retriever.py`

This task adds `query_pinecone`, `_load_memory_section`, `_retrieve_memories_file_based`, `_retrieve_memories_semantic`, and extends the `retrieve_memories` public signature.

- [ ] **Step 1: Write failing tests**

Add to the bottom of `tests/test_memory_retriever.py`:

```python
import sys
from unittest.mock import patch, MagicMock

from processors.memory_retriever import retrieve_memories


# --- helpers ---

def make_match(match_id: str, metadata: dict):
    m = MagicMock()
    m.id = match_id
    m.metadata = metadata
    return m


PINECONE_CFG = {
    "api_key": "test-key",
    "voyage_api_key": "test-voyage-key",
    "index_name": "chief-of-staff",
    "embedding_model": "voyage-3-lite",
    "observations_namespace": "observations",
    "memories_namespace": "memories",
    "retrieval_mode": "semantic",
}

QUERY_SIGNALS = {
    "calendar_events": ["Team standup", "Demo with Apex"],
    "email_subjects": ["Contract renewal"],
    "pipeline_lead_names": ["Apex Gym"],
    "issue_titles": ["Follow up on stale deals"],
}


# --- retrieval_mode="file" ---

def test_retrieve_memories_file_mode_skips_pinecone(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "Apex memory content.")

    with patch("processors.memory_retriever.query_pinecone") as mock_qp:
        result = retrieve_memories(
            str(memory_dir),
            token_budget=1500,
            pinecone_config={**PINECONE_CFG, "retrieval_mode": "file"},
            query_signals=QUERY_SIGNALS,
        )
        mock_qp.assert_not_called()

    assert "Apex memory content." in result


def test_retrieve_memories_no_pinecone_config_uses_file_path(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "Apex file content.")

    result = retrieve_memories(str(memory_dir), token_budget=1500)
    assert "Apex file content." in result


# --- semantic output format ---

def test_retrieve_memories_semantic_output_has_context_and_signals_sections(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "Apex has been stale 8 days.")

    mem_match = make_match(
        "mem:apex.md",
        {"expires": "2026-07-30", "pinned": False},
    )
    obs_match = make_match(
        "2026-04-29:pipeline_stale:apex",
        {
            "date": "2026-04-29",
            "type": "pipeline_stale",
            "content_preview": "Apex stale 8 days",
        },
    )

    with patch("processors.memory_retriever.query_pinecone", return_value=([mem_match], [obs_match])):
        result = retrieve_memories(
            str(memory_dir),
            token_budget=1500,
            pinecone_config=PINECONE_CFG,
            query_signals=QUERY_SIGNALS,
        )

    assert "## Cross-Day Memory" in result
    assert "### Context" in result
    assert "### Recent Signals" in result
    assert "Apex has been stale 8 days." in result
    assert "pipeline_stale: Apex stale 8 days" in result
    # Context must come before Recent Signals
    assert result.index("### Context") < result.index("### Recent Signals")


# --- pinned deduplication ---

def test_retrieve_memories_pinned_not_duplicated_when_in_vector_results(memory_dir):
    write_memory(memory_dir, "critical.md", "critical-topic", "Critical context here.", pinned=True)

    # Pinned memory also returned by Pinecone — should be deduplicated
    mem_match = make_match(
        "mem:critical.md",
        {"expires": "2026-07-30", "pinned": True},
    )

    with patch("processors.memory_retriever.query_pinecone", return_value=([mem_match], [])):
        result = retrieve_memories(
            str(memory_dir),
            token_budget=1500,
            pinecone_config=PINECONE_CFG,
            query_signals=QUERY_SIGNALS,
        )

    assert result.count("Critical context here.") == 1


# --- expiry filtering ---

def test_retrieve_memories_semantic_filters_expired_memory_results(memory_dir):
    write_memory(memory_dir, "expired.md", "expired-topic", "Expired content here.", expires_days=-1)

    mem_match = make_match(
        "mem:expired.md",
        {"expires": (date.today() - timedelta(days=1)).isoformat(), "pinned": False},
    )

    with patch("processors.memory_retriever.query_pinecone", return_value=([mem_match], [])):
        result = retrieve_memories(
            str(memory_dir),
            token_budget=1500,
            pinecone_config=PINECONE_CFG,
            query_signals=QUERY_SIGNALS,
        )

    assert "Expired content here." not in result


# --- fallback ---

def test_retrieve_memories_auto_mode_falls_back_on_pinecone_error(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "Fallback file content.")

    with patch("processors.memory_retriever.query_pinecone", side_effect=Exception("connection refused")):
        result = retrieve_memories(
            str(memory_dir),
            token_budget=1500,
            pinecone_config={**PINECONE_CFG, "retrieval_mode": "auto"},
            query_signals=QUERY_SIGNALS,
        )

    assert "Fallback file content." in result


def test_retrieve_memories_semantic_mode_raises_on_pinecone_error(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "Some content.")

    with patch("processors.memory_retriever.query_pinecone", side_effect=Exception("connection refused")):
        with pytest.raises(Exception, match="connection refused"):
            retrieve_memories(
                str(memory_dir),
                token_budget=1500,
                pinecone_config={**PINECONE_CFG, "retrieval_mode": "semantic"},
                query_signals=QUERY_SIGNALS,
            )


# --- empty query fallback ---

def test_retrieve_memories_falls_back_to_file_when_query_string_is_empty(memory_dir):
    write_memory(memory_dir, "apex.md", "apex", "File path content.")

    with patch("processors.memory_retriever.query_pinecone") as mock_qp:
        result = retrieve_memories(
            str(memory_dir),
            token_budget=1500,
            pinecone_config=PINECONE_CFG,
            query_signals={},  # no signals → empty query string
        )
        mock_qp.assert_not_called()

    assert "File path content." in result


# --- token budget ---

def test_retrieve_memories_semantic_respects_token_budget(memory_dir):
    for i in range(10):
        write_memory(memory_dir, f"topic-{i}.md", f"topic-{i}", "X" * 400)

    mem_matches = [
        make_match(f"mem:topic-{i}.md", {"expires": "2026-12-31", "pinned": False})
        for i in range(10)
    ]
    obs_matches = [
        make_match(f"2026-04-29:type:entity-{i}", {
            "date": "2026-04-29", "type": "signal", "content_preview": "Y" * 200,
        })
        for i in range(10)
    ]

    with patch("processors.memory_retriever.query_pinecone", return_value=(mem_matches, obs_matches)):
        result = retrieve_memories(
            str(memory_dir),
            token_budget=300,
            pinecone_config=PINECONE_CFG,
            query_signals=QUERY_SIGNALS,
        )

    assert len(result) <= 300 * 4 * 1.1  # allow 10% overhead for headers
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_memory_retriever.py -k "semantic or file_mode or pinned_not_duplicated or expired or fallback or empty_query" -v
```
Expected: Most tests FAIL with `TypeError` (unexpected keyword arguments) or similar. The file-mode/no-config tests may already pass.

- [ ] **Step 3: Add imports to memory_retriever.py**

At the top of `processors/memory_retriever.py`, add `import os` and `import sys` to the existing stdlib block, and add the Pinecone/Voyage imports:

```python
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import frontmatter
import voyageai
from pinecone import Pinecone
```

- [ ] **Step 4: Add _load_memory_section helper**

Add this function after `build_query_string` in `processors/memory_retriever.py`:

```python
def _load_memory_section(memory_dir: str, match_id: str) -> Optional[str]:
    """Load and format a memory .md file by its Pinecone vector ID, or None if skipped."""
    if not match_id.startswith("mem:"):
        return None
    filename = match_id[4:]
    path = os.path.join(memory_dir, filename)
    try:
        post = frontmatter.load(path)
    except Exception:
        return None

    if post.get("suppress", False):
        return None

    today = date.today()
    expires_str = str(post.get("expires", ""))
    pinned = bool(post.get("pinned", False))
    try:
        if not pinned and expires_str and date.fromisoformat(expires_str) < today:
            return None
    except ValueError:
        pass

    topic = str(post.get("topic", Path(path).stem))
    last_updated = str(post.get("last_updated", ""))

    content = post.content
    if "## Synthesized Memory" in content:
        synthesized = content.split("## Synthesized Memory")[1].strip()
        lines = [ln for ln in synthesized.splitlines() if not ln.startswith("_Last synthesized")]
        synthesized = "\n".join(lines).strip()
    else:
        synthesized = content.strip()

    if not synthesized:
        return None

    return f"**{topic}** (updated: {last_updated})\n{synthesized}"
```

- [ ] **Step 5: Add query_pinecone function**

Add after `_load_memory_section`:

```python
def query_pinecone(
    pinecone_config: dict,
    query_string: str,
    top_k_memories: int = 20,
    top_k_observations: int = 20,
) -> tuple[list, list]:
    """Embed query_string via Voyage AI and query both Pinecone namespaces.

    Returns (memory_matches, observation_matches).
    """
    vo = voyageai.Client(api_key=pinecone_config["voyage_api_key"])
    result = vo.embed([query_string], model=pinecone_config["embedding_model"], input_type="query")
    query_vector = result.embeddings[0]

    pc = Pinecone(api_key=pinecone_config["api_key"])
    index = pc.Index(pinecone_config["index_name"])

    mem_response = index.query(
        vector=query_vector,
        top_k=top_k_memories,
        namespace=pinecone_config.get("memories_namespace", "memories"),
        include_metadata=True,
    )
    obs_response = index.query(
        vector=query_vector,
        top_k=top_k_observations,
        namespace=pinecone_config.get("observations_namespace", "observations"),
        include_metadata=True,
    )
    return mem_response.matches, obs_response.matches
```

- [ ] **Step 6: Extract existing retrieve_memories body into _retrieve_memories_file_based**

Rename the existing `retrieve_memories` function to `_retrieve_memories_file_based`. The signature stays the same:

```python
def _retrieve_memories_file_based(memory_dir: str, token_budget: int = 550) -> str:
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

        content = post.content
        if "## Synthesized Memory" in content:
            synthesized = content.split("## Synthesized Memory")[1].strip()
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

- [ ] **Step 7: Add _retrieve_memories_semantic**

Add after `_retrieve_memories_file_based`:

```python
def _retrieve_memories_semantic(
    memory_dir: str,
    token_budget: int,
    pinecone_config: dict,
    query_signals: dict,
) -> str:
    today = date.today()
    char_budget = token_budget * 4

    # 1. Load pinned memories from files — always included, bypass ranking
    pinned_sections: list[str] = []
    pinned_ids: set[str] = set()
    for path in sorted(Path(memory_dir).glob("*.md")):
        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue
        if not post.get("pinned", False) or post.get("suppress", False):
            continue
        topic = str(post.get("topic", path.stem))
        last_updated = str(post.get("last_updated", ""))
        content = post.content
        if "## Synthesized Memory" in content:
            synthesized = content.split("## Synthesized Memory")[1].strip()
            lines = [ln for ln in synthesized.splitlines() if not ln.startswith("_Last synthesized")]
            synthesized = "\n".join(lines).strip()
        else:
            synthesized = content.strip()
        if synthesized:
            pinned_sections.append(f"**{topic}** (updated: {last_updated})\n{synthesized}")
            pinned_ids.add(f"mem:{path.name}")

    # 2. Build query — fall back to file-based if no usable signals
    query_string = build_query_string(query_signals)
    if not query_string:
        return _retrieve_memories_file_based(memory_dir, token_budget)

    # 3. Query Pinecone
    mem_matches, obs_matches = query_pinecone(pinecone_config, query_string)

    # 4. Post-filter and load memory results (skip pinned — already loaded above)
    context_sections: list[str] = []
    for match in mem_matches:
        if match.id in pinned_ids:
            continue  # deduplicate: pinned already included
        metadata = match.metadata or {}
        expires_str = str(metadata.get("expires", ""))
        try:
            if expires_str and date.fromisoformat(expires_str) < today:
                continue
        except ValueError:
            pass
        section = _load_memory_section(memory_dir, match.id)
        if section:
            context_sections.append(section)

    # 5. Format observation lines from metadata
    obs_lines: list[str] = []
    for match in obs_matches:
        metadata = match.metadata or {}
        obs_date = metadata.get("date", "")
        obs_type = metadata.get("type", "")
        preview = metadata.get("content_preview", "")
        if preview:
            obs_lines.append(f"[{obs_date}] {obs_type}: {preview}")

    # 6. Nothing to show
    if not pinned_sections and not context_sections and not obs_lines:
        return ""

    # 7. Build output within token budget
    # Pinned sections are always included (no budget cap — matches file-based behaviour)
    pinned_chars = sum(len(s) for s in pinned_sections)
    header = "## Cross-Day Memory"
    remaining = char_budget - len(header) - pinned_chars
    mem_budget = int(remaining * 0.6)
    obs_budget = remaining - mem_budget

    trimmed_context: list[str] = []
    used = 0
    for section in context_sections:
        if used + len(section) > mem_budget:
            break
        trimmed_context.append(section)
        used += len(section)

    trimmed_obs: list[str] = []
    used = 0
    for line in obs_lines:
        if used + len(line) > obs_budget:
            break
        trimmed_obs.append(line)
        used += len(line)

    output_parts = [header]
    all_context = pinned_sections + trimmed_context
    if all_context:
        output_parts.append("### Context\n\n" + "\n\n".join(all_context))
    if trimmed_obs:
        output_parts.append("### Recent Signals\n\n" + "\n".join(trimmed_obs))

    return "\n\n".join(output_parts)
```

- [ ] **Step 8: Replace retrieve_memories with new public signature**

Replace the old `retrieve_memories` function (which was renamed to `_retrieve_memories_file_based` in step 6) with this new version:

```python
def retrieve_memories(
    memory_dir: str,
    token_budget: int = 550,
    pinecone_config: Optional[dict] = None,
    query_signals: Optional[dict] = None,
) -> str:
    """Retrieve cross-day memory context for the brief.

    With pinecone_config and query_signals: uses semantic retrieval (mode controlled by
    pinecone_config["retrieval_mode"]: "auto" | "semantic" | "file").
    Without pinecone_config: always file-based (backward-compatible).
    """
    mode = "file"
    if pinecone_config:
        mode = pinecone_config.get("retrieval_mode", "auto")

    if mode == "file" or not pinecone_config:
        return _retrieve_memories_file_based(memory_dir, token_budget)

    try:
        return _retrieve_memories_semantic(
            memory_dir, token_budget, pinecone_config, query_signals or {}
        )
    except Exception as exc:
        if mode == "semantic":
            raise
        print(
            f"WARNING: Pinecone retrieval failed ({exc}), falling back to file-based.",
            file=sys.stderr,
        )
        return _retrieve_memories_file_based(memory_dir, token_budget)
```

- [ ] **Step 9: Run the full test suite**

```bash
pytest tests/test_memory_retriever.py -v
```
Expected: All tests PASS — both the original file-based tests and the new semantic tests.

- [ ] **Step 10: Commit**

```bash
git add processors/memory_retriever.py tests/test_memory_retriever.py
git commit -m "feat(p14): implement semantic retrieval path in memory_retriever with Pinecone + fallback"
```

---

## Task 4: Wire main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Locate the retrieve_memories call in main.py**

The call is in `_run_inner()`, around line 211–215:

```python
memory_context = retrieve_memories(
    memory_dir=memory_cfg["dir"],
    token_budget=memory_cfg.get("retrieval_token_budget", 1500),
)
```

- [ ] **Step 2: Replace the call with the signal-aware version**

Replace the block above with:

```python
_vector_cfg = config.get("vector", {})
_pinecone_key = os.environ.get("PINECONE_API_KEY", "")
_voyage_key = os.environ.get("VOYAGE_API_KEY", "")
_pinecone_cfg = None
if _vector_cfg.get("enabled") and _pinecone_key and _voyage_key:
    _pinecone_cfg = {
        "api_key": _pinecone_key,
        "voyage_api_key": _voyage_key,
        "index_name": _vector_cfg["index_name"],
        "embedding_model": _vector_cfg["embedding_model"],
        "observations_namespace": _vector_cfg.get("observations_namespace", "observations"),
        "memories_namespace": _vector_cfg.get("memories_namespace", "memories"),
        "retrieval_mode": _vector_cfg.get("retrieval_mode", "auto"),
    }
memory_context = retrieve_memories(
    memory_dir=memory_cfg["dir"],
    token_budget=memory_cfg.get("retrieval_token_budget", 1500),
    pinecone_config=_pinecone_cfg,
    query_signals={
        "calendar_events": [e.summary for e in today_events + tomorrow_events],
        "email_subjects": [t.subject for t in email_threads[:10]],
        "pipeline_lead_names": [l.name for l in trial_leads + attention_leads],
        "issue_titles": [i.title for i in open_issues],
    },
)
```

Note: `trial_leads` and `attention_leads` are already initialized to `[]` before the pipeline block (line 151–152), so this is safe even when `pipeline.enabled` is false.

- [ ] **Step 3: Run the full test suite**

```bash
pytest tests/ -v --ignore=tests/test_memory_retriever_integration.py
```
Expected: All existing tests PASS. The new `main.py` code is only exercised at runtime — the unit tests mock at the `retrieve_memories` level.

- [ ] **Step 4: Dry run locally**

```bash
python main.py --no-email
```
Expected: Brief generates. If `PINECONE_API_KEY` and `VOYAGE_API_KEY` are in `.env`, you'll see semantic retrieval output in the brief (`### Context` / `### Recent Signals` sections). If keys are absent, file-based retrieval runs silently as before.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat(p14): pass query signals and pinecone config to retrieve_memories in main"
```

---

## Task 5: Integration test with real Pinecone

**Files:**
- Create: `tests/test_memory_retriever_integration.py`

This test runs against the live Pinecone index. It is skipped in CI if API keys aren't set (same pattern as `test_vector_ingest_integration.py`).

- [ ] **Step 1: Write integration test**

Create `tests/test_memory_retriever_integration.py`:

```python
import json
import os
import tempfile

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("PINECONE_API_KEY") or not os.environ.get("VOYAGE_API_KEY"),
    reason="PINECONE_API_KEY and VOYAGE_API_KEY not set — skipping integration test",
)

from processors.memory_retriever import retrieve_memories


@pytest.fixture
def memory_dir_with_file(tmp_path):
    import frontmatter
    from datetime import date, timedelta

    content = "## Synthesized Memory\n\nApex Gym has been flagged stale for 8 days.\n\n_Last synthesized: 2026-04-29_"
    post = frontmatter.Post(
        content,
        topic="apex-stale",
        created="2026-04-20",
        last_updated="2026-04-29",
        expires=(date.today() + timedelta(days=90)).isoformat(),
        pinned=False,
        suppress=False,
    )
    path = tmp_path / "apex-stale.md"
    with open(path, "wb") as f:
        frontmatter.dump(post, f)
    return str(tmp_path)


def test_semantic_retrieval_returns_non_empty_result(memory_dir_with_file):
    with open("config.json") as f:
        cfg = json.load(f)

    vector_cfg = cfg.get("vector", {})
    pinecone_cfg = {
        "api_key": os.environ["PINECONE_API_KEY"],
        "voyage_api_key": os.environ["VOYAGE_API_KEY"],
        "index_name": vector_cfg.get("index_name", "chief-of-staff"),
        "embedding_model": vector_cfg.get("embedding_model", "voyage-3-lite"),
        "observations_namespace": vector_cfg.get("observations_namespace", "observations"),
        "memories_namespace": vector_cfg.get("memories_namespace", "memories"),
        "retrieval_mode": "semantic",
    }

    result = retrieve_memories(
        memory_dir=memory_dir_with_file,
        token_budget=1500,
        pinecone_config=pinecone_cfg,
        query_signals={
            "calendar_events": ["Demo with Apex Gym"],
            "email_subjects": ["Contract renewal"],
            "pipeline_lead_names": ["Apex Gym", "TGMC"],
            "issue_titles": ["Follow up on stale deals"],
        },
    )

    # Should have the structured output
    assert "## Cross-Day Memory" in result
    # At least one section should be present (index has data from Phase 1 backfill)
    assert "### Context" in result or "### Recent Signals" in result


def test_semantic_retrieval_auto_mode_falls_back_when_index_empty(tmp_path):
    """With an empty local memory dir and real Pinecone, result comes from Pinecone or is empty — no crash."""
    with open("config.json") as f:
        cfg = json.load(f)

    vector_cfg = cfg.get("vector", {})
    pinecone_cfg = {
        "api_key": os.environ["PINECONE_API_KEY"],
        "voyage_api_key": os.environ["VOYAGE_API_KEY"],
        "index_name": vector_cfg.get("index_name", "chief-of-staff"),
        "embedding_model": vector_cfg.get("embedding_model", "voyage-3-lite"),
        "observations_namespace": vector_cfg.get("observations_namespace", "observations"),
        "memories_namespace": vector_cfg.get("memories_namespace", "memories"),
        "retrieval_mode": "auto",
    }

    # No crash, result is a string (may be empty if Pinecone returns nothing usable)
    result = retrieve_memories(
        memory_dir=str(tmp_path),
        token_budget=1500,
        pinecone_config=pinecone_cfg,
        query_signals={
            "calendar_events": ["Team standup"],
            "email_subjects": [],
            "pipeline_lead_names": [],
            "issue_titles": [],
        },
    )
    assert isinstance(result, str)
```

- [ ] **Step 2: Run locally (requires API keys in .env)**

```bash
pytest tests/test_memory_retriever_integration.py -v -s
```
Expected: Both tests pass. The first test should return a result with `### Context` or `### Recent Signals` if the Pinecone index has data from Phase 1 runs.

- [ ] **Step 3: Verify the brief output looks right**

```bash
python main.py --no-email 2>&1 | head -60
```
Open the generated draft and check that the Memory section in the brief has `### Context` and `### Recent Signals` subsections with semantically relevant content — not just the most recently updated files.

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory_retriever_integration.py
git commit -m "test(p14): add Pinecone integration test for semantic memory retrieval"
```

---

## Task 6: Update BACKLOG.md and CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `BACKLOG.md`

- [ ] **Step 1: Update Vector Memory section in CLAUDE.md**

Find the line:
```
Phase 1 (current): ingest only. Phase 2: semantic retrieval replaces recency-based memory retriever. Phase 3: semantic Telegram queries.
```

Replace with:
```
Phase 1 (complete): ingest only. Phase 2 (complete): semantic retrieval replaces recency-based memory retriever. Brief context now split into `### Context` (ranked synthesized memories) and `### Recent Signals` (ranked raw observations). Phase 3: semantic Telegram queries.
```

Also add `retrieval_mode` to the config note:

Find:
```
GitHub Secrets required: `PINECONE_API_KEY`, `VOYAGE_API_KEY`
```

Replace with:
```
`config.json` vector block: `retrieval_mode` controls retrieval strategy — `"auto"` (Pinecone with file-based fallback), `"semantic"` (Pinecone, raises on error), `"file"` (always file-based). Default: `"auto"`.

GitHub Secrets required: `PINECONE_API_KEY`, `VOYAGE_API_KEY`
```

- [ ] **Step 2: Update BACKLOG.md**

Find the P14 Phase 2 entry in the open items list and mark it complete. Add the shipped date. Add P14 Phase 3 as next up.

Update or add:
```markdown
## ✅ P14 Phase 2 — Semantic Retrieval (complete)

**Shipped YYYY-MM-DD.** `memory_retriever.py` now queries Pinecone instead of loading `.md` files by recency. Query built from today's calendar events, email subjects, active pipeline lead names, and open issue titles. Output split into `### Context` (synthesized memories, 60% of token budget) and `### Recent Signals` (raw observations, 40%). Pinned memories bypass ranking and always appear first. Expired memories filtered post-query in Python. Falls back to file-based retrieval on any Pinecone error (`retrieval_mode="auto"`). `retrieval_mode` config field controls behavior.

**Next:** Phase 3 — semantic Telegram queries (replace `_load_local_context` memory dump in `query.py` with vector retrieval using the user's query text as the embedding).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md BACKLOG.md
git commit -m "docs(p14): mark Phase 2 complete, update CLAUDE.md and BACKLOG.md"
```

---

## Self-review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Replace recency retriever with semantic search | Task 3 (`_retrieve_memories_semantic`) |
| Query built from calendar + email + pipeline + issues | Task 2 (`build_query_string`) |
| Voyage AI `input_type="query"` on retrieval side | Task 3 (`query_pinecone`) |
| Pinned memories bypass ranking | Task 3 (pinned loaded from files, added to `### Context` first) |
| Pinned dedup if also in vector results | Task 3 (`pinned_ids` set) |
| Post-filter expired in Python | Task 3 (metadata `expires` check + `_load_memory_section` double-check) |
| `### Context` + `### Recent Signals` sections | Task 3 (`_retrieve_memories_semantic` output format) |
| Memories first (60%), observations second (40%) | Task 3 (budget split) |
| `retrieval_mode: "auto"/"semantic"/"file"` | Tasks 1, 3, 4 |
| Fallback to file-based on error (auto mode) | Task 3 (`retrieve_memories` try/except) |
| Wire main.py with all four signal types | Task 4 |
| Integration test | Task 5 |
| `query.py` (Telegram) NOT touched | Out of scope — Phase 3 |

**Known Phase 3 entry point:**

`processors/query.py` line 36–41: `_load_local_context` calls `retrieve_memories` without `pinecone_config`. Phase 3 changes this to pass the user's Telegram query text as the embedding query (replacing `build_query_string` signal construction with the raw query string). The function signature change in Phase 2 is already backward-compatible for this.

**One thing to watch during testing:**

The `_retrieve_memories_semantic` function calls `_retrieve_memories_file_based` as its fallback when `query_string` is empty. If `pinned_sections` were already loaded before the fallback, they'd be shown twice (once from the fallback, which also loads pinned). This is acceptable — the fallback is only triggered when `query_signals` is completely empty, which only happens if all four collectors failed simultaneously (extremely rare). If it becomes an issue in practice, add a `return ""` after `_retrieve_memories_file_based(...)` when `query_string` is empty but `pinned_sections` is non-empty.
