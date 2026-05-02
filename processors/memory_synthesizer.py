import json
import re
from datetime import date, timedelta

import anthropic
import frontmatter

from lib.llm_logger import log_usage

_OBS_KEY = "memory/observations.jsonl"


def _load_recent_observations(storage, lookback_days: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback_days)
    observations = []
    content = storage.read(_OBS_KEY) or ""
    for line in content.splitlines():
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
    return observations


def _is_expired(expires: str, pinned: bool = False) -> bool:
    if pinned:
        return False
    try:
        return date.fromisoformat(expires) < date.today()
    except (ValueError, TypeError):
        return False


def _archive_expired_files(storage) -> None:
    for key in storage.list_keys("memory"):
        if not key.endswith(".md") or key.startswith("memory/archive/"):
            continue
        content = storage.read(key)
        if content is None:
            continue
        try:
            post = frontmatter.loads(content)
            if _is_expired(str(post.get("expires", "")), pinned=bool(post.get("pinned", False))):
                name = key.split("/")[-1]
                storage.write(f"memory/archive/{name}", content)
                storage.delete(key)
        except Exception:
            continue


def _apply_abandonment_decay(storage, abandon_threshold_days: int, abandon_ttl_days: int) -> None:
    cutoff = date.today() - timedelta(days=abandon_threshold_days)
    new_expires = (date.today() + timedelta(days=abandon_ttl_days)).isoformat()
    for key in storage.list_keys("memory"):
        if not key.endswith(".md") or key.startswith("memory/archive/"):
            continue
        content = storage.read(key)
        if content is None:
            continue
        try:
            post = frontmatter.loads(content)
            if post.get("pinned"):
                continue
            last_updated = post.get("activity_last_seen", "")
            if not last_updated:
                continue
            try:
                updated_date = date.fromisoformat(str(last_updated)[:10])
            except ValueError:
                continue
            if updated_date < cutoff:
                current_expires = str(post.get("expires", ""))
                try:
                    current_exp_date = date.fromisoformat(current_expires)
                except ValueError:
                    current_exp_date = None
                candidate = date.today() + timedelta(days=abandon_ttl_days)
                if current_exp_date is None or candidate < current_exp_date:
                    post["expires"] = new_expires
                    storage.write(key, frontmatter.dumps(post))
        except Exception:
            continue


def _load_existing_human_section(storage, key: str) -> str:
    content = storage.read(key)
    if content is None:
        return ""
    try:
        post = frontmatter.loads(content)
        text = post.content
        if "## Synthesized Memory" in text:
            return text.split("## Synthesized Memory")[0].strip()
        return text.strip()
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
    storage,
    api_key: str,
    model: str,
    lookback_days: int = 30,
    default_ttl_days: int = 90,
    activity_extension_days: int = 30,
    abandon_threshold_days: int = 60,
    abandon_ttl_days: int = 14,
) -> None:
    observations = _load_recent_observations(storage, lookback_days)
    if not observations:
        return

    _apply_abandonment_decay(storage, abandon_threshold_days, abandon_ttl_days)
    _archive_expired_files(storage)

    prompt = _build_synthesis_prompt(observations)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    log_usage("memory_synthesizer", response.usage, model)

    raw = response.content[0].text.strip()
    try:
        memories = json.loads(raw)
    except json.JSONDecodeError:
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

        slug = filename.replace(".md", "")
        key = f"memory/{filename}"
        human_section = _load_existing_human_section(storage, key)

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
        existing_pinned = False
        existing_suppress = False
        existing_content = storage.read(key)
        if existing_content is not None:
            try:
                existing = frontmatter.loads(existing_content)
                created = str(existing.get("created", today))
                existing_pinned = bool(existing.get("pinned", False))
                existing_suppress = bool(existing.get("suppress", False))
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
            topic=memory.get("topic", slug),
            created=created,
            last_updated=today,
            expires=file_expires,
            activity_last_seen=today,
            pinned=existing_pinned,
            suppress=existing_suppress,
        )
        storage.write(f"memory/{slug}.md", frontmatter.dumps(post))
