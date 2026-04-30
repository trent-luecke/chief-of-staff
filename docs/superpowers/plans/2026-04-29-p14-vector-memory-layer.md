# P14 — Vector Memory Layer Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Pinecone vector index alongside the existing file-based memory system. Phase 1 covers ingestion only — embed all observations and synthesized memory files into Pinecone after each daily run. Retrieval changes come in Phase 2.

**Architecture:** New `processors/vector_ingest.py` reads `observations.jsonl` and `data/memory/*.md`, embeds via Voyage AI (`voyage-3-lite`, 512 dims), and upserts raw vectors to a `chief-of-staff` Pinecone index with two namespaces (`observations` and `memories`). Runs after the existing observer and synthesizer in `main.py`. State file tracks last-ingested position to avoid re-embedding old data.

**Tech Stack:** `pinecone` Python SDK, `voyageai` Python SDK, existing `python-frontmatter` for reading memory files

**Design spec:** `docs/superpowers/plans/2026-04-29-p14-vector-memory-layer-design.md`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `processors/vector_ingest.py` | **Create** | Embed observations + memory files, upsert to Pinecone |
| `scripts/create_pinecone_index.py` | **Create** | One-time index creation script |
| `tests/test_vector_ingest.py` | **Create** | Unit tests for ingest logic |
| `main.py` | **Modify** | Wire vector ingest after memory synthesis |
| `config.json` | **Modify** | Add `vector` config block |
| `requirements.txt` | **Modify** | Add `pinecone` SDK |
| `data/vector_ingest_state.json` | **Created at runtime** | Tracks last-ingested observation line and memory file timestamps |

---

## Task 1: Add Pinecone dependency and config

**Files:**
- Modify: `requirements.txt`
- Modify: `config.json`
- Modify: `.gitignore` (if `data/vector_ingest_state.json` should be tracked — it should, same as other state files)

- [ ] **Step 1: Add pinecone and voyageai SDKs to requirements.txt**

Add to `requirements.txt`:
```
pinecone>=5.0.0
voyageai>=0.3.0
```

Install:
```bash
pip install pinecone voyageai
python -c "from pinecone import Pinecone; import voyageai; print('OK')"
```
Expected: `OK`

- [ ] **Step 2: Add vector config block to config.json**

Add inside the top-level JSON object:
```json
"vector": {
  "enabled": true,
  "index_name": "chief-of-staff",
  "embedding_model": "voyage-3-lite",
  "embedding_dimension": 512,
  "observations_namespace": "observations",
  "memories_namespace": "memories",
  "ingest_state_file": "data/vector_ingest_state.json"
}
```

- [ ] **Step 3: Add API keys to .env**

```bash
PINECONE_API_KEY=your-pinecone-api-key-here
VOYAGE_API_KEY=your-voyage-api-key-here
```

Also add both as GitHub Actions secrets for the `brief.yml` workflow.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt config.json
git commit -m "feat(p14): add pinecone dependency and vector config block"
```

---

## Task 2: Create index creation script

**Files:**
- Create: `scripts/create_pinecone_index.py`

This is a one-time setup script run locally. It creates the Pinecone index with the right configuration.

- [ ] **Step 1: Implement scripts/create_pinecone_index.py**

```python
#!/usr/bin/env python3
"""One-time script: create the chief-of-staff Pinecone index."""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from pinecone import Pinecone, ServerlessSpec


