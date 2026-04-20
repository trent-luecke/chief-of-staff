from dataclasses import dataclass
from typing import Optional
import json
import os
import re
import anthropic

from processors.memory_retriever import retrieve_memories


@dataclass
class Capture:
    type: str
    target: Optional[str]
    content: str


@dataclass
class QueryResult:
    answer: str
    captures: list[Capture]


def _load_local_context(config: dict) -> str:
    parts = []

    # Pipeline cache
    try:
        with open(config["pipeline"]["cache_path"]) as f:
            cache = json.load(f)
        leads = cache.get("leads", [])
        if leads:
            parts.append("## Pipeline\n" + json.dumps(leads[:20], indent=2))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # People store
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

    # Memory (reuse existing retriever)
    memory_cfg = config.get("memory", {})
    if memory_cfg.get("enabled"):
        memory_context = retrieve_memories(
            memory_dir=memory_cfg["dir"],
            token_budget=memory_cfg.get("retrieval_token_budget", 1500),
        )
        if memory_context:
            parts.append(f"## Memory\n{memory_context}")

    # Projects
    projects_file = config.get("projects_file", "data/projects.md")
    if os.path.exists(projects_file):
        try:
            with open(projects_file) as f:
                parts.append("## Projects\n" + f.read())
        except OSError:
            pass

    # Open issues
    try:
        with open(config["issues_file"]) as f:
            issues = json.load(f)
        if issues:
            parts.append("## Open Issues\n" + json.dumps(issues, indent=2))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Recent captures (last ~2000 chars)
    captures_file = config.get("captures_file", "data/captures.md")
    if os.path.exists(captures_file):
        try:
            with open(captures_file) as f:
                content = f.read()
            parts.append("## Recent Captures\n" + (content[-2000:] if len(content) > 2000 else content))
        except OSError:
            pass

    return "\n\n".join(parts)


def _classify_intent(client: anthropic.Anthropic, model: str, query: str) -> dict:
    system = """You are a query router for a chief-of-staff AI system.
Given a natural language query, decide whether live Gmail or Calendar data is needed.
Respond with JSON only, no other text.

Available local data (always loaded, no API call needed):
- Pipeline cache (leads, trial status, stale opps)
- People store (contact files with activity history)
- Memory (synthesized patterns and decisions from past briefs)
- Open issues
- Recent action captures

Live data (extra ~15s — fetch only when local data is insufficient):
- Gmail: arbitrary thread search (from:, to:, subject:, date ranges)
- Calendar: dates beyond tomorrow

Return exactly this JSON schema:
{
  "needs_live_gmail": boolean,
  "needs_live_calendar": boolean,
  "gmail_search_query": "gmail search string or null",
  "calendar_date_range": "description like 'next 7 days' or null"
}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": f"Query: {query}"}],
        )
        from lib.llm_logger import log_usage
        log_usage("query_classify", message.usage, model)
        raw = message.content[0].text.strip()
        m = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
        return json.loads(m.group(1).strip() if m else raw)
    except Exception:
        return {"needs_live_gmail": False, "needs_live_calendar": False,
                "gmail_search_query": None, "calendar_date_range": None}


def _fetch_live_gmail(config: dict, gmail_query: str) -> str:
    from collectors.gmail import fetch_threads_needing_attention
    try:
        threads = fetch_threads_needing_attention(
            user_email=config["email"],
            max_results=10,
            query=gmail_query,
        )
    except Exception:
        return ""
    if not threads:
        return ""
    lines = [f"- [{t.last_sender}] {t.subject} — {t.snippet[:120]}" for t in threads]
    return "## Live Gmail Results\n" + "\n".join(lines)


def _fetch_live_calendar(config: dict, date_range: str) -> str:
    from collectors.calendar import fetch_today_events
    from datetime import date, timedelta

    days = 7
    if date_range:
        for n in ["14", "7", "3"]:
            if n in date_range:
                days = int(n)
                break

    events_text = []
    for i in range(1, days + 1):
        target = date.today() + timedelta(days=i)
        for cal_id in config.get("calendar_ids", ["primary"]):
            try:
                events = fetch_today_events(cal_id, target_date=target, user_email=config["email"])
                for e in events:
                    events_text.append(f"- {target.isoformat()} {e.start.strftime('%H:%M')} {e.summary}")
            except Exception:
                pass

    if not events_text:
        return ""
    return "## Live Calendar Results\n" + "\n".join(events_text)


def answer_query(api_key: str, model: str, query: str, config: dict) -> QueryResult:
    local_context = _load_local_context(config)
    client = anthropic.Anthropic(api_key=api_key)

    intent = _classify_intent(client, model, query)

    context_parts = [local_context]
    if intent.get("needs_live_gmail") and intent.get("gmail_search_query"):
        live_gmail = _fetch_live_gmail(config, intent["gmail_search_query"])
        if live_gmail:
            context_parts.append(live_gmail)
    if intent.get("needs_live_calendar") and intent.get("calendar_date_range"):
        live_cal = _fetch_live_calendar(config, intent["calendar_date_range"])
        if live_cal:
            context_parts.append(live_cal)

    full_context = "\n\n".join(context_parts)

    system = f"""You are JARVIS, Trent's AI Chief of Staff. You handle things quietly and competently — no fuss, no performance.

Your tone is dry, precise, and occasionally wry. You use "sir" naturally but not robotically. You don't volunteer enthusiasm and you don't pad responses. If something is worth noting that wasn't asked, you note it once and move on. If the question has a better framing, you'll offer it. You're warm underneath the formality, but competence is how you show it — not warmth-signaling.

Answer concisely and directly.
If the query requests an action or capture, include it in the captures list.
Capture types: todo (action item), idea (thought to explore), note (info to remember), flag (priority signal), complete (mark a capture or project next-action as done — content should be the exact or close text of the item to remove).
Respond with JSON only, no other text.

Schema:
{{
  "answer": "concise reply for Telegram, plain text, 500 chars max",
  "captures": [
    {{"type": "todo|idea|note|flag", "target": "person/company name or null", "content": "what to capture"}}
  ]
}}

Context:
{full_context}"""

    try:
        message = client.messages.create(
            model=model,
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": query}],
        )
        from lib.llm_logger import log_usage
        log_usage("query_answer", message.usage, model)
        raw = message.content[0].text.strip()
        m = re.search(r"```(?:json)?\n?(.*?)```", raw, re.DOTALL)
        data = json.loads(m.group(1).strip() if m else raw)
        captures = [
            Capture(type=c.get("type", "note"), target=c.get("target"), content=c.get("content", ""))
            for c in data.get("captures", [])
        ]
        return QueryResult(answer=data.get("answer", "No answer generated."), captures=captures)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return QueryResult(answer="Sorry, I couldn't parse a response. Try rephrasing.", captures=[])
