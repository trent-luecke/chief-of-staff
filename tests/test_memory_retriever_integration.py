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


def test_semantic_retrieval_auto_mode_does_not_crash(tmp_path):
    """With an empty local memory dir and real Pinecone, result is a string — no crash."""
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
