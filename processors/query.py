import sys
import json
import os
import anthropic

from processors.memory_retriever import retrieve_memories


def _load_local_context(config: dict) -> str:
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
        memory_context = retrieve_memories(
            memory_dir=memory_cfg["dir"],
            token_budget=memory_cfg.get("retrieval_token_budget", 550),
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

    try:
        with open(config["issues_file"]) as f:
            issues = json.load(f)
        if issues:
            parts.append("## Open Issues\n" + json.dumps(issues, indent=2))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    captures_file = config.get("captures_file", "data/captures.md")
    if os.path.exists(captures_file):
        try:
            with open(captures_file) as f:
                content = f.read()
            parts.append("## Recent Captures\n" + (content[-2000:] if len(content) > 2000 else content))
        except OSError:
            pass

    return "\n\n".join(parts)


_SYSTEM_PROMPT = """You are JARVIS, Trent's AI Chief of Staff. You handle things quietly and competently — no fuss, no performance.

Your tone is dry, precise, and occasionally wry. You use "sir" naturally but not robotically. You don't volunteer enthusiasm and you don't pad responses. If something is worth noting that wasn't asked, you note it once and move on. If the question has a better framing, you'll offer it. You're warm underneath the formality, but competence is how you show it — not warmth-signaling.

You have tools to look up live data and to write to the system's files. Use them when the query requires it. When you take a write action, confirm briefly what you did. For config changes, state explicitly what you changed and what it was before. Answer in plain text, 500 characters or fewer unless the query needs more detail.

Context:
{local_context}"""


def answer_query_with_tools(api_key: str, model: str, query: str, config: dict) -> str:
    from processors.query_tools import TOOL_SCHEMAS, execute_tool
    from lib.llm_logger import log_usage

    client = anthropic.Anthropic(api_key=api_key)
    local_context = _load_local_context(config)
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
                    result = execute_tool(block.name, block.input, config)
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
