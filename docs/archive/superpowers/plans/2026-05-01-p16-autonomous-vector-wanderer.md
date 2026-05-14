# P16 — Autonomous Vector Wanderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a nightly autonomous agent (`scripts/wanderer.py`) that explores the Pinecone vector DB using a Claude tool-use loop, surfaces interesting patterns via Telegram, and optionally writes findings back as memory files.

**Architecture:** A standalone script (`scripts/wanderer.py`) imports no brief pipeline code. It seeds Claude with recent wanderer memories (anti-rut), runs a tool-use loop (Claude calls `query_semantic` and `filter_records` iteratively), parses Claude's JSON final response, sends a Telegram message via the existing `lib/telegram.py`, and optionally writes a new `data/memory/wanderer_*.md` file. A new `wanderer.yml` GitHub Actions workflow runs this nightly at 11pm CDT.

**Tech Stack:** Python 3.11, `anthropic>=0.40.0`, `voyageai>=0.2.4`, `pinecone>=5.0.0`, `python-frontmatter>=1.0.0`, `pytest`, `lib/telegram.py` (already exists)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/wanderer.py` | Create | Full wanderer: memory loader, system prompt, tool executor, loop, output |
| `tests/test_wanderer.py` | Create | Unit tests for all testable functions |
| `.github/workflows/wanderer.yml` | Create | Nightly GitHub Actions job |

**Nothing else is modified.** `main.py`, `memory_retriever.py`, and all brief processors are untouched.

---

## Task 1: Test scaffold + `load_wanderer_memories`

Reads `data/memory/*.md` files tagged `source: wanderer`, returns the last N sorted by `last_updated` descending.

**Files:**
- Create: `scripts/wanderer.py` (skeleton + first function)
- Create: `tests/test_wanderer.py`

- [ ] **Step 1: Create the wanderer skeleton**

```python
#!/usr/bin/env python3
"""Nightly autonomous vector wanderer."""

import json
import math
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import frontmatter

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def load_wanderer_memories(memory_dir: str, limit: int = 5) -> list[dict]:
    """Return up to `limit` wanderer-tagged memory files sorted by last_updated desc."""
    results = []
    try:
        paths = sorted(Path(memory_dir).glob("*.md"))
    except (FileNotFoundError, OSError):
        return []

    for path in paths:
        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue
        if post.get("source") != "wanderer":
            continue
        results.append({
            "topic": str(post.get("topic", path.stem)),
            "last_updated": str(post.get("last_updated", "")),
            "content": post.content.strip(),
        })

    results.sort(key=lambda x: x["last_updated"], reverse=True)
    return results[:limit]
```

- [ ] **Step 2: Write failing tests for `load_wanderer_memories`**

```python
# tests/test_wanderer.py
import json
import math
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.wanderer import (
    load_wanderer_memories,
    parse_final_response,
    write_wanderer_memory,
    _format_matches,
    build_system_prompt,
)


def _write_memory(tmp_path, filename, topic, source, last_updated, content):
    text = f"""---
topic: {topic}
source: {source}
last_updated: {last_updated}
expires: 2026-06-01
pinned: false
suppress: false
---

{content}
"""
    (tmp_path / filename).write_text(text)


def test_load_wanderer_memories_empty_dir(tmp_path):
    result = load_wanderer_memories(str(tmp_path))
    assert result == []


def test_load_wanderer_memories_skips_non_wanderer(tmp_path):
    _write_memory(tmp_path, "regular.md", "pipeline", "brief", "2026-05-01", "some content")
    result = load_wanderer_memories(str(tmp_path))
    assert result == []


def test_load_wanderer_memories_returns_wanderer_files(tmp_path):
    _write_memory(tmp_path, "wanderer_foo_2026-05-01.md", "Foo Finding", "wanderer", "2026-05-01", "foo content")
    result = load_wanderer_memories(str(tmp_path))
    assert len(result) == 1
    assert result[0]["topic"] == "Foo Finding"
    assert result[0]["content"] == "foo content"


def test_load_wanderer_memories_sorted_by_last_updated(tmp_path):
    _write_memory(tmp_path, "w1.md", "Old", "wanderer", "2026-04-28", "old")
    _write_memory(tmp_path, "w2.md", "New", "wanderer", "2026-05-01", "new")
    _write_memory(tmp_path, "w3.md", "Mid", "wanderer", "2026-04-30", "mid")
    result = load_wanderer_memories(str(tmp_path))
    assert [r["topic"] for r in result] == ["New", "Mid", "Old"]


def test_load_wanderer_memories_respects_limit(tmp_path):
    for i in range(8):
        _write_memory(tmp_path, f"w{i}.md", f"Topic {i}", "wanderer", f"2026-05-0{i % 9 + 1}", f"content {i}")
    result = load_wanderer_memories(str(tmp_path), limit=3)
    assert len(result) == 3


def test_load_wanderer_memories_missing_dir():
    result = load_wanderer_memories("/nonexistent/path/memory")
    assert result == []
```

- [ ] **Step 3: Run tests — expect failures**

```bash
cd /path/to/chief-of-staff
pytest tests/test_wanderer.py::test_load_wanderer_memories_empty_dir -v
```

Expected: some pass, some fail with `ImportError` (other functions not yet defined).

- [ ] **Step 4: Commit skeleton**

```bash
git add scripts/wanderer.py tests/test_wanderer.py
git commit -m "feat(wanderer): scaffold wanderer script and load_wanderer_memories"
```

---

## Task 2: `parse_final_response`

Extracts the JSON block from Claude's final response text. Falls back to raw text if JSON is missing or malformed.

**Files:**
- Modify: `scripts/wanderer.py` (add function)
- Modify: `tests/test_wanderer.py` (add tests)

- [ ] **Step 1: Write failing tests for `parse_final_response`**

Add to `tests/test_wanderer.py`:

```python
def test_parse_final_response_clean_json():
    text = '{"telegram": "hello", "memory": {"topic": "foo", "content": "bar", "expires": "2026-05-15"}}'
    result = parse_final_response(text)
    assert result["telegram"] == "hello"
    assert result["memory"]["topic"] == "foo"


def test_parse_final_response_json_in_code_fence():
    text = 'Some preamble\n```json\n{"telegram": "hello"}\n```\nsome trailing text'
    result = parse_final_response(text)
    assert result["telegram"] == "hello"


def test_parse_final_response_json_embedded_in_text():
    text = 'Here is my analysis:\n{"telegram": "finding", "memory": {"topic": "x", "content": "y", "expires": "2026-06-01"}}\nDone.'
    result = parse_final_response(text)
    assert result["telegram"] == "finding"


def test_parse_final_response_malformed_json_falls_back():
    text = "Claude said something but forgot JSON entirely"
    result = parse_final_response(text)
    assert result["telegram"] == text
    assert "memory" not in result


def test_parse_final_response_no_memory_field():
    text = '{"telegram": "just a message"}'
    result = parse_final_response(text)
    assert result["telegram"] == "just a message"
    assert "memory" not in result
```

- [ ] **Step 2: Run tests — expect failures**

```bash
pytest tests/test_wanderer.py -k "parse_final_response" -v
```

Expected: `ImportError` on `parse_final_response`.

- [ ] **Step 3: Implement `parse_final_response`**

Add to `scripts/wanderer.py`:

```python
def parse_final_response(text: str) -> dict:
    """Extract JSON from Claude's final response. Falls back to raw text as telegram."""
    # Try ```json ... ``` fence first
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding outermost { ... } in the text
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: treat entire response as the telegram message
    return {"telegram": text}
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_wanderer.py -k "parse_final_response" -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/wanderer.py tests/test_wanderer.py
git commit -m "feat(wanderer): add parse_final_response"
```

---

## Task 3: `write_wanderer_memory`

Writes a `data/memory/wanderer_{slug}_{date}.md` file from Claude's memory dict.

**Files:**
- Modify: `scripts/wanderer.py`
- Modify: `tests/test_wanderer.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_wanderer.py`:

```python
def test_write_wanderer_memory_creates_file(tmp_path):
    memory = {
        "topic": "cancellation-reason-clustering",
        "content": "Business Changes is the top cancellation reason this month.",
        "expires": "2026-05-15",
    }
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    assert os.path.exists(path)
    assert "wanderer_cancellation-reason-clustering_2026-05-01" in path


def test_write_wanderer_memory_frontmatter(tmp_path):
    memory = {"topic": "bug-clustering", "content": "Many bugs in mobile.", "expires": "2026-05-15"}
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    post = frontmatter.load(path)
    assert post["source"] == "wanderer"
    assert post["last_updated"] == "2026-05-01"
    assert post["expires"] == "2026-05-15"
    assert post.content.strip() == "Many bugs in mobile."


def test_write_wanderer_memory_default_expires(tmp_path):
    memory = {"topic": "some-finding", "content": "content"}
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    post = frontmatter.load(path)
    assert post["expires"] == "2026-05-15"  # 14 days from 2026-05-01


def test_write_wanderer_memory_topic_display_name(tmp_path):
    memory = {"topic": "stale-pipeline-leads", "content": "content", "expires": "2026-05-15"}
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    post = frontmatter.load(path)
    assert post["topic"] == "Stale Pipeline Leads"


def test_write_wanderer_memory_slug_sanitized(tmp_path):
    memory = {"topic": "Bug Clusters: Mobile & Payments", "content": "c", "expires": "2026-05-15"}
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    assert "wanderer_bug-clusters-mobile-payments_2026-05-01" in path
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_wanderer.py -k "write_wanderer_memory" -v
```

- [ ] **Step 3: Implement `write_wanderer_memory`**

Add to `scripts/wanderer.py`:

```python
def _topic_slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower().strip()).strip("-")[:50]


def write_wanderer_memory(memory_dir: str, memory: dict, today: str) -> str:
    """Write a wanderer memory .md file. Returns the file path written."""
    topic = memory.get("topic", "finding")
    content = memory.get("content", "").strip()
    expires = memory.get(
        "expires",
        (date.fromisoformat(today) + timedelta(days=14)).isoformat(),
    )

    slug = _topic_slug(topic)
    display_topic = topic.replace("-", " ").title()
    filename = f"wanderer_{slug}_{today}.md"
    path = os.path.join(memory_dir, filename)

    text = (
        f"---\n"
        f"topic: {display_topic}\n"
        f"source: wanderer\n"
        f"last_updated: {today}\n"
        f"expires: {expires}\n"
        f"pinned: false\n"
        f"suppress: false\n"
        f"---\n\n"
        f"{content}\n"
    )

    os.makedirs(memory_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return path
```

Add `import frontmatter` to the test file at the top (it's already needed for `_write_memory` helper).

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_wanderer.py -k "write_wanderer_memory" -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/wanderer.py tests/test_wanderer.py
git commit -m "feat(wanderer): add write_wanderer_memory"
```

---

## Task 4: Tool result formatter + `execute_query_semantic` + `execute_filter_records`

These are the Python functions that back Claude's tools. The formatter turns Pinecone matches into a readable string Claude can reason over.

**Files:**
- Modify: `scripts/wanderer.py`
- Modify: `tests/test_wanderer.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_wanderer.py`:

```python
def test_format_matches_empty():
    assert _format_matches([]) == "No results found."


def test_format_matches_formats_fields():
    match = MagicMock()
    match.id = "lead:abc123"
    match.score = 0.87
    match.metadata = {"name": "Tyler Landeck", "status": "In-Trial", "content_preview": "Pipeline lead: Tyler"}
    result = _format_matches([match])
    assert "lead:abc123" in result
    assert "0.870" in result
    assert "Tyler Landeck" in result
    assert "Pipeline lead: Tyler" in result


def test_execute_query_semantic_calls_voyage_and_pinecone():
    mock_voyage = MagicMock()
    mock_voyage.embed.return_value = MagicMock(embeddings=[[0.1] * 512])

    match = MagicMock()
    match.id = "bug:xyz"
    match.score = 0.9
    match.metadata = {"title": "Login crash", "content_preview": "Bug: Login crash"}
    mock_index = MagicMock()
    mock_index.query.return_value = MagicMock(matches=[match])

    from scripts.wanderer import execute_query_semantic
    result = execute_query_semantic(mock_voyage, mock_index, "login bugs", "raw_data", top_k=5)

    mock_voyage.embed.assert_called_once_with(["login bugs"], model="voyage-3-lite", input_type="query")
    mock_index.query.assert_called_once_with(
        vector=[0.1] * 512,
        top_k=5,
        namespace="raw_data",
        include_metadata=True,
    )
    assert "bug:xyz" in result


def test_execute_filter_records_calls_pinecone_with_filter():
    match = MagicMock()
    match.id = "bug:001"
    match.score = 0.0
    match.metadata = {"priority_level": "High", "content_preview": "High priority bug"}
    mock_index = MagicMock()
    mock_index.query.return_value = MagicMock(matches=[match])

    from scripts.wanderer import execute_filter_records
    result = execute_filter_records(mock_index, "raw_data", {"priority_level": {"$eq": "High"}}, top_k=10)

    call_kwargs = mock_index.query.call_args[1]
    assert call_kwargs["namespace"] == "raw_data"
    assert call_kwargs["filter"] == {"priority_level": {"$eq": "High"}}
    assert call_kwargs["top_k"] == 10
    assert call_kwargs["include_metadata"] is True
    assert "bug:001" in result
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_wanderer.py -k "format_matches or execute_query or execute_filter" -v
```

- [ ] **Step 3: Implement the three functions**

Add to `scripts/wanderer.py`:

```python
# Normalized dummy vector for metadata-only filter queries (cosine-safe with voyage-3-lite 512 dims)
_DUMMY_VECTOR = [1.0 / math.sqrt(512)] * 512


def _format_matches(matches: list) -> str:
    """Format Pinecone query results as a readable string for Claude."""
    if not matches:
        return "No results found."
    parts = []
    for m in matches:
        meta = m.metadata or {}
        score = getattr(m, "score", None)
        score_str = f" (score: {score:.3f})" if score is not None else ""
        preview = meta.get("content_preview", "")
        meta_str = json.dumps({k: v for k, v in meta.items() if k != "content_preview"}, default=str)
        parts.append(f"ID: {m.id}{score_str}\nMetadata: {meta_str}\nPreview: {preview}")
    return "\n\n".join(parts)


def execute_query_semantic(
    voyage_client,
    pc_index,
    query: str,
    namespace: str,
    top_k: int = 10,
    embedding_model: str = "voyage-3-lite",
) -> str:
    """Embed query via Voyage and search Pinecone. Returns formatted result string."""
    result = voyage_client.embed([query], model=embedding_model, input_type="query")
    query_vector = result.embeddings[0]
    response = pc_index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )
    return _format_matches(response.matches)


def execute_filter_records(
    pc_index,
    namespace: str,
    filters: dict,
    top_k: int = 20,
) -> str:
    """Metadata filter query against Pinecone. Uses dummy vector (scores are irrelevant)."""
    response = pc_index.query(
        vector=_DUMMY_VECTOR,
        top_k=top_k,
        namespace=namespace,
        filter=filters,
        include_metadata=True,
    )
    return _format_matches(response.matches)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_wanderer.py -k "format_matches or execute_query or execute_filter" -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/wanderer.py tests/test_wanderer.py
git commit -m "feat(wanderer): add tool executor functions"
```

---

## Task 5: `build_system_prompt`

Assembles the system prompt Claude receives at the start of the loop: namespace schema, today's date, recent wanderer memories, and budget instructions.

**Files:**
- Modify: `scripts/wanderer.py`
- Modify: `tests/test_wanderer.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_wanderer.py`:

```python
def test_build_system_prompt_contains_today():
    prompt = build_system_prompt("2026-05-01", [], "")
    assert "2026-05-01" in prompt


def test_build_system_prompt_no_memories_section():
    prompt = build_system_prompt("2026-05-01", [], "")
    assert "No previous findings" in prompt


def test_build_system_prompt_includes_memories():
    memories = [
        {"topic": "Cancellation Clustering", "last_updated": "2026-04-30", "content": "Business Changes is dominant."},
    ]
    prompt = build_system_prompt("2026-05-01", memories, "")
    assert "Cancellation Clustering" in prompt
    assert "Business Changes is dominant" in prompt


def test_build_system_prompt_contains_query_limit():
    prompt = build_system_prompt("2026-05-01", [], "")
    assert "15" in prompt
    assert "20" in prompt


def test_build_system_prompt_contains_json_instruction():
    prompt = build_system_prompt("2026-05-01", [], "")
    assert '"telegram"' in prompt
    assert '"memory"' in prompt
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_wanderer.py -k "build_system_prompt" -v
```

- [ ] **Step 3: Implement `build_system_prompt`**

Add to `scripts/wanderer.py`:

```python
_NAMESPACE_SCHEMA = """
**observations** — daily signals written by the morning brief system.
  Metadata fields: type (pipeline_staleness | email_loop | top_priorities | kpi_snapshot), date (YYYY-MM-DD), entity, content_preview.
  kpi_snapshot entries have structured context in content_preview: sales_revenue, demos, open_bugs, cancellations_mtd.

**memories** — synthesized cross-day context files on ongoing topics.
  Metadata fields: topic, last_updated, expires, pinned, content_preview.

**raw_data** — individual operational records. Distinguish by ID prefix:
  lead:{id}   → pipeline leads.    Metadata: name, status, priority, days_since_contact, stale (bool), source, email.
  bug:{id}    → bug tickets.       Metadata: title, status, priority_level, technical_areas (list), date_created, days_open, shortcut_url.
  cancel:{id} → cancellations.     Metadata: date, account_name, reason, base_plan, monetary_value, customer_returned.
  sale:{id}   → sales entries.     Metadata: date, customer, total, sale_type, salesperson.

filter_records filter syntax (Pinecone):
  Exact match:       {"field": {"$eq": "value"}}
  Set membership:    {"field": {"$in": ["a", "b"]}}
  Boolean:           {"field": {"$eq": true}}
  Numeric gt/lt:     {"field": {"$gt": 7}}
  Combine (AND):     {"field1": {"$eq": "x"}, "field2": {"$gt": 3}}
"""


def build_system_prompt(today: str, wanderer_memories: list[dict], namespace_schema: str = "") -> str:
    schema = namespace_schema or _NAMESPACE_SCHEMA

    if wanderer_memories:
        mem_lines = []
        for m in wanderer_memories:
            mem_lines.append(
                f"**{m['topic']}** (found: {m['last_updated']})\n{m['content']}"
            )
        memories_section = "\n\n".join(mem_lines)
        memories_instruction = (
            "These are your recent findings. Revisit them only if there is meaningfully new data "
            "since you last looked. Otherwise, explore elsewhere."
        )
    else:
        memories_section = "No previous findings — explore freely."
        memories_instruction = ""

    return f"""You are the Wanderer — an autonomous analyst running nightly over TeamBuildr OS's operational data.
TeamBuildr OS is a B2B SaaS platform for strength and conditioning coaches. The VP of Sales is Trent Luecke.

Today is {today}.

You have access to a Pinecone vector DB with three namespaces:
{schema}

**Your recent findings** (previous nights):
{memories_section}
{memories_instruction}

**Your task:** Explore the data autonomously. Look for patterns, anomalies, or connections worth surfacing — things that might not be obvious from a single day's brief. You decide what to investigate and in what order.

**Constraints:**
- Aim to conclude within ~15 queries. Hard limit: 20.
- When done exploring, respond with ONLY a valid JSON object (no preamble, no trailing text):

```json
{{
  "telegram": "🔍 Wanderer — {today}\\n\\n[your finding, ≤1500 characters]",
  "memory": {{
    "topic": "short-topic-slug",
    "content": "Cross-day finding worth carrying into future briefs...",
    "expires": "YYYY-MM-DD"
  }}
}}
```

Include "memory" only if the finding has cross-day significance worth surfacing in future morning briefs.
Omit "memory" for ephemeral or day-specific observations.
If you include "memory", set "expires" to 14 days from today ({(date.fromisoformat(today) + timedelta(days=14)).isoformat()}) unless you have reason to choose differently.
Keep the telegram message under 1500 characters — be editorial, surface the single most interesting thing."""
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_wanderer.py -k "build_system_prompt" -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/wanderer.py tests/test_wanderer.py
git commit -m "feat(wanderer): add build_system_prompt"
```

---

## Task 6: `run_tool_loop`

The core Claude tool-use loop. Manages multi-turn conversation, counts tool calls, enforces the hard cap at 20, and returns Claude's final text response.

**Files:**
- Modify: `scripts/wanderer.py`
- Modify: `tests/test_wanderer.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_wanderer.py`:

```python
def _make_text_block(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(tool_id, name, input_dict):
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = input_dict
    return block


def _make_response(stop_reason, content_blocks):
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = content_blocks
    return resp


def test_run_tool_loop_end_turn_immediately():
    from scripts.wanderer import run_tool_loop

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_response(
        "end_turn", [_make_text_block('{"telegram": "done"}')]
    )

    result = run_tool_loop(mock_client, "sys", [], lambda n, i: "result")
    assert result == '{"telegram": "done"}'
    assert mock_client.messages.create.call_count == 1


def test_run_tool_loop_executes_tool_and_continues():
    from scripts.wanderer import run_tool_loop

    tool_block = _make_tool_use_block("tid1", "query_semantic", {"query": "bugs", "namespace": "raw_data"})
    final_block = _make_text_block('{"telegram": "found bugs"}')

    responses = [
        _make_response("tool_use", [tool_block]),
        _make_response("end_turn", [final_block]),
    ]
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = responses

    calls = []
    def executor(name, inp):
        calls.append((name, inp))
        return "Bug results here"

    result = run_tool_loop(mock_client, "sys", [], executor)
    assert result == '{"telegram": "found bugs"}'
    assert calls == [("query_semantic", {"query": "bugs", "namespace": "raw_data"})]
    assert mock_client.messages.create.call_count == 2


def test_run_tool_loop_hard_stop_at_max():
    from scripts.wanderer import run_tool_loop

    # Claude keeps using tools every turn — should hard stop at max_tool_calls
    tool_block = _make_tool_use_block("tid", "query_semantic", {"query": "x", "namespace": "raw_data"})
    final_block = _make_text_block('{"telegram": "stopped"}')

    # 3 tool-use responses then a final response
    responses = [_make_response("tool_use", [tool_block])] * 3 + [_make_response("end_turn", [final_block])]
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = responses

    result = run_tool_loop(mock_client, "sys", [], lambda n, i: "result", max_tool_calls=3)
    assert result == '{"telegram": "stopped"}'
    # After hitting the cap, one more call is made with no tools to get final response
    assert mock_client.messages.create.call_count == 4
```

- [ ] **Step 2: Run — expect failures**

```bash
pytest tests/test_wanderer.py -k "run_tool_loop" -v
```

- [ ] **Step 3: Implement `run_tool_loop`**

Add to `scripts/wanderer.py`:

```python
def run_tool_loop(
    anthropic_client,
    system_prompt: str,
    tools: list,
    tool_executor,
    model: str = "claude-sonnet-4-6",
    max_tool_calls: int = 20,
) -> str:
    """Run Claude tool-use loop. Returns Claude's final text response."""
    messages = []
    tool_call_count = 0

    while True:
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        assistant_content = list(response.content)
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason != "tool_use":
            for block in assistant_content:
                if getattr(block, "type", None) == "text":
                    return block.text
            return ""

        # Execute tool calls; track count
        tool_results = []
        hit_limit = False

        for block in assistant_content:
            if getattr(block, "type", None) != "tool_use":
                continue

            tool_call_count += 1
            if hit_limit or tool_call_count > max_tool_calls:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Query limit reached.",
                })
                hit_limit = True
                continue

            try:
                result = tool_executor(block.name, block.input)
            except Exception as exc:
                result = f"Error executing {block.name}: {exc}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

            if tool_call_count >= max_tool_calls:
                hit_limit = True

        messages.append({"role": "user", "content": tool_results})

        if hit_limit:
            # One final call without tools to force conclusion
            messages.append({
                "role": "user",
                "content": "You've reached your query limit. Write your final JSON response now — no more tool calls.",
            })
            final = anthropic_client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            )
            for block in final.content:
                if getattr(block, "type", None) == "text":
                    return block.text
            return ""
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/test_wanderer.py -k "run_tool_loop" -v
```

Expected: all 3 pass.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/test_wanderer.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/wanderer.py tests/test_wanderer.py
git commit -m "feat(wanderer): add run_tool_loop"
```

---

## Task 7: `main()` + Anthropic tool definitions + top-level error handling

Wires everything together: reads env vars, initializes clients, loads memories, runs the loop, delivers via Telegram, optionally writes memory.

**Files:**
- Modify: `scripts/wanderer.py` (add `TOOLS` constant + `make_tool_executor` + `main`)

No new tests — `main()` is an integration boundary. The individual functions it calls are already tested.

- [ ] **Step 1: Add Anthropic tool definitions constant**

Add to `scripts/wanderer.py` (after imports, before functions):

```python
TOOLS = [
    {
        "name": "query_semantic",
        "description": (
            "Embed a natural language query and search a Pinecone namespace for semantically similar records. "
            "Use this to find patterns, trends, or specific record types by describing what you're looking for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query string."},
                "namespace": {
                    "type": "string",
                    "enum": ["observations", "memories", "raw_data"],
                    "description": "Pinecone namespace to search.",
                },
                "top_k": {"type": "integer", "description": "Number of results (default: 10).", "default": 10},
            },
            "required": ["query", "namespace"],
        },
    },
    {
        "name": "filter_records",
        "description": (
            "Query a Pinecone namespace using metadata filters without embedding. "
            "Use for structured lookups: all High-priority bugs, cancellations by reason, stale leads, etc. "
            'Filter syntax: {"field": {"$eq": "value"}}, {"field": {"$in": ["a","b"]}}, {"field": {"$gt": 7}}, {"field": {"$eq": true}}.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "enum": ["observations", "memories", "raw_data"],
                    "description": "Pinecone namespace to filter.",
                },
                "filters": {"type": "object", "description": "Pinecone metadata filter dict."},
                "top_k": {"type": "integer", "description": "Max results (default: 20).", "default": 20},
            },
            "required": ["namespace", "filters"],
        },
    },
]
```

- [ ] **Step 2: Add `make_tool_executor`**

Add to `scripts/wanderer.py`:

```python
def make_tool_executor(voyage_client, pc_index, embedding_model: str = "voyage-3-lite"):
    """Return a callable that dispatches tool calls to the appropriate executor."""
    def executor(tool_name: str, tool_input: dict) -> str:
        if tool_name == "query_semantic":
            return execute_query_semantic(
                voyage_client,
                pc_index,
                query=tool_input["query"],
                namespace=tool_input["namespace"],
                top_k=tool_input.get("top_k", 10),
                embedding_model=embedding_model,
            )
        elif tool_name == "filter_records":
            return execute_filter_records(
                pc_index,
                namespace=tool_input["namespace"],
                filters=tool_input["filters"],
                top_k=tool_input.get("top_k", 20),
            )
        else:
            return f"Unknown tool: {tool_name}"
    return executor
```

- [ ] **Step 3: Add `main()`**

Add to `scripts/wanderer.py`:

```python
def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")

    import anthropic
    import voyageai
    from pinecone import Pinecone
    from lib.telegram import send_message

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")

    for name, val in [
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("PINECONE_API_KEY", pinecone_key),
        ("VOYAGE_API_KEY", voyage_key),
        ("TELEGRAM_BOT_TOKEN", telegram_token),
        ("TELEGRAM_CHAT_ID", telegram_chat),
    ]:
        if not val:
            print(f"ERROR: {name} not set — wanderer cannot run.", file=sys.stderr)
            return

    memory_dir = str(_ROOT / "data" / "memory")
    today = date.today().isoformat()
    embedding_model = "voyage-3-lite"
    index_name = "chief-of-staff"

    # Load recent wanderer memories for context seeding
    wanderer_memories = load_wanderer_memories(memory_dir)
    print(f"   Loaded {len(wanderer_memories)} recent wanderer memories.")

    # Initialize clients
    vo = voyageai.Client(api_key=voyage_key)
    pc = Pinecone(api_key=pinecone_key)
    pc_index = pc.Index(index_name)
    ac = anthropic.Anthropic(api_key=anthropic_key)

    # Build system prompt and tool executor
    system_prompt = build_system_prompt(today, wanderer_memories)
    tool_executor = make_tool_executor(vo, pc_index, embedding_model)

    # Run the loop
    print("   Starting wanderer tool-use loop...")
    raw_response = run_tool_loop(
        ac, system_prompt, TOOLS, tool_executor,
        model="claude-sonnet-4-6",
        max_tool_calls=20,
    )

    # Parse response
    parsed = parse_final_response(raw_response)
    telegram_text = parsed.get("telegram", "").strip()
    memory_data = parsed.get("memory")

    # Send Telegram
    if telegram_text:
        try:
            send_message(telegram_token, telegram_chat, telegram_text)
            print("   Telegram message sent.")
        except Exception as exc:
            print(f"WARNING: Telegram send failed: {exc}", file=sys.stderr)
    else:
        print("WARNING: No telegram text in response.", file=sys.stderr)

    # Write memory if present
    if memory_data and isinstance(memory_data, dict) and memory_data.get("content"):
        try:
            path = write_wanderer_memory(memory_dir, memory_data, today)
            print(f"   Memory written: {path}")
        except Exception as exc:
            print(f"WARNING: Memory write failed: {exc}", file=sys.stderr)
    else:
        print("   No memory to write.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: Wanderer failed: {exc}", file=sys.stderr)
        sys.exit(0)  # Non-fatal — don't fail the GitHub Actions job
```

- [ ] **Step 4: Run the full test suite to verify nothing broke**

```bash
pytest tests/test_wanderer.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/wanderer.py
git commit -m "feat(wanderer): add main(), TOOLS, and make_tool_executor"
```

---

## Task 8: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/wanderer.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
# .github/workflows/wanderer.yml
name: Nightly Wanderer

on:
  schedule:
    # 11pm CDT (UTC-5, Apr-Oct). Change to "0 5 * * *" in November for CST (UTC-6).
    - cron: "0 4 * * *"
  workflow_dispatch:

jobs:
  run-wanderer:
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

      - name: Run wanderer
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
          VOYAGE_API_KEY: ${{ secrets.VOYAGE_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python scripts/wanderer.py

      - name: Persist data
        run: |
          git config user.name "chief-of-staff[bot]"
          git config user.email "noreply@github.com"
          git add data/
          git diff --cached --quiet && exit 0
          git commit -m "chore: wanderer data update $(date +%Y-%m-%d)"
          git pull --rebase
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/wanderer.yml
git commit -m "feat(wanderer): add nightly wanderer GitHub Actions workflow"
```

---

## Task 9: Smoke test (manual)

Run the wanderer locally against the live Pinecone index to verify end-to-end behavior before the first scheduled run.

- [ ] **Step 1: Run locally with `--no-telegram` dry-run**

Add a temporary dry-run flag to `main()` by setting `TELEGRAM_CHAT_ID` to a test value you can verify, OR patch `send_message` to print instead:

```bash
cd /path/to/chief-of-staff
ANTHROPIC_API_KEY=... PINECONE_API_KEY=... VOYAGE_API_KEY=... TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python scripts/wanderer.py
```

Expected output:
```
   Loaded N recent wanderer memories.
   Starting wanderer tool-use loop...
   Telegram message sent.
   Memory written: data/memory/wanderer_<topic>_<date>.md
   (or: No memory to write.)
```

- [ ] **Step 2: Verify Telegram message arrived**

Check your Telegram chat for a message starting with `🔍 Wanderer —`.

- [ ] **Step 3: Verify memory file (if written)**

```bash
cat data/memory/wanderer_*_$(date +%Y-%m-%d).md
```

Check that frontmatter has `source: wanderer`, correct `last_updated`, and valid `expires`.

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest tests/test_wanderer.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Final commit**

```bash
git add data/memory/
git commit -m "chore: first wanderer run data"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Covered by |
|---|---|
| Claude tool-use loop (iterative agent) | Task 6: `run_tool_loop` |
| `query_semantic` tool | Task 4 + Task 7 |
| `filter_records` tool with Pinecone syntax | Task 4 + Task 7 |
| Soft cap ~15, hard stop at 20 | Task 6: `run_tool_loop` |
| `claude-sonnet-4-6` model | Task 7: `main()` |
| Seed with last 5 wanderer memories | Task 1: `load_wanderer_memories`, Task 5: `build_system_prompt` |
| Anti-rut instruction in system prompt | Task 5: `build_system_prompt` |
| JSON final response with `telegram` + optional `memory` | Task 2: `parse_final_response` |
| Telegram delivery via `lib/telegram.py` | Task 7: `main()` |
| Memory write-back with `source: wanderer` | Task 3: `write_wanderer_memory` |
| 14-day TTL default | Task 3: `write_wanderer_memory` |
| `wanderer_{slug}_{date}.md` filename | Task 3: `write_wanderer_memory` |
| Non-fatal error handling | Task 7: `main()` top-level try/except |
| Separate GitHub Actions workflow, 11pm CDT | Task 8 |
| No modifications to brief pipeline | Enforced by file map |
| No new secrets required | Verified — all 5 secrets already in repo |

All spec requirements covered. No placeholders. Type names are consistent across tasks.
