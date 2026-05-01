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
