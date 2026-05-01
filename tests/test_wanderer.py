# tests/test_wanderer.py
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import frontmatter

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
    assert post["last_updated"] == date(2026, 5, 1)
    assert post["expires"] == date(2026, 5, 15)
    assert post.content.strip() == "Many bugs in mobile."


def test_write_wanderer_memory_default_expires(tmp_path):
    memory = {"topic": "some-finding", "content": "content"}
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    post = frontmatter.load(path)
    assert post["expires"] == date(2026, 5, 15)  # 14 days from 2026-05-01


def test_write_wanderer_memory_topic_display_name(tmp_path):
    memory = {"topic": "stale-pipeline-leads", "content": "content", "expires": "2026-05-15"}
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    post = frontmatter.load(path)
    assert post["topic"] == "Stale Pipeline Leads"


def test_write_wanderer_memory_slug_sanitized(tmp_path):
    memory = {"topic": "Bug Clusters: Mobile & Payments", "content": "c", "expires": "2026-05-15"}
    path = write_wanderer_memory(str(tmp_path), memory, "2026-05-01")
    assert "wanderer_bug-clusters-mobile-payments_2026-05-01" in path


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