def main():
    api_key = os.environ.get("PINECONE_API_KEY", "")
    if not api_key:
        print("ERROR: PINECONE_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    with open("config.json") as f:
        config = json.load(f)

    vector_cfg = config.get("vector", {})
    index_name = vector_cfg.get("index_name", "chief-of-staff")
    dimension = vector_cfg.get("embedding_dimension", 512)

    pc = Pinecone(api_key=api_key)

    # Check if index already exists
    existing = [idx.name for idx in pc.list_indexes()]
    if index_name in existing:
        print(f"Index '{index_name}' already exists. Nothing to do.")
        desc = pc.describe_index(index_name)
        print(f"  Dimension: {desc.dimension}")
        print(f"  Metric: {desc.metric}")
        print(f"  Host: {desc.host}")
        return

    print(f"Creating index '{index_name}' (dim={dimension}, cosine, AWS us-east-1)...")
    pc.create_index(
        name=index_name,
        dimension=dimension,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    print(f"Index '{index_name}' created successfully.")
    desc = pc.describe_index(index_name)
    print(f"  Host: {desc.host}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script locally**

```bash
python scripts/create_pinecone_index.py
```
Expected: Index created. Host URL printed.

- [ ] **Step 3: Verify in Pinecone dashboard**

Go to https://app.pinecone.io and confirm the `chief-of-staff` index exists with the correct dimension and metric.

- [ ] **Step 4: Commit**

```bash
git add scripts/create_pinecone_index.py
git commit -m "feat(p14): add one-time Pinecone index creation script"
```

---

## Task 3: Implement vector_ingest.py

**Files:**
- Create: `processors/vector_ingest.py`
- Create: `tests/test_vector_ingest.py`

This is the core of Phase 1. It reads new observations and updated memory files, embeds them, and upserts to Pinecone.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vector_ingest.py
import json
import os
import tempfile
from datetime import date
from unittest.mock import patch, MagicMock, call

import pytest

from processors.vector_ingest import (
    load_ingest_state,
    save_ingest_state,
    IngestState,
    prepare_observation_records,
    prepare_memory_records,
    build_observation_text,
)


@pytest.fixture
def obs_file(tmp_path):
    lines = [
        {"date": "2026-04-28", "type": "pipeline_stale", "entity": "apex",
         "content": "Apex stale 20 days, status: In-Trial", "source": "pipeline"},
        {"date": "2026-04-28", "type": "top_priority", "entity": "priorities",
         "content": "Follow up on Apex contract renewal", "source": "brief"},
        {"date": "2026-04-29", "type": "email_loop", "entity": "thread:Contract",
         "content": "Thread open multiple days, no reply", "source": "state",
         "context": "Contract renewal discussion with Apex"},
    ]
    path = tmp_path / "observations.jsonl"
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return str(path)


@pytest.fixture
def memory_dir(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    content = """---
topic: apex-trial
created: '2026-04-20'
last_updated: '2026-04-28'
expires: '2026-07-20'
pinned: false
suppress: false
---

## Synthesized Memory

**Pattern:** Apex has been flagged stale for 8 consecutive days.

_Last synthesized: 2026-04-28_
"""
    (mem_dir / "apex-trial.md").write_text(content)
    return str(mem_dir)


def test_load_ingest_state_missing_file(tmp_path):
    state = load_ingest_state(str(tmp_path / "nonexistent.json"))
    assert state.last_obs_line == 0
    assert state.memory_mtimes == {}


def test_save_and_load_ingest_state(tmp_path):
    path = str(tmp_path / "state.json")
    state = IngestState(last_obs_line=42, memory_mtimes={"apex.md": 1714300000.0})
    save_ingest_state(state, path)
    loaded = load_ingest_state(path)
    assert loaded.last_obs_line == 42
    assert loaded.memory_mtimes["apex.md"] == 1714300000.0


def test_build_observation_text_with_context():
    obs = {"type": "email_loop", "content": "Thread open multiple days",
           "context": "Contract renewal with Apex"}
    text = build_observation_text(obs)
    assert "email_loop" in text
    assert "Thread open multiple days" in text
    assert "Contract renewal with Apex" in text


def test_build_observation_text_without_context():
    obs = {"type": "pipeline_stale", "content": "Apex stale 20 days"}
    text = build_observation_text(obs)
    assert "pipeline_stale" in text
    assert "Apex stale 20 days" in text


def test_prepare_observation_records_skips_already_ingested(obs_file):
    # Start from line 2 — should only get the third observation
    records = prepare_observation_records(obs_file, start_line=2)
    assert len(records) == 1
    assert records[0]["metadata"]["type"] == "email_loop"
    assert records[0]["line_number"] == 2  # 0-indexed


def test_prepare_observation_records_from_start(obs_file):
    records = prepare_observation_records(obs_file, start_line=0)
    assert len(records) == 3


def test_prepare_memory_records_returns_updated_files(memory_dir):
    # No previous mtimes — all files are "new"
    records, new_mtimes = prepare_memory_records(memory_dir, previous_mtimes={})
    assert len(records) == 1
    assert records[0]["id"] == "mem:apex-trial.md"
    assert "Apex has been flagged stale" in records[0]["text"]
    assert "apex-trial.md" in new_mtimes


def test_prepare_memory_records_skips_unchanged(memory_dir):
    # Set mtime to current file's mtime — should skip
    import os
    path = os.path.join(memory_dir, "apex-trial.md")
    current_mtime = os.path.getmtime(path)
    records, new_mtimes = prepare_memory_records(
        memory_dir, previous_mtimes={"apex-trial.md": current_mtime}
    )
    assert len(records) == 0


def test_prepare_memory_records_skips_suppressed(memory_dir):
    # Write a suppressed file
    suppressed = """---
topic: suppressed-topic
suppress: true
---

## Synthesized Memory

Should not be embedded.
"""
    with open(os.path.join(memory_dir, "suppressed.md"), "w") as f:
        f.write(suppressed)
    records, _ = prepare_memory_records(memory_dir, previous_mtimes={})
    topics = [r["metadata"]["topic"] for r in records]
    assert "suppressed-topic" not in topics
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_vector_ingest.py -v
```
Expected: `ModuleNotFoundError: No module named 'processors.vector_ingest'`

- [ ] **Step 3: Implement processors/vector_ingest.py**

```python
"""Vector ingest: embed observations and memory files into Pinecone via Voyage AI."""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

import frontmatter
import voyageai

from pinecone import Pinecone


@dataclass
class IngestState:
    last_obs_line: int = 0
    memory_mtimes: dict = field(default_factory=dict)


def load_ingest_state(path: str) -> IngestState:
    try:
        with open(path) as f:
            data = json.load(f)
        return IngestState(
            last_obs_line=data.get("last_obs_line", 0),
            memory_mtimes=data.get("memory_mtimes", {}),
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return IngestState()


def save_ingest_state(state: IngestState, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(asdict(state), f, indent=2)


def build_observation_text(obs: dict) -> str:
    """Build the text string to embed for a single observation."""
    parts = [f"{obs.get('type', 'unknown')}: {obs.get('content', '')}"]
    if obs.get("context"):
        parts.append(f"Context: {obs['context']}")
    return " | ".join(parts)


def prepare_observation_records(
    obs_file: str, start_line: int = 0
) -> list[dict]:
    """Read observations from start_line onward and return records for embedding."""
    records = []
    try:
        with open(obs_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                except json.JSONDecodeError:
                    continue
                obs_date = obs.get("date", "unknown")
                obs_type = obs.get("type", "unknown")
                entity = obs.get("entity", "unknown")
                vector_id = f"{obs_date}:{obs_type}:{entity}"
                records.append({
                    "id": vector_id,
                    "text": build_observation_text(obs),
                    "metadata": {
                        "date": obs_date,
                        "type": obs_type,
                        "entity": entity,
                        "source": obs.get("source", ""),
                        "content_preview": obs.get("content", "")[:200],
                    },
                    "line_number": i,
                })
    except FileNotFoundError:
        pass
    return records


def prepare_memory_records(
    memory_dir: str, previous_mtimes: dict
) -> tuple[list[dict], dict]:
    """Read memory .md files that changed since last ingest. Returns (records, new_mtimes)."""
    records = []
    new_mtimes = dict(previous_mtimes)

    for path in sorted(Path(memory_dir).glob("*.md")):
        fname = path.name
        current_mtime = path.stat().st_mtime

        # Skip if unchanged
        if previous_mtimes.get(fname) == current_mtime:
            continue

        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue

        # Skip suppressed files
        if post.get("suppress", False):
            new_mtimes[fname] = current_mtime
            continue

        # Extract text to embed
        content = post.content
        if "## Synthesized Memory" in content:
            parts = content.split("## Synthesized Memory")
            human_section = parts[0].strip()
            synthesized = parts[1].strip()
            # Strip the timestamp line
            lines = [l for l in synthesized.splitlines()
                     if not l.strip().startswith("_Last synthesized")]
            synthesized = "\n".join(lines).strip()
            text = f"{human_section}\n\n{synthesized}" if human_section else synthesized
        else:
            text = content.strip()

        if not text:
            new_mtimes[fname] = current_mtime
            continue

        topic = str(post.get("topic", path.stem))
        records.append({
            "id": f"mem:{fname}",
            "text": text,
            "metadata": {
                "topic": topic,
                "last_updated": str(post.get("last_updated", "")),
                "expires": str(post.get("expires", "")),
                "pinned": bool(post.get("pinned", False)),
                "content_preview": text[:200],
            },
        })
        new_mtimes[fname] = current_mtime

    return records, new_mtimes


def _embed_texts(
    voyage_client: voyageai.Client,
    texts: list[str],
    model: str,
    input_type: str = "document",
    batch_size: int = 128,
) -> list[list[float]]:
    """Embed texts via Voyage AI in batches. Returns list of embedding vectors."""
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = voyage_client.embed(batch, model=model, input_type=input_type)
        all_embeddings.extend(result.embeddings)
    return all_embeddings


def _embed_and_upsert(
    voyage_client: voyageai.Client,
    pc_index,
    namespace: str,
    model: str,
    records: list[dict],
    batch_size: int = 50,
) -> int:
    """Embed texts via Voyage AI and upsert vectors to Pinecone. Returns count upserted."""
    if not records:
        return 0

    texts = [r["text"] for r in records]
    embeddings = _embed_texts(voyage_client, texts, model)

    upserted = 0
    for i in range(0, len(records), batch_size):
        batch_records = records[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]

        vectors = []
        for record, embedding in zip(batch_records, batch_embeddings):
            vectors.append({
                "id": record["id"],
                "values": embedding,
                "metadata": record["metadata"],
            })

        pc_index.upsert(vectors=vectors, namespace=namespace)
        upserted += len(vectors)

    return upserted


def ingest(
    obs_file: str,
    memory_dir: str,
    pinecone_api_key: str,
    voyage_api_key: str,
    index_name: str,
    embedding_model: str,
    obs_namespace: str = "observations",
    mem_namespace: str = "memories",
    state_file: str = "data/vector_ingest_state.json",
) -> None:
    """Run the full ingest pipeline: embed new observations + updated memories."""
    state = load_ingest_state(state_file)

    # Prepare records
    obs_records = prepare_observation_records(obs_file, start_line=state.last_obs_line)
    mem_records, new_mtimes = prepare_memory_records(memory_dir, state.memory_mtimes)

    if not obs_records and not mem_records:
        print("   No new data to ingest.")
        return

    # Initialize clients
    pc = Pinecone(api_key=pinecone_api_key)
    pc_index = pc.Index(index_name)
    vo = voyageai.Client(api_key=voyage_api_key)

    # Embed and upsert observations
    if obs_records:
        obs_count = _embed_and_upsert(
            vo, pc_index, obs_namespace, embedding_model, obs_records
        )
        print(f"   Upserted {obs_count} observation vectors.")
        state.last_obs_line = obs_records[-1]["line_number"] + 1

    # Embed and upsert memories
    if mem_records:
        mem_count = _embed_and_upsert(
            vo, pc_index, mem_namespace, embedding_model, mem_records
        )
        print(f"   Upserted {mem_count} memory vectors.")
        state.memory_mtimes = new_mtimes

    save_ingest_state(state, state_file)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_vector_ingest.py -v
```
Expected: All tests PASS.

Note: The tests only cover the preparation and state management functions, not the actual Pinecone API calls. `_embed_and_upsert` and `ingest` are integration-tested in Task 5 with a real (or mocked) Pinecone connection.

- [ ] **Step 5: Commit**

```bash
git add processors/vector_ingest.py tests/test_vector_ingest.py
git commit -m "feat(p14): add vector_ingest processor for Pinecone embedding pipeline"
```

---

## Task 4: Integration test with real Pinecone

**Files:**
- Create: `tests/test_vector_ingest_integration.py`

This test runs against the real Pinecone index. It's skipped in CI if `PINECONE_API_KEY` isn't set.

- [ ] **Step 1: Write integration test**

```python
# tests/test_vector_ingest_integration.py
import json
import os
import time
import tempfile

import pytest

from processors.vector_ingest import ingest, load_ingest_state

pytestmark = pytest.mark.skipif(
    not os.environ.get("PINECONE_API_KEY") or not os.environ.get("VOYAGE_API_KEY"),
    reason="PINECONE_API_KEY and VOYAGE_API_KEY not set — skipping integration test",
)


@pytest.fixture
def test_data(tmp_path):
    # Create a small observations file
    obs_file = str(tmp_path / "observations.jsonl")
    with open(obs_file, "w") as f:
        f.write(json.dumps({
            "date": "2026-04-29", "type": "test_signal",
            "entity": "integration-test", "content": "Integration test observation",
            "source": "test",
        }) + "\n")

    # Create a memory file
    mem_dir = str(tmp_path / "memory")
    os.makedirs(mem_dir)
    with open(os.path.join(mem_dir, "test-memory.md"), "w") as f:
        f.write("""---
topic: integration-test
last_updated: '2026-04-29'
expires: '2026-07-29'
pinned: false
suppress: false
---

## Synthesized Memory

This is a test memory for the integration test.

_Last synthesized: 2026-04-29_
""")

    state_file = str(tmp_path / "ingest_state.json")

    return obs_file, mem_dir, state_file


def test_ingest_round_trip(test_data):
    obs_file, mem_dir, state_file = test_data

    with open("config.json") as f:
        config = json.load(f)

    vector_cfg = config.get("vector", {})

    ingest(
        obs_file=obs_file,
        memory_dir=mem_dir,
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        index_name=vector_cfg.get("index_name", "chief-of-staff"),
        embedding_model=vector_cfg.get("embedding_model", "voyage-3-lite"),
        state_file=state_file,
    )

    # Verify state was updated
    state = load_ingest_state(state_file)
    assert state.last_obs_line == 1
    assert "test-memory.md" in state.memory_mtimes

    # Run again — should be a no-op
    ingest(
        obs_file=obs_file,
        memory_dir=mem_dir,
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        index_name=vector_cfg.get("index_name", "chief-of-staff"),
        embedding_model=vector_cfg.get("embedding_model", "voyage-3-lite"),
        state_file=state_file,
    )
    # State unchanged
    state2 = load_ingest_state(state_file)
    assert state2.last_obs_line == 1
```

- [ ] **Step 2: Run locally (requires PINECONE_API_KEY in .env)**

```bash
pytest tests/test_vector_ingest_integration.py -v -s
```
Expected: Test passes. Vectors appear in Pinecone dashboard under `chief-of-staff` index.

- [ ] **Step 3: Verify in Pinecone dashboard**

Check both namespaces (`observations` and `memories`) have vectors. The vector count should match what the test ingested.

- [ ] **Step 4: Clean up test vectors (optional)**

The test vectors have IDs starting with `2026-04-29:test_signal:integration-test` and `mem:test-memory.md`. They can be left in place (they'll be overwritten on real runs) or manually deleted from the dashboard.

- [ ] **Step 5: Commit**

```bash
git add tests/test_vector_ingest_integration.py
git commit -m "test(p14): add Pinecone integration test for vector ingest"
```

---

## Task 5: Wire ingest into main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add import**

Add after the existing memory imports:
```python
from processors.vector_ingest import ingest as vector_ingest
```

- [ ] **Step 2: Add vector ingest call after memory synthesis**

In `_run_inner()`, inside the `if memory_cfg.get("enabled"):` block, after the `synthesize(...)` call and its "Memory synthesis complete" print, add:

```python
            # Vector ingest — embed new observations and updated memories into Pinecone
            vector_cfg = config.get("vector", {})
            pinecone_key = os.environ.get("PINECONE_API_KEY", "")
            voyage_key = os.environ.get("VOYAGE_API_KEY", "")
            if vector_cfg.get("enabled") and pinecone_key and voyage_key:
                try:
                    print("📡  Ingesting vectors into Pinecone...")
                    vector_ingest(
                        obs_file=memory_cfg["observations_file"],
                        memory_dir=memory_cfg["dir"],
                        pinecone_api_key=pinecone_key,
                        voyage_api_key=voyage_key,
                        index_name=vector_cfg["index_name"],
                        embedding_model=vector_cfg["embedding_model"],
                        obs_namespace=vector_cfg.get("observations_namespace", "observations"),
                        mem_namespace=vector_cfg.get("memories_namespace", "memories"),
                        state_file=vector_cfg.get("ingest_state_file", "data/vector_ingest_state.json"),
                    )
                    print("✅  Vector ingest complete.")
                except Exception as e:
                    print(f"⚠️  Vector ingest error (non-fatal): {e}", file=sys.stderr)
```

The `try/except` makes vector ingest non-fatal — same pattern as the memory pipeline. If Pinecone is down, the brief still generates and sends. The vector index just doesn't get updated that day.

- [ ] **Step 3: Add PINECONE_API_KEY to brief.yml GitHub Actions workflow**

In `.github/workflows/brief.yml`, add to the `env` section:
```yaml
PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
VOYAGE_API_KEY: ${{ secrets.VOYAGE_API_KEY }}
```

- [ ] **Step 4: Add data/vector_ingest_state.json to tracked state**

Make sure `data/vector_ingest_state.json` is not in `.gitignore`. It should be committed back to the repo on each run, same as `data/state/` files.

Check `.gitignore`:
```bash
grep vector_ingest .gitignore
```
If it's listed, remove it. If it's not listed, you're good.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All existing tests still pass. The new import doesn't break anything because `vector_ingest` is only called when `vector.enabled` is true and `PINECONE_API_KEY` is set.

- [ ] **Step 6: Dry run locally**

```bash
python main.py --no-email
```
Expected: After "Memory synthesis complete", you see "Ingesting vectors into Pinecone..." and "Vector ingest complete." Check the Pinecone dashboard — vector counts should increase.

- [ ] **Step 7: Commit**

```bash
git add main.py .github/workflows/brief.yml
git commit -m "feat(p14): wire vector ingest into main run loop (non-fatal)"
```

---

## Task 6: Backfill existing observations

**Files:**
- Create: `scripts/backfill_vectors.py`

The daily ingest only processes new observations. This script does a one-time backfill of the entire `observations.jsonl` history so the vector store starts with full context.

- [ ] **Step 1: Implement scripts/backfill_vectors.py**

```python
#!/usr/bin/env python3
"""One-time backfill: embed all existing observations and memory files into Pinecone."""

import json
import os
import sys

from dotenv import load_dotenv
load_dotenv()

import voyageai
from pinecone import Pinecone

from processors.vector_ingest import (
    prepare_observation_records,
    prepare_memory_records,
    _embed_and_upsert,
    save_ingest_state,
    IngestState,
)


def main():
    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
    if not pinecone_key or not voyage_key:
        print("ERROR: PINECONE_API_KEY and VOYAGE_API_KEY must be set.", file=sys.stderr)
        sys.exit(1)

    with open("config.json") as f:
        config = json.load(f)

    vector_cfg = config.get("vector", {})
    memory_cfg = config.get("memory", {})

    index_name = vector_cfg.get("index_name", "chief-of-staff")
    model = vector_cfg.get("embedding_model", "voyage-3-lite")
    obs_ns = vector_cfg.get("observations_namespace", "observations")
    mem_ns = vector_cfg.get("memories_namespace", "memories")
    state_file = vector_cfg.get("ingest_state_file", "data/vector_ingest_state.json")

    obs_file = memory_cfg.get("observations_file", "data/memory/observations.jsonl")
    memory_dir = memory_cfg.get("dir", "data/memory")

    pc = Pinecone(api_key=pinecone_key)
    pc_index = pc.Index(index_name)
    vo = voyageai.Client(api_key=voyage_key)

    # Backfill all observations from line 0
    print("Loading all observations...")
    obs_records = prepare_observation_records(obs_file, start_line=0)
    print(f"  {len(obs_records)} observation records to embed.")

    if obs_records:
        print("Embedding and upserting observations...")
        count = _embed_and_upsert(vo, pc_index, obs_ns, model, obs_records)
        print(f"  Upserted {count} observation vectors.")

    # Backfill all memory files
    print("Loading all memory files...")
    mem_records, new_mtimes = prepare_memory_records(memory_dir, previous_mtimes={})
    print(f"  {len(mem_records)} memory records to embed.")

    if mem_records:
        print("Embedding and upserting memories...")
        count = _embed_and_upsert(vo, pc_index, mem_ns, model, mem_records)
        print(f"  Upserted {count} memory vectors.")

    # Save state so daily ingest picks up from where backfill left off
    state = IngestState(
        last_obs_line=obs_records[-1]["line_number"] + 1 if obs_records else 0,
        memory_mtimes=new_mtimes,
    )
    save_ingest_state(state, state_file)
    print(f"  State saved: next ingest starts at line {state.last_obs_line}.")
    print("Backfill complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the backfill**

```bash
python scripts/backfill_vectors.py
```
Expected: All existing observations and memory files are embedded. State file is written.

- [ ] **Step 3: Verify in Pinecone dashboard**

Check vector counts in both namespaces. The `observations` namespace should have hundreds of vectors (matching the ~10 days of data in `observations.jsonl`). The `memories` namespace should have ~15 vectors (one per `.md` file).

- [ ] **Step 4: Commit state file**

```bash
git add scripts/backfill_vectors.py data/vector_ingest_state.json
git commit -m "feat(p14): add backfill script and run initial vector population"
```

---

## Task 7: Update CLAUDE.md and BACKLOG.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `BACKLOG.md`

- [ ] **Step 1: Add vector layer section to CLAUDE.md**

Add after the "## Data Persistence" section:

```markdown
## Vector Memory (Pinecone + Voyage AI)

Observations and synthesized memory files are embedded into a Pinecone serverless index (`chief-of-staff`) after each run. Two namespaces: `observations` (raw signals, one vector per JSONL line) and `memories` (synthesized `.md` files, one vector per file). Embeddings generated via Voyage AI (`voyage-3-lite`, 512 dims).

Ingest is non-fatal — if Pinecone or Voyage is unreachable, the system continues with file-based memory. Ingest state tracked in `data/vector_ingest_state.json` (committed to repo).

Phase 1 (current): ingest only. Phase 2: semantic retrieval replaces recency-based memory retriever. Phase 3: semantic Telegram queries.

GitHub Secrets required: `PINECONE_API_KEY`, `VOYAGE_API_KEY`
```

- [ ] **Step 2: Add P14 entry to BACKLOG.md**

Add after the P13 section:

```markdown
## ✅ P14 — Vector Memory Layer — Phase 1 (complete)

**Shipped YYYY-MM-DD.** Pinecone serverless index (`chief-of-staff`) with two namespaces: `observations` and `memories`. `processors/vector_ingest.py` embeds new observations and updated memory files after each daily run using Voyage AI (voyage-3-lite, 512 dims). Non-fatal — Pinecone errors don't block the brief. Backfill script in `scripts/backfill_vectors.py` populated the index with all historical data. State tracked in `data/vector_ingest_state.json`.

**Next:** Phase 2 — replace `memory_retriever.py` with semantic search against Pinecone.
```

Update the date when shipping.

- [ ] **Step 3: Update the status summary at the bottom of BACKLOG.md**

Add to the open items list:
```
5. P14 Phase 2 — Semantic retrieval (replaces recency-based memory retriever)
6. P14 Phase 3 — Semantic Telegram queries
7. P14 Phase 4 — Proactive pattern detection
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md BACKLOG.md
git commit -m "docs(p14): update CLAUDE.md and BACKLOG.md with vector memory layer"
```

---

## Self-review

**What Phase 1 delivers:**
- Every observation and synthesized memory is embedded and stored in Pinecone
- Daily ingest is incremental (only new/changed data)
- The vector store accumulates context over time, ready for Phase 2 retrieval
- Existing system is completely unchanged — no retrieval paths modified
- Non-fatal: Pinecone outage doesn't affect the morning brief

**What Phase 1 does not deliver:**
- No semantic retrieval yet — the brief still uses recency-based `.md` file loading
- No Telegram query improvements yet
- No pattern detection or clustering

**Known considerations for Phase 2:**
- `memory_retriever.py` will need a `query_pinecone()` function that builds a query from today's signals and returns ranked results
- The function signature `retrieve_memories(memory_dir, token_budget)` should gain an optional `pinecone_config` parameter, with fallback to file-based retrieval if None
- Cold start latency on the first query of the day (200-800ms) is acceptable
- `top_k` and the query construction strategy need tuning once Phase 1 data accumulates

**Dependency on embedding model availability:**
- Uses `voyage-3-lite` (512 dims) via the Voyage AI API, matching the OS assistant project. Pinecone index must be created with `dimension=512`. If you later switch to `voyage-3` or `voyage-3-large` (both 1024 dims), the index must be recreated with the new dimension — Pinecone doesn't allow changing dimension on an existing index.
