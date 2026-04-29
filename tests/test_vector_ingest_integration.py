# tests/test_vector_ingest_integration.py
import json
import os
from pathlib import Path

import pytest
from pinecone import Pinecone

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
    obs_file = str(tmp_path / "observations.jsonl")
    with open(obs_file, "w") as f:
        f.write(json.dumps({
            "date": "2026-04-29", "type": "test_signal",
            "entity": "integration-test", "content": "Integration test observation",
            "source": "test",
        }) + "\n")

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

    with open(_CONFIG_PATH) as f:
        config = json.load(f)

    vector_cfg = config.get("vector", {})
    index_name = vector_cfg.get("index_name", "chief-of-staff")

    ingest(
        obs_file=obs_file,
        memory_dir=mem_dir,
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        index_name=index_name,
        embedding_model=vector_cfg.get("embedding_model", "voyage-3-lite"),
        obs_namespace=_TEST_OBS_NS,
        mem_namespace=_TEST_MEM_NS,
        state_file=state_file,
    )

    # Verify local state was updated
    state = load_ingest_state(state_file)
    assert state.last_obs_line == 1
    assert isinstance(state.memory_mtimes.get("test-memory.md"), float)
    assert state.memory_mtimes["test-memory.md"] > 0

    # Verify vectors actually landed in Pinecone
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    idx = pc.Index(index_name)
    obs_result = idx.fetch(ids=[_TEST_OBS_ID], namespace=_TEST_OBS_NS)
    assert _TEST_OBS_ID in obs_result.vectors
    mem_result = idx.fetch(ids=[_TEST_MEM_ID], namespace=_TEST_MEM_NS)
    assert _TEST_MEM_ID in mem_result.vectors

    # Second run — should be a no-op
    ingest(
        obs_file=obs_file,
        memory_dir=mem_dir,
        pinecone_api_key=os.environ["PINECONE_API_KEY"],
        voyage_api_key=os.environ["VOYAGE_API_KEY"],
        index_name=index_name,
        embedding_model=vector_cfg.get("embedding_model", "voyage-3-lite"),
        obs_namespace=_TEST_OBS_NS,
        mem_namespace=_TEST_MEM_NS,
        state_file=state_file,
    )
    state2 = load_ingest_state(state_file)
    assert state2.last_obs_line == 1
    assert state2.memory_mtimes == state.memory_mtimes
