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


# Normalized dummy vector for metadata-only filter queries (cosine-safe with voyage-3-lite 512 dims)
_DUMMY_VECTOR = [1.0 / math.sqrt(512)] * 512


def _format_matches(matches: list) -> str:
    """Format Pinecone query results as a readable string for Claude."""
    if not matches:
        return "No results found."
    parts = []
    for m in matches:
        meta = m.metadata or {}
        score = getattr(m, "score", None)
        score_str = f" (score: {score:.3f})" if score is not None else ""
        preview = meta.get("content_preview", "")
        meta_str = json.dumps({k: v for k, v in meta.items() if k != "content_preview"}, default=str)
        parts.append(f"ID: {m.id}{score_str}\nMetadata: {meta_str}\nPreview: {preview}")
    return "\n\n".join(parts)


def execute_query_semantic(
    voyage_client,
    pc_index,
    query: str,
    namespace: str,
    top_k: int = 10,
    embedding_model: str = "voyage-3-lite",
) -> str:
    """Embed query via Voyage and search Pinecone. Returns formatted result string."""
    result = voyage_client.embed([query], model=embedding_model, input_type="query")
    query_vector = result.embeddings[0]
    response = pc_index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=True,
    )
    return _format_matches(response.matches)


def execute_filter_records(
    pc_index,
    namespace: str,
    filters: dict,
    top_k: int = 20,
) -> str:
    """Metadata filter query against Pinecone. Uses dummy vector (scores are irrelevant)."""
    response = pc_index.query(
        vector=_DUMMY_VECTOR,
        top_k=top_k,
        namespace=namespace,
        filter=filters,
        include_metadata=True,
    )
    return _format_matches(response.matches)


_NAMESPACE_SCHEMA = """
**observations** — daily signals written by the morning brief system.
  Metadata fields: type (pipeline_staleness | email_loop | top_priorities | kpi_snapshot), date (YYYY-MM-DD), entity, content_preview.
  kpi_snapshot entries have structured context in content_preview: sales_revenue, demos, open_bugs, cancellations_mtd.

**memories** — synthesized cross-day context files on ongoing topics.
  Metadata fields: topic, last_updated, expires, pinned, content_preview.

**raw_data** — individual operational records. Distinguish by ID prefix:
  lead:{id}   → pipeline leads.    Metadata: name, status, priority, days_since_contact, stale (bool), source, email.
  bug:{id}    → bug tickets.       Metadata: title, status, priority_level, technical_areas (list), date_created, days_open, shortcut_url.
  cancel:{id} → cancellations.     Metadata: date, account_name, reason, base_plan, monetary_value, customer_returned.
  sale:{id}   → sales entries.     Metadata: date, customer, total, sale_type, salesperson.

filter_records filter syntax (Pinecone):
  Exact match:       {"field": {"$eq": "value"}}
  Set membership:    {"field": {"$in": ["a", "b"]}}
  Boolean:           {"field": {"$eq": true}}
  Numeric gt/lt:     {"field": {"$gt": 7}}
  Combine (AND):     {"field1": {"$eq": "x"}, "field2": {"$gt": 3}}
"""


def build_system_prompt(today: str, wanderer_memories: list[dict], namespace_schema: str = "") -> str:
    schema = namespace_schema or _NAMESPACE_SCHEMA

    if wanderer_memories:
        mem_lines = []
        for m in wanderer_memories:
            mem_lines.append(
                f"**{m['topic']}** (found: {m['last_updated']})\n{m['content']}"
            )
        memories_section = "\n\n".join(mem_lines)
        memories_instruction = (
            "These are your recent findings. Revisit them only if there is meaningfully new data "
            "since you last looked. Otherwise, explore elsewhere."
        )
    else:
        memories_section = "No previous findings — explore freely."
        memories_instruction = ""

    return f"""You are the Wanderer — an autonomous analyst running nightly over TeamBuildr OS's operational data.
TeamBuildr OS is a B2B SaaS platform for strength and conditioning coaches. The VP of Sales is Trent Luecke.

Today is {today}.

You have access to a Pinecone vector DB with three namespaces:
{schema}

**Your recent findings** (previous nights):
{memories_section}
{memories_instruction}

**Your task:** Explore the data autonomously. Look for patterns, anomalies, or connections worth surfacing — things that might not be obvious from a single day's brief. You decide what to investigate and in what order.

**Constraints:**
- Aim to conclude within ~15 queries. Hard limit: 20.
- When done exploring, respond with ONLY a valid JSON object (no preamble, no trailing text):

```json
{{
  "telegram": "🔍 Wanderer — {today}\\n\\n[your finding, ≤1500 characters]",
  "memory": {{
    "topic": "short-topic-slug",
    "content": "Cross-day finding worth carrying into future briefs...",
    "expires": "YYYY-MM-DD"
  }}
}}
```

Include "memory" only if the finding has cross-day significance worth surfacing in future morning briefs.
Omit "memory" for ephemeral or day-specific observations.
If you include "memory", set "expires" to 14 days from today ({(date.fromisoformat(today) + timedelta(days=14)).isoformat()}) unless you have reason to choose differently.
Keep the telegram message under 1500 characters — be editorial, surface the single most interesting thing."""
