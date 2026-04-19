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
