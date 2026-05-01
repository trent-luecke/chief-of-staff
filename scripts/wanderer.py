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

TOOLS = [
    {
        "name": "query_semantic",
        "description": (
            "Embed a natural language query and search a Pinecone namespace for semantically similar records. "
            "Use this to find patterns, trends, or specific record types by describing what you're looking for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query string."},
                "namespace": {
                    "type": "string",
                    "enum": ["observations", "memories", "raw_data"],
                    "description": "Pinecone namespace to search.",
                },
                "top_k": {"type": "integer", "description": "Number of results (default: 10).", "default": 10},
            },
            "required": ["query", "namespace"],
        },
    },
    {
        "name": "filter_records",
        "description": (
            "Query a Pinecone namespace using metadata filters without embedding. "
            "Use for structured lookups: all High-priority bugs, cancellations by reason, stale leads, etc. "
            'Filter syntax: {"field": {"$eq": "value"}}, {"field": {"$in": ["a","b"]}}, {"field": {"$gt": 7}}, {"field": {"$eq": true}}.'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "enum": ["observations", "memories", "raw_data"],
                    "description": "Pinecone namespace to filter.",
                },
                "filters": {"type": "object", "description": "Pinecone metadata filter dict."},
                "top_k": {"type": "integer", "description": "Max results (default: 20).", "default": 20},
            },
            "required": ["namespace", "filters"],
        },
    },
]


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


def run_tool_loop(
    anthropic_client,
    system_prompt: str,
    tools: list,
    tool_executor,
    model: str = "claude-sonnet-4-6",
    max_tool_calls: int = 20,
) -> str:
    """Run Claude tool-use loop. Returns Claude's final text response."""
    messages = []
    tool_call_count = 0

    while True:
        response = anthropic_client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        assistant_content = list(response.content)
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason != "tool_use":
            for block in assistant_content:
                if getattr(block, "type", None) == "text":
                    return block.text
            return ""

        # Execute tool calls; track count
        tool_results = []
        hit_limit = False

        for block in assistant_content:
            if getattr(block, "type", None) != "tool_use":
                continue

            tool_call_count += 1
            if hit_limit or tool_call_count > max_tool_calls:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Query limit reached.",
                })
                hit_limit = True
                continue

            try:
                result = tool_executor(block.name, block.input)
            except Exception as exc:
                result = f"Error executing {block.name}: {exc}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

            if tool_call_count >= max_tool_calls:
                hit_limit = True

        if hit_limit:
            tool_results.append({
                "type": "text",
                "text": "You've reached your query limit. Write your final JSON response now — no more tool calls.",
            })

        messages.append({"role": "user", "content": tool_results})

        if hit_limit:
            final = anthropic_client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            )
            for block in final.content:
                if getattr(block, "type", None) == "text":
                    return block.text
            return ""


def make_tool_executor(voyage_client, pc_index, embedding_model: str = "voyage-3-lite"):
    """Return a callable that dispatches tool calls to the appropriate executor."""
    def executor(tool_name: str, tool_input: dict) -> str:
        if tool_name == "query_semantic":
            return execute_query_semantic(
                voyage_client,
                pc_index,
                query=tool_input["query"],
                namespace=tool_input["namespace"],
                top_k=tool_input.get("top_k", 10),
                embedding_model=embedding_model,
            )
        elif tool_name == "filter_records":
            return execute_filter_records(
                pc_index,
                namespace=tool_input["namespace"],
                filters=tool_input["filters"],
                top_k=tool_input.get("top_k", 20),
            )
        else:
            return f"Unknown tool: {tool_name}"
    return executor


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")

    import anthropic
    import voyageai
    from pinecone import Pinecone
    from lib.telegram import send_message

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "")

    for name, val in [
        ("ANTHROPIC_API_KEY", anthropic_key),
        ("PINECONE_API_KEY", pinecone_key),
        ("VOYAGE_API_KEY", voyage_key),
        ("TELEGRAM_BOT_TOKEN", telegram_token),
        ("TELEGRAM_CHAT_ID", telegram_chat),
    ]:
        if not val:
            print(f"ERROR: {name} not set — wanderer cannot run.", file=sys.stderr)
            return

    memory_dir = str(_ROOT / "data" / "memory")
    today = date.today().isoformat()
    embedding_model = "voyage-3-lite"
    index_name = "chief-of-staff"

    # Load recent wanderer memories for context seeding
    wanderer_memories = load_wanderer_memories(memory_dir)
    print(f"   Loaded {len(wanderer_memories)} recent wanderer memories.")

    # Initialize clients
    vo = voyageai.Client(api_key=voyage_key)
    pc = Pinecone(api_key=pinecone_key)
    pc_index = pc.Index(index_name)
    ac = anthropic.Anthropic(api_key=anthropic_key)

    # Build system prompt and tool executor
    system_prompt = build_system_prompt(today, wanderer_memories)
    tool_executor = make_tool_executor(vo, pc_index, embedding_model)

    # Run the loop
    print("   Starting wanderer tool-use loop...")
    raw_response = run_tool_loop(
        ac, system_prompt, TOOLS, tool_executor,
        model="claude-sonnet-4-6",
        max_tool_calls=20,
    )

    # Parse response
    parsed = parse_final_response(raw_response)
    telegram_text = parsed.get("telegram", "").strip()
    memory_data = parsed.get("memory")

    # Send Telegram
    if telegram_text:
        try:
            send_message(telegram_token, telegram_chat, telegram_text)
            print("   Telegram message sent.")
        except Exception as exc:
            print(f"WARNING: Telegram send failed: {exc}", file=sys.stderr)
    else:
        print("WARNING: No telegram text in response.", file=sys.stderr)

    # Write memory if present
    if memory_data and isinstance(memory_data, dict) and memory_data.get("content"):
        try:
            path = write_wanderer_memory(memory_dir, memory_data, today)
            print(f"   Memory written: {path}")
        except Exception as exc:
            print(f"WARNING: Memory write failed: {exc}", file=sys.stderr)
    else:
        print("   No memory to write.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: Wanderer failed: {exc}", file=sys.stderr)
        sys.exit(0)  # Non-fatal — don't fail the GitHub Actions job
