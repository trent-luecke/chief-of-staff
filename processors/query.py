import sys
import json
import os
import anthropic

from processors.memory_retriever import retrieve_memories
from processors.issues import get_open_issues
from lib.captures import load_recent_captures


def _load_local_context(config: dict, storage, query: str = "") -> str:
    parts = []

    try:
        with open(config["pipeline"]["cache_path"]) as f:
            cache = json.load(f)
        leads = cache.get("leads", [])
        if leads:
            parts.append("## Pipeline\n" + json.dumps(leads[:20], indent=2))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    people_dir = config.get("people_dir", "data/people")
    if os.path.isdir(people_dir):
        people_parts = []
        for fname in sorted(os.listdir(people_dir))[:30]:
            if fname.endswith(".md"):
                try:
                    with open(os.path.join(people_dir, fname)) as f:
                        people_parts.append(f.read()[:600])
                except OSError:
                    pass
        if people_parts:
            parts.append("## People\n" + "\n---\n".join(people_parts))

    memory_cfg = config.get("memory", {})
    if memory_cfg.get("enabled"):
        vector_cfg = config.get("vector", {})
        pinecone_key = os.environ.get("PINECONE_API_KEY", "")
        voyage_key = os.environ.get("VOYAGE_API_KEY", "")
        _pinecone_cfg = None
        if vector_cfg.get("enabled") and pinecone_key and voyage_key:
            _pinecone_cfg = {
                "api_key": pinecone_key,
                "voyage_api_key": voyage_key,
                "index_name": vector_cfg["index_name"],
                "embedding_model": vector_cfg["embedding_model"],
                "observations_namespace": vector_cfg.get("observations_namespace", "observations"),
                "memories_namespace": vector_cfg.get("memories_namespace", "memories"),
                "retrieval_mode": vector_cfg.get("retrieval_mode", "auto"),
            }
        memory_context = retrieve_memories(
            storage,
            token_budget=memory_cfg.get("retrieval_token_budget", 550),
            pinecone_config=_pinecone_cfg,
            query_signals={"raw_query": query},
        )
        if memory_context:
            parts.append(f"## Memory\n{memory_context}")

    projects_file = config.get("projects_file", "data/projects.md")
    if os.path.exists(projects_file):
        try:
            with open(projects_file) as f:
                parts.append("## Projects\n" + f.read())
        except OSError:
            pass

    if storage is not None:
        from dataclasses import asdict as _asdict
        issues = get_open_issues(storage)
        if issues:
            parts.append("## Open Issues\n" + json.dumps([_asdict(i) for i in issues], indent=2))

    if storage is not None:
        from lib.tasks import get_open_tasks
        open_tasks = get_open_tasks(storage)
        if open_tasks:
            task_lines = []
            for t in open_tasks:
                due = f" (due {t['due_date']})" if t.get("due_date") else ""
                task_lines.append(f"- [{t['id']}] {t['title']}{due}")
            parts.append("## Open Tasks\n" + "\n".join(task_lines))

    if storage is not None:
        captures = load_recent_captures(storage)
        if captures:
            parts.append("## Recent Captures\n" + captures)

    tz_name = config.get("timezone", "America/Chicago")
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        now_local = _dt.now(ZoneInfo(tz_name))
        parts.append(
            f"Current time: {now_local.strftime('%A %Y-%m-%d %H:%M %Z')} ({tz_name})"
        )
    except Exception:
        pass

    return "\n\n".join(parts)


_SYSTEM_PROMPT = """You are JARVIS, Trent's AI Chief of Staff. You handle things quietly and competently — no fuss, no performance.

Your tone is dry, precise, and occasionally wry. You use "sir" naturally but not robotically. You don't volunteer enthusiasm and you don't pad responses. If something is worth noting that wasn't asked, you note it once and move on. If the question has a better framing, you'll offer it. You're warm underneath the formality, but competence is how you show it — not warmth-signaling.

You have tools to look up live data and to write to the system's files. Use them when the query requires it. When you take one or more write actions, respond with an explicit receipt block:

Done. Here's what I wrote:
  → [destination]: [content paraphrase]
  → [destination]: [content paraphrase]

This will [downstream effect].

Destinations: file path for people notes (e.g. people/jake-torres.md), 'captures', 'Notion queue', 'projects', 'config'. Downstream effects: 'surface in tomorrow's brief', 'queryable from this bot', 'applied to Notion by Cowork on its next scheduled run'. Read-only tools (search_gmail, get_calendar_events, get_person_profile, get_pipeline_lead) need no receipt. Answer in plain text, 500 characters or fewer unless the query needs more detail.

When setting a reminder, compute the target fire time using the current time shown in Context. Check if the minute falls on a 15-minute boundary (:00, :15, :30, :45). If it does, call set_reminder with the correct UTC ISO 8601 fire_at (seconds must be :00). If it does not, do NOT call the tool — reply asking the user which of the two surrounding marks they prefer (e.g. "That lands at 10:20. Should I set it for 10:15 or 10:30, sir?"). Only offer boundaries that are in the future: if the lower mark has already passed, offer only the upper one. The user's next reply triggers a new run where you call set_reminder with the confirmed time.

Context:
{local_context}"""


def answer_query_with_tools(api_key: str, model: str, query: str, config: dict, storage=None) -> str:
    from processors.query_tools import TOOL_SCHEMAS, execute_tool
    from lib.llm_logger import log_usage

    client = anthropic.Anthropic(api_key=api_key)
    local_context = _load_local_context(config, storage, query=query)
    system = _SYSTEM_PROMPT.format(local_context=local_context)
    messages = [{"role": "user", "content": query}]

    for _ in range(10):
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        log_usage("query_tool_loop", response.usage, model)

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "No response generated."

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, config, storage=storage)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    print("WARNING: query tool loop hit max iterations (10)", file=sys.stderr)
    for block in response.content:
        if hasattr(block, "text") and isinstance(block.text, str):
            return block.text
    return "Hit maximum tool iterations — something went wrong."
