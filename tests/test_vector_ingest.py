# tests/test_vector_ingest.py
import json
import os
import tempfile

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
