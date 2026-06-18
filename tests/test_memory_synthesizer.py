import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lib.storage import LocalStorage
from processors.memory_synthesizer import (
    synthesize,
    _load_recent_observations,
    _is_expired,
    _archive_expired_files,
    _apply_abandonment_decay,
)


def write_obs(storage, observations):
    content = "\n".join(json.dumps(obs) for obs in observations) + "\n"
    storage.write("memory/observations.jsonl", content)


@pytest.fixture
def storage(tmp_path):
    (tmp_path / "memory" / "archive").mkdir(parents=True)
    return LocalStorage(base_dir=str(tmp_path))


def test_load_recent_observations_returns_within_lookback(storage):
    today = date.today().isoformat()
    old_date = (date.today() - timedelta(days=40)).isoformat()
    write_obs(storage, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
        {"date": old_date, "type": "top_priority", "entity": "apex", "content": "Old entry"},
    ])
    result = _load_recent_observations(storage, lookback_days=30)
    assert len(result) == 1
    assert result[0]["content"] == "Follow up Apex"


def test_is_expired_returns_true_for_past_date():
    assert _is_expired("2026-01-01") is True


def test_is_expired_returns_false_for_future_date():
    future = (date.today() + timedelta(days=30)).isoformat()
    assert _is_expired(future) is False


def test_is_expired_returns_false_when_pinned():
    assert _is_expired("2026-01-01", pinned=True) is False


def test_archive_expired_files_moves_file(storage, tmp_path):
    import frontmatter as fm
    expired_content = """---
topic: old-topic
expires: 2026-01-01
pinned: false
---
Old memory
"""
    storage.write("memory/old-topic.md", expired_content)
    _archive_expired_files(storage)
    assert storage.read("memory/old-topic.md") is None
    assert storage.read("memory/archive/old-topic.md") is not None


