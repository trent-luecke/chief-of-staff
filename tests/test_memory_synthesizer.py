import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from processors.memory_synthesizer import (
    synthesize,
    _load_recent_observations,
    _is_expired,
    _archive_expired_files,
)


def write_obs(obs_file, observations):
    with open(obs_file, "w") as f:
        for obs in observations:
            f.write(json.dumps(obs) + "\n")


@pytest.fixture
def memory_dir(tmp_path):
    (tmp_path / "archive").mkdir()
    return tmp_path


@pytest.fixture
def obs_file(memory_dir):
    return str(memory_dir / "observations.jsonl")


def test_load_recent_observations_returns_within_lookback(obs_file):
    today = date.today().isoformat()
    old_date = (date.today() - timedelta(days=40)).isoformat()
    write_obs(obs_file, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
        {"date": old_date, "type": "top_priority", "entity": "apex", "content": "Old entry"},
    ])
    result = _load_recent_observations(obs_file, lookback_days=30)
    assert len(result) == 1
    assert result[0]["content"] == "Follow up Apex"


def test_is_expired_returns_true_for_past_date():
    assert _is_expired("2026-01-01") is True


def test_is_expired_returns_false_for_future_date():
    future = (date.today() + timedelta(days=30)).isoformat()
    assert _is_expired(future) is False


def test_is_expired_returns_false_when_pinned():
    assert _is_expired("2026-01-01", pinned=True) is False


def test_archive_expired_files_moves_file(memory_dir):
    expired_file = memory_dir / "old-topic.md"
    expired_file.write_text("""---
topic: old-topic
expires: 2026-01-01
pinned: false
---
Old memory
""")
    archive_dir = str(memory_dir / "archive")
    _archive_expired_files(str(memory_dir), archive_dir)
    assert not expired_file.exists()
    assert (memory_dir / "archive" / "old-topic.md").exists()


def test_synthesize_creates_memory_file(obs_file, memory_dir):
    today = date.today().isoformat()
    write_obs(obs_file, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex contract"},
        {"date": today, "type": "pipeline_stale", "entity": "apex", "content": "Apex stale 20 days"},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([{
        "topic": "apex",
        "filename": "apex.md",
        "synthesized_memory": "**Pattern:** Apex appearing repeatedly. **Watch:** Stale 20 days.",
        "decision_candidates": [],
    }]))]

    with patch("processors.memory_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        synthesize(
            obs_file=obs_file,
            memory_dir=str(memory_dir),
            archive_dir=str(memory_dir / "archive"),
            api_key="test-key",
            model="claude-sonnet-4-6",
            lookback_days=30,
            default_ttl_days=90,
            activity_extension_days=30,
        )

    memory_file = memory_dir / "apex.md"
    assert memory_file.exists()
    content = memory_file.read_text()
    assert "## Synthesized Memory" in content
    assert "Apex appearing repeatedly" in content
