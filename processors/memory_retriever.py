import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import frontmatter


def build_query_string(query_signals: dict) -> str:
    """Build a Voyage AI query string from today's collected signals."""
    raw = query_signals.get("raw_query", "")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

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


def _load_memory_section(memory_dir: str, match_id: str) -> Optional[str]:
    """Load and format a memory .md file by its Pinecone vector ID, or None if skipped."""
    if not match_id.startswith("mem:"):
        return None
    filename = match_id[4:]
    path = os.path.join(memory_dir, filename)
    try:
        post = frontmatter.load(path)
    except Exception:
        return None

    if post.get("suppress", False):
        return None

    today = date.today()
    expires_str = str(post.get("expires", ""))
    pinned = bool(post.get("pinned", False))
    try:
        if not pinned and expires_str and date.fromisoformat(expires_str) < today:
            return None
    except ValueError:
        pass

    topic = str(post.get("topic", Path(path).stem))
    last_updated = str(post.get("last_updated", ""))

    content = post.content
    if "## Synthesized Memory" in content:
        synthesized = content.split("## Synthesized Memory")[1].strip()
        lines = [ln for ln in synthesized.splitlines() if not ln.startswith("_Last synthesized")]
        synthesized = "\n".join(lines).strip()
    else:
        synthesized = content.strip()

    if not synthesized:
        return None

    return f"**{topic}** (updated: {last_updated})\n{synthesized}"


def query_pinecone(
    pinecone_config: dict,
    query_string: str,
    top_k_memories: int = 20,
    top_k_observations: int = 20,
) -> tuple[list, list]:
    """Embed query_string via Voyage AI and query both Pinecone namespaces.

    Returns (memory_matches, observation_matches).
    """
    import voyageai
    from pinecone import Pinecone
    vo = voyageai.Client(api_key=pinecone_config["voyage_api_key"])
    result = vo.embed([query_string], model=pinecone_config["embedding_model"], input_type="query")
    query_vector = result.embeddings[0]

    pc = Pinecone(api_key=pinecone_config["api_key"])
    index = pc.Index(pinecone_config["index_name"])

    mem_response = index.query(
        vector=query_vector,
        top_k=top_k_memories,
        namespace=pinecone_config.get("memories_namespace", "memories"),
        include_metadata=True,
    )
    obs_response = index.query(
        vector=query_vector,
        top_k=top_k_observations,
        namespace=pinecone_config.get("observations_namespace", "observations"),
        include_metadata=True,
    )
    return mem_response.matches, obs_response.matches


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


def _retrieve_memories_file_based(memory_dir: str, token_budget: int = 550) -> str:
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


def _maybe_log_retrieval(
    log_file: Optional[str],
    run_date: str,
    trigger: str,
    query_text: str,
    retrieval_mode: str,
    log_pinned: list[dict],
    log_memory: list[dict],
    log_obs: list[dict],
    token_budget: int,
    pinecone_config: dict,
) -> None:
    if not log_file:
        return
    try:
        from processors.retrieval_logger import log_retrieval
        log_retrieval(
            log_file=log_file,
            date_str=run_date,
            trigger=trigger,
            query_text=query_text,
            retrieval_mode=retrieval_mode,
            pinned_memories=log_pinned,
            memory_results=log_memory,
            observation_results=log_obs,
            token_budget=token_budget,
            config_snapshot={
                "retrieval_mode": pinecone_config.get("retrieval_mode", "auto"),
                "top_k": pinecone_config.get("top_k", 20),
                "memory_budget_pct": pinecone_config.get("memory_budget_pct", 0.6),
                "observation_budget_pct": pinecone_config.get("observation_budget_pct", 0.4),
                "score_threshold": pinecone_config.get("score_threshold"),
            },
        )
    except Exception as exc:
        print(f"WARNING: retrieval logging failed: {exc}", file=sys.stderr)


