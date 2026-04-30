import json
from datetime import date
from pathlib import Path
from typing import Optional

import frontmatter


def build_query_string(query_signals: dict) -> str:
    """Build a Voyage AI query string from today's collected signals."""
    parts = []
    parts.extend(query_signals.get("calendar_events", []))
    parts.extend(query_signals.get("email_subjects", [])[:10])
    parts.extend(query_signals.get("pipeline_lead_names", []))
    parts.extend(query_signals.get("issue_titles", []))

    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        if not isinstance(p, str) or not p.strip():
            continue
        key = p.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(p.strip())

    return " | ".join(unique)


def _count_distinct_days(obs_file: str) -> int:
    days = set()
    try:
        with open(obs_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    days.add(obs.get("date", ""))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return len(days)


def get_cold_start_message(obs_file: str, cold_start_days: int = 3) -> Optional[str]:
    distinct_days = _count_distinct_days(obs_file)
    if distinct_days >= cold_start_days:
        return None
    day_num = distinct_days + 1
    if day_num == 1:
        return f"Memory building — context improves with each run (day 1 of {cold_start_days})"
    return f"Memory building — patterns will emerge after a few more runs (day {day_num} of {cold_start_days})"


def retrieve_memories(memory_dir: str, token_budget: int = 550) -> str:
    today = date.today()
    pinned_sections = []
    regular_sections = []

    for path in sorted(Path(memory_dir).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue

        if post.get("suppress", False):
            continue

        expires_str = str(post.get("expires", ""))
        pinned = bool(post.get("pinned", False))
        try:
            if not pinned and date.fromisoformat(expires_str) < today:
                continue
        except ValueError:
            pass

        topic = post.get("topic", path.stem)
        last_updated = post.get("last_updated", "")

        content = post.content
        if "## Synthesized Memory" in content:
            synthesized = content.split("## Synthesized Memory")[1].strip()
            lines = [l for l in synthesized.splitlines() if not l.startswith("_Last synthesized")]
            synthesized = "\n".join(lines).strip()
        else:
            synthesized = content.strip()

        section = f"**{topic}** (updated: {last_updated})\n{synthesized}"

        if pinned:
            pinned_sections.append(section)
        else:
            regular_sections.append(section)

    if not pinned_sections and not regular_sections:
        return ""

    char_budget = token_budget * 4
    output_parts = ["## Cross-Day Memory\n"]

    for section in pinned_sections:
        output_parts.append(section)

    remaining = char_budget - sum(len(p) for p in output_parts)
    for section in regular_sections:
        if len(section) > remaining:
            break
        output_parts.append(section)
        remaining -= len(section)

    return "\n\n".join(output_parts)
