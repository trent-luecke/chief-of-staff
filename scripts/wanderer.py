#!/usr/bin/env python3
"""Nightly autonomous vector wanderer."""

import json
import math
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import frontmatter

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def load_wanderer_memories(memory_dir: str, limit: int = 5) -> list[dict]:
    """Return up to `limit` wanderer-tagged memory files sorted by last_updated desc."""
    results = []
    try:
        paths = sorted(Path(memory_dir).glob("*.md"))
    except (FileNotFoundError, OSError):
        return []

    for path in paths:
        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue
        if post.get("source") != "wanderer":
            continue
        results.append({
            "topic": str(post.get("topic", path.stem)),
            "last_updated": str(post.get("last_updated", "")),
            "content": post.content.strip(),
        })

    results.sort(key=lambda x: x["last_updated"], reverse=True)
    return results[:limit]


# Stubs — will be replaced in later tasks
def parse_final_response(text: str) -> dict:
    """Extract JSON from Claude's final response. Falls back to raw text as telegram."""
    # Try ```json ... ``` fence first
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding outermost { ... } in the text
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: treat entire response as the telegram message
    return {"telegram": text}


def _topic_slug(topic: str) -> str:
    """Convert topic to slug: lowercase, replace non-alphanumeric with hyphens, trim, limit 50 chars."""
    return re.sub(r"[^a-z0-9]+", "-", topic.lower().strip()).strip("-")[:50]


def write_wanderer_memory(memory_dir: str, memory: dict, today: str) -> str:
    """Write a wanderer memory .md file. Returns the file path written."""
    topic = memory.get("topic", "finding")
    content = memory.get("content", "").strip()
    expires = memory.get(
        "expires",
        (date.fromisoformat(today) + timedelta(days=14)).isoformat(),
    )

    slug = _topic_slug(topic)
    display_topic = topic.replace("-", " ").title()
    filename = f"wanderer_{slug}_{today}.md"
    path = os.path.join(memory_dir, filename)

    text = (
        f"---\n"
        f"topic: {display_topic}\n"
        f"source: wanderer\n"
        f"last_updated: {today}\n"
        f"expires: {expires}\n"
        f"pinned: false\n"
        f"suppress: false\n"
        f"---\n\n"
        f"{content}\n"
    )

    os.makedirs(memory_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    return path


def _format_matches(matches: list) -> str: ...  # noqa: E704
def build_system_prompt(today: str, wanderer_memories: list, namespace_schema: str = "") -> str: ...  # noqa: E704