def _retrieve_memories_semantic(
    memory_dir: str,
    token_budget: int,
    pinecone_config: dict,
    query_signals: dict,
    log_file: Optional[str] = None,
    trigger: str = "brief",
    run_date: Optional[str] = None,
) -> str:
    today = date.today()
    _run_date = run_date or today.isoformat()
    char_budget = token_budget * 4

    # 1. Load pinned memories from files — always included, bypass ranking
    pinned_sections: list[str] = []
    pinned_ids: set[str] = set()
    log_pinned: list[dict] = []
    for path in sorted(Path(memory_dir).glob("*.md")):
        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue
        if not post.get("pinned", False) or post.get("suppress", False):
            continue
        topic = str(post.get("topic", path.stem))
        last_updated = str(post.get("last_updated", ""))
        content = post.content
        if "## Synthesized Memory" in content:
            synthesized = content.split("## Synthesized Memory")[1].strip()
            lines = [ln for ln in synthesized.splitlines() if not ln.startswith("_Last synthesized")]
            synthesized = "\n".join(lines).strip()
        else:
            synthesized = content.strip()
        if synthesized:
            section = f"**{topic}** (updated: {last_updated})\n{synthesized}"
            pinned_sections.append(section)
            pinned_ids.add(f"mem:{path.name}")
            log_pinned.append({
                "file": path.name,
                "topic": topic,
                "tokens": len(section) // 4,
            })

    # 2. Build query — fall back to file-based if no usable signals
    query_string = build_query_string(query_signals)
    if not query_string:
        return _retrieve_memories_file_based(memory_dir, token_budget)

    # 3. Query Pinecone
    mem_matches, obs_matches = query_pinecone(pinecone_config, query_string)

    # 4. Compute budget split (pinned always included, non-capped)
    pinned_chars = sum(len(s) for s in pinned_sections)
    header = "## Cross-Day Memory"
    remaining = char_budget - len(header) - pinned_chars
    mem_budget = int(remaining * 0.6)
    obs_budget = remaining - mem_budget

    # 5. Process memory results with inline budget tracking
    context_sections: list[str] = []
    log_memory: list[dict] = []
    mem_used = 0
    for match in mem_matches:
        meta = match.metadata or {}
        score = getattr(match, "score", None)
        match_id = match.id

        if match_id in pinned_ids:
            log_memory.append({
                "id": match_id,
                "namespace": "memories",
                "score": score,
                "included": False,
                "excluded_reason": "duplicate_of_pinned",
            })
            continue

        expires_str = str(meta.get("expires", ""))
        try:
            if expires_str and date.fromisoformat(expires_str) < today:
                log_memory.append({
                    "id": match_id,
                    "namespace": "memories",
                    "score": score,
                    "included": False,
                    "excluded_reason": "expired",
                })
                continue
        except ValueError:
            pass

        section = _load_memory_section(memory_dir, match_id)
        if section is None:
            log_memory.append({
                "id": match_id,
                "namespace": "memories",
                "score": score,
                "included": False,
                "excluded_reason": "suppressed",
            })
            continue

        if mem_used + len(section) > mem_budget:
            log_memory.append({
                "id": match_id,
                "namespace": "memories",
                "score": score,
                "content_preview": section[:80],
                "included": False,
                "excluded_reason": "budget_exhausted",
            })
            continue

        tokens = len(section) // 4
        topic_val = str(meta.get("topic", match_id[4:].replace(".md", "") if match_id.startswith("mem:") else match_id))
        log_memory.append({
            "id": match_id,
            "namespace": "memories",
            "score": score,
            "topic": topic_val,
            "content_preview": section[:80],
            "included": True,
            "tokens": tokens,
        })
        context_sections.append(section)
        mem_used += len(section)

    # 6. Process observation results with inline budget tracking
    obs_lines: list[str] = []
    log_obs: list[dict] = []
    obs_used = 0
    for match in obs_matches:
        meta = match.metadata or {}
        score = getattr(match, "score", None)
        obs_date = meta.get("date", "")
        obs_type = meta.get("type", "")
        entity = meta.get("entity", "")
        preview = meta.get("content_preview", "")

        if not preview:
            continue

        line = f"[{obs_date}] {obs_type}: {preview}"

        if obs_used + len(line) > obs_budget:
            log_obs.append({
                "id": match.id,
                "namespace": "observations",
                "score": score,
                "type": obs_type,
                "entity": entity,
                "content_preview": preview[:80],
                "included": False,
                "excluded_reason": "budget_exhausted",
            })
            continue

        tokens = len(line) // 4
        log_obs.append({
            "id": match.id,
            "namespace": "observations",
            "score": score,
            "type": obs_type,
            "entity": entity,
            "content_preview": preview[:80],
            "included": True,
            "tokens": tokens,
        })
        obs_lines.append(line)
        obs_used += len(line)

    # 7. Build output
    if not pinned_sections and not context_sections and not obs_lines:
        _maybe_log_retrieval(
            log_file, _run_date, trigger, query_string, "semantic",
            log_pinned, log_memory, log_obs, token_budget, pinecone_config,
        )
        return ""

    output_parts = [header]
    all_context = pinned_sections + context_sections
    if all_context:
        output_parts.append("### Context\n\n" + "\n\n".join(all_context))
    if obs_lines:
        output_parts.append("### Recent Signals\n\n" + "\n".join(obs_lines))

    result = "\n\n".join(output_parts)

    # 8. Log (non-fatal)
    _maybe_log_retrieval(
        log_file, _run_date, trigger, query_string, "semantic",
        log_pinned, log_memory, log_obs, token_budget, pinecone_config,
    )

    return result


def retrieve_memories(
    memory_dir: str,
    token_budget: int = 550,
    pinecone_config: Optional[dict] = None,
    query_signals: Optional[dict] = None,
    log_file: Optional[str] = None,
    trigger: str = "brief",
    run_date: Optional[str] = None,
) -> str:
    """Retrieve cross-day memory context for the brief.

    With pinecone_config and query_signals: uses semantic retrieval (mode controlled by
    pinecone_config["retrieval_mode"]: "auto" | "semantic" | "file").
    Without pinecone_config: always file-based (backward-compatible).
    """
    mode = "file"
    if pinecone_config:
        mode = pinecone_config.get("retrieval_mode", "auto")

    if mode == "file" or not pinecone_config:
        return _retrieve_memories_file_based(memory_dir, token_budget)

    try:
        return _retrieve_memories_semantic(
            memory_dir, token_budget, pinecone_config, query_signals or {},
            log_file=log_file, trigger=trigger, run_date=run_date,
        )
    except Exception as exc:
        if mode == "semantic":
            raise
        print(
            f"WARNING: Pinecone retrieval failed ({exc}), falling back to file-based.",
            file=sys.stderr,
        )
        _maybe_log_retrieval(
            log_file, run_date or date.today().isoformat(), trigger,
            "", "file_fallback", [], [], [], token_budget, pinecone_config,
        )
        return _retrieve_memories_file_based(memory_dir, token_budget)
