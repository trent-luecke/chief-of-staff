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
    with open(obs_file, "w") as f:
        for i in range(4):
            d = (date.today() - timedelta(days=i)).isoformat()
            f.write(f'{{"date": "{d}", "type": "top_priority", "entity": "x", "content": "x"}}\n')
    msg = get_cold_start_message(obs_file, cold_start_days=3)
    assert msg is None


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


def test_build_query_string_handles_non_string_items_gracefully():
    signals = {
        "calendar_events": ["Real event", None, 42],
        "email_subjects": [],
        "pipeline_lead_names": [],
        "issue_titles": [],
    }
    result = build_query_string(signals)
    assert result == "Real event"


import sys
from unittest.mock import patch, MagicMock


# --- helpers for semantic tests ---

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
