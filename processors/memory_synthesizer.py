import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import anthropic
import frontmatter


def _load_recent_observations(obs_file: str, lookback_days: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback_days)
    observations = []
    try:
        with open(obs_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                    obs_date = date.fromisoformat(obs.get("date", "2000-01-01"))
                    if obs_date >= cutoff:
                        observations.append(obs)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return observations


def _is_expired(expires: str, pinned: bool = False) -> bool:
    if pinned:
        return False
    try:
        return date.fromisoformat(expires) < date.today()
    except (ValueError, TypeError):
        return False


def _archive_expired_files(memory_dir: str, archive_dir: str) -> None:
    for path in Path(memory_dir).glob("*.md"):
        try:
            post = frontmatter.load(str(path))
            if _is_expired(str(post.get("expires", "")), pinned=bool(post.get("pinned", False))):
                shutil.move(str(path), str(Path(archive_dir) / path.name))
        except Exception:
            continue


def _load_existing_human_section(memory_file: Path) -> str:
    if not memory_file.exists():
        return ""
    try:
        post = frontmatter.load(str(memory_file))
        content = post.content
        if "## Synthesized Memory" in content:
            return content.split("## Synthesized Memory")[0].strip()
        return content.strip()
    except Exception:
        return ""


def _build_synthesis_prompt(observations: list[dict]) -> str:
    grouped: dict[str, list[dict]] = {}
    for obs in observations:
        entity = obs.get("entity", "general")
        grouped.setdefault(entity, []).append(obs)

    lines = ["Observations grouped by entity (last 30 days):\n"]
    for entity, obs_list in grouped.items():
        lines.append(f"### {entity}")
        for obs in obs_list:
            lines.append(f"  [{obs['date']}] [{obs['type']}] {obs['content']}")
            if obs.get("context"):
                lines.append(f"    context: {obs['context']}")
        lines.append("")

    lines.append("""
Analyze these observations and return a JSON array. Each element represents one memory file to create/update:

[
  {
    "topic": "short-slug",
    "filename": "short-slug.md",
    "synthesized_memory": "Markdown content for ## Synthesized Memory section. Use **Pattern:**, **Decision:**, **Watch:** headers. Be concise.",
    "decision_candidates": ["candidate text if inferred from context, else empty list"]
  }
]

Rules:
- Group related entities into one file (e.g., multiple apex observations → apex.md)
- Only create files for entities with meaningful patterns (2+ observations or a clear decision)
- Keep synthesized_memory under 200 words
- decision_candidates: only include if you can infer a clear decision from the context field of email/slack observations
- Respond ONLY with the JSON array, no other text
""")
    return "\n".join(lines)


def synthesize(
    obs_file: str,
    memory_dir: str,
    archive_dir: str,
    api_key: str,
    model: str,
    lookback_days: int = 30,
    default_ttl_days: int = 90,
    activity_extension_days: int = 30,
) -> None:
    observations = _load_recent_observations(obs_file, lookback_days)
    if not observations:
        return

    _archive_expired_files(memory_dir, archive_dir)

    prompt = _build_synthesis_prompt(observations)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    try:
        memories = json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            memories = json.loads(match.group(0))
        else:
            return

    today = date.today().isoformat()
    expires = (date.today() + timedelta(days=default_ttl_days)).isoformat()

    for memory in memories:
        filename = memory.get("filename", "")
        if not filename or not filename.endswith(".md"):
            continue

        memory_path = Path(memory_dir) / filename
        human_section = _load_existing_human_section(memory_path)

        synthesized = memory.get("synthesized_memory", "")
        decision_candidates = memory.get("decision_candidates", [])
        if decision_candidates:
            synthesized += "\n\n**Decision Candidates (unconfirmed):**\n"
            for dc in decision_candidates:
                synthesized += f"• {dc}\n"

        content_parts = []
        if human_section:
            content_parts.append(f"<!-- Human-written — never modified by synthesis -->\n{human_section}")
        content_parts.append(f"## Synthesized Memory\n\n{synthesized}\n\n_Last synthesized: {today}_")
        content = "\n\n".join(content_parts)

        created = today
        file_expires = expires
        if memory_path.exists():
            try:
                existing = frontmatter.load(str(memory_path))
                created = str(existing.get("created", today))
                existing_expires = str(existing.get("expires", ""))
                try:
                    ext_date = date.fromisoformat(existing_expires) + timedelta(days=activity_extension_days)
                    file_expires = max(
                        date.fromisoformat(expires),
                        ext_date,
                    ).isoformat()
                except ValueError:
                    pass
            except Exception:
                pass

        post = frontmatter.Post(
            content,
            topic=memory.get("topic", filename.replace(".md", "")),
            created=created,
            last_updated=today,
            expires=file_expires,
            activity_last_seen=today,
            pinned=False,
            suppress=False,
        )
        with open(memory_path, "wb") as f:
            frontmatter.dump(post, f)
