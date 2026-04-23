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
    _apply_abandonment_decay,
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


def test_apply_abandonment_decay_shortens_expired_ttl(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    memory_file = memory_dir / "stale-topic.md"
    post = fm.Post(
        "## Synthesized Memory\n\nSome old content",
        topic="stale-topic",
        created=old_date,
        last_updated=old_date,
        expires=far_expires,
        activity_last_seen=old_date,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    expected_expires = (date.today() + timedelta(days=14)).isoformat()
    assert str(updated["expires"]) == expected_expires


def test_apply_abandonment_decay_skips_pinned(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    memory_file = memory_dir / "pinned-topic.md"
    post = fm.Post(
        "## Synthesized Memory\n\nPinned content",
        topic="pinned-topic",
        created=old_date,
        last_updated=old_date,
        expires=far_expires,
        activity_last_seen=old_date,
        pinned=True,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    assert str(updated["expires"]) == far_expires


def test_apply_abandonment_decay_skips_recent_file(memory_dir):
    import frontmatter as fm
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    memory_file = memory_dir / "active-topic.md"
    post = fm.Post(
        "## Synthesized Memory\n\nRecent content",
        topic="active-topic",
        created=recent_date,
        last_updated=recent_date,
        expires=far_expires,
        activity_last_seen=recent_date,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    assert str(updated["expires"]) == far_expires


def test_apply_abandonment_decay_skips_already_short_ttl(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    soon_expires = (date.today() + timedelta(days=5)).isoformat()
    memory_file = memory_dir / "nearly-dead.md"
    post = fm.Post(
        "## Synthesized Memory\n\nAlmost gone",
        topic="nearly-dead",
        created=old_date,
        last_updated=old_date,
        expires=soon_expires,
        activity_last_seen=old_date,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    assert str(updated["expires"]) == soon_expires


def test_apply_abandonment_decay_applies_ttl_when_expires_missing(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    memory_file = memory_dir / "no-expires.md"
    post = fm.Post(
        "## Synthesized Memory\n\nNo expiry set",
        topic="no-expires",
        created=old_date,
        last_updated=old_date,
        activity_last_seen=old_date,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    expected_expires = (date.today() + timedelta(days=14)).isoformat()
    assert str(updated["expires"]) == expected_expires


def test_apply_abandonment_decay_skips_missing_activity_last_seen(memory_dir):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    memory_file = memory_dir / "no-activity.md"
    post = fm.Post(
        "## Synthesized Memory\n\nNo activity date",
        topic="no-activity",
        created=old_date,
        last_updated=old_date,
        expires=far_expires,
        pinned=False,
        suppress=False,
    )
    with open(memory_file, "wb") as f:
        fm.dump(post, f)

    _apply_abandonment_decay(str(memory_dir), abandon_threshold_days=60, abandon_ttl_days=14)

    updated = fm.load(str(memory_file))
    assert str(updated["expires"]) == far_expires
