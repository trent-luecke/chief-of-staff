# tests/test_vector_ingest_integration.py
import json
import os
from pathlib import Path

import pytest
from pinecone import Pinecone

from lib.storage import LocalStorage
from processors.vector_ingest import ingest, load_ingest_state

pytestmark = pytest.mark.skipif(
    not os.environ.get("PINECONE_API_KEY") or not os.environ.get("VOYAGE_API_KEY"),
    reason="PINECONE_API_KEY or VOYAGE_API_KEY not set — skipping integration test",
)

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_TEST_OBS_NS = "test-observations"
_TEST_MEM_NS = "test-memories"
_TEST_OBS_ID = "2026-04-29:test_signal:integration-test:0"
_TEST_MEM_ID = "mem:test-memory.md"


@pytest.fixture(autouse=True)
def cleanup_test_vectors():
    """Delete test vectors from Pinecone before and after each test."""
    with open(_CONFIG_PATH) as f:
        cfg = json.load(f)
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    idx = pc.Index(cfg["vector"]["index_name"])

    def _delete():
        try:
            idx.delete(ids=[_TEST_OBS_ID], namespace=_TEST_OBS_NS)
            idx.delete(ids=[_TEST_MEM_ID], namespace=_TEST_MEM_NS)
        except Exception:
            pass  # vectors may not exist yet

    _delete()
    yield
    _delete()


@pytest.fixture
def test_data(tmp_path):
    storage = LocalStorage(base_dir=str(tmp_path))

    obs_content = json.dumps({
        "date": "2026-04-29", "type": "test_signal",
        "entity": "integration-test", "content": "Integration test observation",
        "source": "test",
    }) + "\n"
    storage.write("memory/observations.jsonl", obs_content)

    mem_content = """---
topic: integration-test
last_updated: '2026-04-29'
expires: '2026-07-29'
pinned: false
suppress: false
---

## Synthesized Memory

This is a test memory for the integration test.

_Last synthesized: 2026-04-29_
"""
    storage.write("memory/test-memory.md", mem_content)

    return storage


def test_ingest_round_trip(test_data):
    storage = test_data

    with open(_CONFIG_PATH) as f:
        config = json.load(f)

    vector_cfg = config.get("vector", {})
    index_name = vector_cfg.get("index_name", "chief-of-staff")

    ingest(
        storage=storage,
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        index_name=index_name,
        embedding_model=vector_cfg.get("embedding_model", "voyage-3-lite"),
        obs_namespace=_TEST_OBS_NS,
        mem_namespace=_TEST_MEM_NS,
    )

    # Verify local state was updated
    state = load_ingest_state(storage)
    assert state.last_obs_line == 1
    # memory_mtimes now uses storage keys (e.g. "memory/test-memory.md") and content hashes
    mem_key = "memory/test-memory.md"
    assert mem_key in state.memory_mtimes
    assert isinstance(state.memory_mtimes[mem_key], str)  # content hash (hex string)

    # Verify vectors actually landed in Pinecone
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    idx = pc.Index(index_name)
    obs_result = idx.fetch(ids=[_TEST_OBS_ID], namespace=_TEST_OBS_NS)
    assert _TEST_OBS_ID in obs_result.vectors
    mem_result = idx.fetch(ids=[_TEST_MEM_ID], namespace=_TEST_MEM_NS)
    assert _TEST_MEM_ID in mem_result.vectors

    # Second run — should be a no-op
    ingest(
        storage=storage,
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        index_name=index_name,
        embedding_model=vector_cfg.get("embedding_model", "voyage-3-lite"),
        obs_namespace=_TEST_OBS_NS,
        mem_namespace=_TEST_MEM_NS,
    )
    state2 = load_ingest_state(storage)
    assert state2.last_obs_line == 1
    assert state2.memory_mtimes == state.memory_mtimes
