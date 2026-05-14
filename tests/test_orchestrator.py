"""Tests for bot-as-orchestrator capabilities."""

import os


def _config(tmp_dir: str) -> dict:
    return {
        "data_dir": tmp_dir,
        "captures_file": os.path.join(tmp_dir, "captures.md"),
        "projects_file": os.path.join(tmp_dir, "projects.md"),
        "people_dir": os.path.join(tmp_dir, "people"),
        "issues_file": os.path.join(tmp_dir, "issues.json"),
        "pipeline": {"cache_path": os.path.join(tmp_dir, "pipeline_cache.json")},
        "email": "trent@teambuildr.com",
        "notion_queue_path": os.path.join(tmp_dir, "notion_updates_queue.json"),
        "brief_prefs_path": os.path.join(tmp_dir, "brief_prefs.md"),
    }


def test_system_prompt_requires_receipt():
    from processors.query import _SYSTEM_PROMPT
    prompt_lower = _SYSTEM_PROMPT.lower()
    assert "receipt" in prompt_lower or "here's what i wrote" in prompt_lower or "here's what" in prompt_lower