def test_synthesize_creates_memory_file(storage):
    today = date.today().isoformat()
    write_obs(storage, [
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
    mock_response.usage = MagicMock()

    with patch("processors.memory_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        with patch("processors.memory_synthesizer.log_usage", return_value=None):
            synthesize(
                storage=storage,
                api_key="test-key",
                model="claude-sonnet-4-6",
                lookback_days=30,
                default_ttl_days=90,
                activity_extension_days=30,
            )

    content = storage.read("memory/apex.md")
    assert content is not None
    assert "## Synthesized Memory" in content
    assert "Apex appearing repeatedly" in content


def test_apply_abandonment_decay_shortens_expired_ttl(storage):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
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
    storage.write("memory/stale-topic.md", fm.dumps(post))

    _apply_abandonment_decay(storage, abandon_threshold_days=60, abandon_ttl_days=14)

    updated_content = storage.read("memory/stale-topic.md")
    updated = fm.loads(updated_content)
    expected_expires = (date.today() + timedelta(days=14)).isoformat()
    assert str(updated["expires"]) == expected_expires


def test_apply_abandonment_decay_skips_pinned(storage):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
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
    storage.write("memory/pinned-topic.md", fm.dumps(post))

    _apply_abandonment_decay(storage, abandon_threshold_days=60, abandon_ttl_days=14)

    updated_content = storage.read("memory/pinned-topic.md")
    updated = fm.loads(updated_content)
    assert str(updated["expires"]) == far_expires


def test_apply_abandonment_decay_skips_recent_file(storage):
    import frontmatter as fm
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
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
    storage.write("memory/active-topic.md", fm.dumps(post))

    _apply_abandonment_decay(storage, abandon_threshold_days=60, abandon_ttl_days=14)

    updated_content = storage.read("memory/active-topic.md")
    updated = fm.loads(updated_content)
    assert str(updated["expires"]) == far_expires


def test_apply_abandonment_decay_skips_already_short_ttl(storage):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    soon_expires = (date.today() + timedelta(days=5)).isoformat()
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
    storage.write("memory/nearly-dead.md", fm.dumps(post))

    _apply_abandonment_decay(storage, abandon_threshold_days=60, abandon_ttl_days=14)

    updated_content = storage.read("memory/nearly-dead.md")
    updated = fm.loads(updated_content)
    assert str(updated["expires"]) == soon_expires


def test_apply_abandonment_decay_applies_ttl_when_expires_missing(storage):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    post = fm.Post(
        "## Synthesized Memory\n\nNo expiry set",
        topic="no-expires",
        created=old_date,
        last_updated=old_date,
        activity_last_seen=old_date,
        pinned=False,
        suppress=False,
    )
    storage.write("memory/no-expires.md", fm.dumps(post))

    _apply_abandonment_decay(storage, abandon_threshold_days=60, abandon_ttl_days=14)

    updated_content = storage.read("memory/no-expires.md")
    updated = fm.loads(updated_content)
    expected_expires = (date.today() + timedelta(days=14)).isoformat()
    assert str(updated["expires"]) == expected_expires


def test_synthesize_preserves_pinned_flag(storage):
    import frontmatter as fm
    today = date.today().isoformat()

    post = fm.Post(
        "## Synthesized Memory\n\nExisting content",
        topic="apex",
        created=today,
        last_updated=today,
        expires=(date.today() + timedelta(days=90)).isoformat(),
        activity_last_seen=today,
        pinned=True,
        suppress=False,
    )
    storage.write("memory/apex.md", fm.dumps(post))

    write_obs(storage, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([{
        "topic": "apex",
        "filename": "apex.md",
        "synthesized_memory": "**Pattern:** Apex updated.",
        "decision_candidates": [],
    }]))]
    mock_response.usage = MagicMock()

    with patch("processors.memory_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        with patch("processors.memory_synthesizer.log_usage", return_value=None):
            synthesize(
                storage=storage,
                api_key="test-key",
                model="claude-sonnet-4-6",
            )

    updated_content = storage.read("memory/apex.md")
    updated = fm.loads(updated_content)
    assert updated["pinned"] is True


def _run_synthesize_with_response(storage, text, stop_reason="end_turn"):
    today = date.today().isoformat()
    write_obs(storage, [
        {"date": today, "type": "top_priority", "entity": "apex", "content": "Follow up Apex"},
    ])
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock_response.stop_reason = stop_reason
    mock_response.usage = MagicMock()
    with patch("processors.memory_synthesizer.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        with patch("processors.memory_synthesizer.log_usage", return_value=None):
            synthesize(storage=storage, api_key="test-key", model="claude-sonnet-4-6")


def test_synthesize_truncated_response_raises_clear_error(storage):
    """A response cut off at max_tokens leaves a malformed array whose only
    surviving ']' is an inner decision_candidates bracket. Today's failure.
    The synthesizer must raise an actionable error, not a cryptic JSONDecodeError."""
    truncated = (
        '[\n  {\n    "topic": "apex",\n    "filename": "apex.md",\n'
        '    "synthesized_memory": "stuff",\n'
        '    "decision_candidates": ["renew the contract"]\n  }\n'
        '  {\n    "topic": "beta",\n    "filename": "beta.md",\n'
        '    "synthesized_memory": "more stuff that got cut off mid'
    )
    with pytest.raises(ValueError) as exc:
        _run_synthesize_with_response(storage, truncated, stop_reason="max_tokens")
    assert "max_tokens" in str(exc.value)
    # No file should have been written from the unparseable response
    assert storage.read("memory/apex.md") is None


def test_synthesize_strips_code_fences(storage):
    fenced = "```json\n" + json.dumps([{
        "topic": "apex",
        "filename": "apex.md",
        "synthesized_memory": "**Pattern:** fenced output parsed fine.",
        "decision_candidates": [],
    }]) + "\n```"
    _run_synthesize_with_response(storage, fenced)
    content = storage.read("memory/apex.md")
    assert content is not None
    assert "fenced output parsed fine" in content


def test_apply_abandonment_decay_skips_missing_activity_last_seen(storage):
    import frontmatter as fm
    old_date = (date.today() - timedelta(days=70)).isoformat()
    far_expires = (date.today() + timedelta(days=80)).isoformat()
    post = fm.Post(
        "## Synthesized Memory\n\nNo activity date",
        topic="no-activity",
        created=old_date,
        last_updated=old_date,
        expires=far_expires,
        pinned=False,
        suppress=False,
    )
    storage.write("memory/no-activity.md", fm.dumps(post))

    _apply_abandonment_decay(storage, abandon_threshold_days=60, abandon_ttl_days=14)

    updated_content = storage.read("memory/no-activity.md")
    updated = fm.loads(updated_content)
    assert str(updated["expires"]) == far_expires
