# tests/test_wanderer.py
import json
import math
import os
import sys
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
