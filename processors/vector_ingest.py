"""Vector ingest: embed observations and memory files into Pinecone via Voyage AI."""

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

import frontmatter
import voyageai

from pinecone import Pinecone

_OBS_KEY = "memory/observations.jsonl"
_STATE_KEY = "vector_ingest_state.json"


@dataclass
class IngestState:
    last_obs_line: int = 0
    memory_mtimes: dict = field(default_factory=dict)
    raw_record_ids: dict = field(default_factory=dict)
    sidecar_enriched_lines: list = field(default_factory=list)


def load_ingest_state(storage) -> IngestState:
    data = storage.read_json(_STATE_KEY)
    if data is None:
        return IngestState()
    return IngestState(
        last_obs_line=data.get("last_obs_line", 0),
        memory_mtimes=data.get("memory_mtimes", {}),
        raw_record_ids=data.get("raw_record_ids", {}),
        sidecar_enriched_lines=data.get("sidecar_enriched_lines", []),
    )


def save_ingest_state(state: IngestState, storage) -> None:
    storage.write_json(_STATE_KEY, asdict(state))


def _sanitize_id(raw: str) -> str:
    """Transliterate non-ASCII characters to ASCII for Pinecone vector IDs."""
    import unicodedata
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_only = normalized.encode("ascii", errors="ignore").decode("ascii")
    return re.sub(r"-{2,}", "-", ascii_only)


def _load_person_names() -> dict:
    """Return person_id → canonical_name from the registry (best-effort)."""
    registry_file = Path("data/people_registry.json")
    try:
        if registry_file.exists():
            data = json.loads(registry_file.read_text(encoding="utf-8"))
            return {p["id"]: p["canonical_name"] for p in data.get("people", [])}
    except Exception:
        pass
    return {}


def _load_sidecar(sidecar_file: str | None) -> dict:
    """Load people_resolution.json sidecar. Returns empty dict if absent."""
    if not sidecar_file:
        return {}
    try:
        p = Path(sidecar_file)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")).get("resolutions", {})
    except Exception:
        pass
    return {}


def build_observation_text(obs: dict, person_name: str | None = None) -> str:
    """Build the text string to embed for a single observation.

    When person_name is provided, it is prepended to improve embedding quality
    by grounding the semantic content to a specific person.
    """
    obs_type = obs.get("type", "unknown")
    content = obs.get("content", "")
    if person_name:
        prefix = f"{obs_type} [{person_name}]: {content}"
    else:
        prefix = f"{obs_type}: {content}"
    parts = [prefix]
    if obs.get("context"):
        parts.append(f"Context: {obs['context']}")
    return " | ".join(parts)


def prepare_observation_records(
    obs_file: str, start_line: int = 0
) -> list[dict]:
    """Read observations from start_line onward and return records for embedding."""
    records = []
    try:
        with open(obs_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                except json.JSONDecodeError:
                    continue
                obs_date = obs.get("date", "unknown")
                obs_type = obs.get("type", "unknown")
                entity = obs.get("entity", "unknown")
                vector_id = _sanitize_id(f"{obs_date}:{obs_type}:{entity}:{i}")
                records.append({
                    "id": vector_id,
                    "text": build_observation_text(obs),
                    "metadata": {
                        "date": obs_date,
                        "type": obs_type,
                        "entity": entity,
                        "source": obs.get("source", ""),
                        "content_preview": obs.get("content", "")[:500],
                    },
                    "line_number": i,
                })
    except FileNotFoundError:
        pass
    return records


def prepare_memory_records(
    memory_dir: str, previous_mtimes: dict
) -> tuple[list[dict], dict]:
    """Read memory .md files that changed since last ingest. Returns (records, new_mtimes)."""
    records = []
    new_mtimes = dict(previous_mtimes)

    for path in sorted(Path(memory_dir).glob("*.md")):
        fname = path.name
        current_mtime = path.stat().st_mtime

        # Skip if unchanged
        if previous_mtimes.get(fname) == current_mtime:
            continue

        try:
            post = frontmatter.load(str(path))
        except Exception:
            continue

        # Skip suppressed files
        if post.get("suppress", False):
            new_mtimes[fname] = current_mtime
            continue

        # Extract text to embed
        content = post.content
        if "## Synthesized Memory" in content:
            parts = content.split("## Synthesized Memory")
            human_section = parts[0].strip()
            synthesized = parts[1].strip()
            # Strip the timestamp line
            lines = [l for l in synthesized.splitlines()
                     if not l.strip().startswith("_Last synthesized")]
            synthesized = "\n".join(lines).strip()
            text = f"{human_section}\n\n{synthesized}" if human_section else synthesized
        else:
            text = content.strip()

        if not text:
            new_mtimes[fname] = current_mtime
            continue

        topic = str(post.get("topic", path.stem))
        records.append({
            "id": _sanitize_id(f"mem:{fname}"),
            "text": text,
            "metadata": {
                "topic": topic,
                "last_updated": str(post.get("last_updated", "")),
                "expires": str(post.get("expires", "")),
                "pinned": bool(post.get("pinned", False)),
                "content_preview": text[:500],
            },
        })
        new_mtimes[fname] = current_mtime

    return records, new_mtimes


def _raw_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip())[:40].strip("-")


def _content_hash(values: list) -> str:
    combined = "|".join(str(v) for v in values)
    return hashlib.md5(combined.encode()).hexdigest()[:12]


def _lead_records(pipeline_leads: list, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for lead in pipeline_leads:
        page_id = lead.get("page_id", "")
        if not page_id:
            continue
        record_id = f"lead:{page_id}"
        status = lead.get("status") or ""
        days = lead.get("days_since_contact") or 0
        priority = lead.get("priority") or ""
        fingerprint = f"{status}:{days}:{priority}"
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue
        source = lead.get("source") or ""
        stale_str = " | stale" if lead.get("stale") else ""
        text = (
            f"Pipeline lead: {lead.get('name') or ''} | "
            f"status: {status} | "
            f"source: {source} | "
            f"priority: {priority} | "
            f"{days} days since contact{stale_str}"
        )
        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "name": lead.get("name") or "",
                "status": status,
                "source": source,
                "priority": priority,
                "days_since_contact": days,
                "stale": bool(lead.get("stale", False)),
                "email": lead.get("email") or "",
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def _bug_records(bugs: list, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for bug in bugs:
        bug_id = bug.get("id", "")
        if not bug_id:
            continue
        record_id = f"bug:{bug_id}"
        last_updated = bug.get("last_updated") or ""
        fingerprint = last_updated
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue
        title = bug.get("title") or ""
        status = bug.get("status") or ""
        priority = bug.get("priority_level") or ""
        areas = bug.get("technical_areas") or []
        days_open = bug.get("days_open") or 0
        areas_str = ", ".join(areas) if areas else "untagged"
        text = (
            f"Bug: {title} | "
            f"status: {status} | "
            f"priority: {priority} | "
            f"areas: {areas_str} | "
            f"{days_open} days open"
        )
        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "title": title,
                "status": status,
                "priority_level": priority,
                "technical_areas": areas,
                "date_created": bug.get("date_created") or "",
                "days_open": days_open,
                "shortcut_url": bug.get("shortcut_url") or "",
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def _cancellation_records(cancellations: dict, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for entry in (cancellations or {}).get("entries", []):
        date_str = entry.get("date", "")
        account = entry.get("account_name", "")
        if not date_str or not account:
            continue
        record_id = f"cancel:{_raw_slug(date_str)}:{_raw_slug(account)}"
        fingerprint = _content_hash([
            date_str, account, entry.get("reason", ""), entry.get("monetary_value", "")
        ])
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue

        reason = entry.get("reason", "")
        base_plan = entry.get("base_plan", "")
        monetary_value = entry.get("monetary_value", "")
        customer_note = entry.get("customer_note", "")

        parts = [f"Cancellation: {account} on {date_str}"]
        if reason:
            parts.append(f"reason: {reason}")
        if base_plan:
            parts.append(f"base plan: {base_plan}")
        if monetary_value:
            parts.append(f"monetary value: {monetary_value}")
        if customer_note:
            parts.append(f"customer note: {customer_note}")
        text = " | ".join(parts)

        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "date": date_str,
                "account_name": account,
                "reason": reason,
                "base_plan": base_plan,
                "monetary_value": monetary_value,
                "customer_returned": entry.get("customer_returned", ""),
                "lifetime_value": entry.get("lifetime_value", ""),
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def _sale_records(sales_entries: list, previous_ids: dict) -> tuple[list, dict]:
    records = []
    new_ids = {}
    for entry in (sales_entries or []):
        date_str = entry.get("date", "")
        customer = entry.get("customer", "")
        if not date_str or not customer:
            continue
        record_id = f"sale:{_raw_slug(date_str)}:{_raw_slug(customer)}"
        fingerprint = _content_hash([
            date_str, customer, str(entry.get("total", "")), entry.get("sale_type", "")
        ])
        if previous_ids.get(record_id) == fingerprint:
            new_ids[record_id] = fingerprint
            continue

        total = entry.get("total", 0.0)
        sale_type = entry.get("sale_type", "")
        salesperson = entry.get("salesperson", "")

        try:
            total_fmt = f"${float(total):,.0f}"
        except (TypeError, ValueError):
            total_fmt = str(total)

        text = (
            f"Sale: {customer} on {date_str} | "
            f"{total_fmt} | "
            f"type: {sale_type} | "
            f"salesperson: {salesperson}"
        )
        records.append({
            "id": _sanitize_id(record_id),
            "text": text,
            "metadata": {
                "date": date_str,
                "customer": customer,
                "total": total,
                "sale_type": sale_type,
                "salesperson": salesperson,
            },
        })
        new_ids[record_id] = fingerprint
    return records, new_ids


def prepare_raw_records(
    pipeline_leads: list,
    bugs: list,
    cancellations: dict,
    sales_entries: list,
    previous_ids: dict,
) -> tuple[list, dict]:
    """Build raw_data records for all KPI sources. Returns (records_to_upsert, new_id_state)."""
    all_records = []
    new_ids = dict(previous_ids)

    lead_recs, lead_ids = _lead_records(pipeline_leads or [], previous_ids)
    all_records.extend(lead_recs)
    new_ids.update(lead_ids)

    bug_recs, bug_ids = _bug_records(bugs or [], previous_ids)
    all_records.extend(bug_recs)
    new_ids.update(bug_ids)

    cancel_recs, cancel_ids = _cancellation_records(cancellations or {}, previous_ids)
    all_records.extend(cancel_recs)
    new_ids.update(cancel_ids)

    sale_recs, sale_ids = _sale_records(sales_entries or [], previous_ids)
    all_records.extend(sale_recs)
    new_ids.update(sale_ids)

    return all_records, new_ids


def _embed_texts(
    voyage_client: voyageai.Client,
    texts: list[str],
    model: str,
    input_type: str = "document",
    batch_size: int = 128,
) -> list[list[float]]:
    """Embed texts via Voyage AI in batches. Returns list of embedding vectors."""
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = voyage_client.embed(batch, model=model, input_type=input_type)
        all_embeddings.extend(result.embeddings)
    return all_embeddings


def _embed_and_upsert(
    voyage_client: voyageai.Client,
    pc_index,
    namespace: str,
    model: str,
    records: list[dict],
    batch_size: int = 50,
) -> int:
    """Embed texts via Voyage AI and upsert vectors to Pinecone. Returns count upserted."""
    if not records:
        return 0

    texts = [r["text"] for r in records]
    embeddings = _embed_texts(voyage_client, texts, model)

    upserted = 0
    for i in range(0, len(records), batch_size):
        batch_records = records[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]

        vectors = []
        for record, embedding in zip(batch_records, batch_embeddings):
            vectors.append({
                "id": record["id"],
                "values": embedding,
                "metadata": record["metadata"],
            })

        pc_index.upsert(vectors=vectors, namespace=namespace)
        upserted += len(vectors)

    return upserted


def ingest(
    storage,
    pinecone_api_key: str,
    voyage_api_key: str,
    index_name: str,
    embedding_model: str,
    obs_namespace: str = "observations",
    mem_namespace: str = "memories",
    raw_namespace: str = "raw_data",
    pipeline_leads=None,
    bugs=None,
    cancellations=None,
    sales_entries=None,
    sidecar_file: str | None = None,
) -> None:
    """Run the full ingest pipeline: embed new observations + updated memories + raw KPI records."""
    state = load_ingest_state(storage)
    person_names = _load_person_names()
    sidecar = _load_sidecar(sidecar_file)
    enriched_set = set(state.sidecar_enriched_lines)

    # Prepare observation records from storage
    content = storage.read(_OBS_KEY) or ""
    lines = content.splitlines()
    obs_records = []
    for i, raw_line in enumerate(lines):
        if i < state.last_obs_line:
            continue
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obs = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        obs_date = obs.get("date", "unknown")
        obs_type = obs.get("type", "unknown")
        entity = obs.get("entity", "unknown")
        vector_id = _sanitize_id(f"{obs_date}:{obs_type}:{entity}:{i}")

        # Resolve person_id: prefer embedded field, fall back to sidecar
        person_id = obs.get("primary_person_id")
        related_ids = obs.get("related_person_ids", [])
        if person_id is None and str(i) in sidecar:
            res = sidecar[str(i)]
            person_id = res.get("primary_person_id")
            related_ids = res.get("related_person_ids", [])

        person_name = person_names.get(person_id) if person_id else None

        obs_records.append({
            "id": vector_id,
            "text": build_observation_text(obs, person_name),
            "metadata": {
                "date": obs_date,
                "type": obs_type,
                "entity": entity,
                "person_id": person_id or "",
                "related_person_ids": related_ids,
                "source": obs.get("source", ""),
                "content_preview": obs.get("content", "")[:500],
            },
            "line_number": i,
        })

    # Sidecar re-ingestion: enrich historical observations that now have a resolved person_id
    sidecar_records = []
    if sidecar and lines:
        for line_str, res in sidecar.items():
            line_num = int(line_str)
            if line_num in enriched_set:
                continue
            if line_num >= state.last_obs_line:
                continue  # Will be handled in the new-observations pass above
            person_id = res.get("primary_person_id")
            if not person_id:
                continue  # System-level or unresolved — no enrichment needed
            if line_num >= len(lines):
                continue
            raw_line = lines[line_num].strip()
            if not raw_line:
                continue
            try:
                obs = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            obs_date = obs.get("date", "unknown")
            obs_type = obs.get("type", "unknown")
            entity = obs.get("entity", "unknown")
            vector_id = _sanitize_id(f"{obs_date}:{obs_type}:{entity}:{line_num}")
            person_name = person_names.get(person_id)
            related_ids = res.get("related_person_ids", [])
            sidecar_records.append({
                "id": vector_id,
                "text": build_observation_text(obs, person_name),
                "metadata": {
                    "date": obs_date,
                    "type": obs_type,
                    "entity": entity,
                    "person_id": person_id,
                    "related_person_ids": related_ids,
                    "source": obs.get("source", ""),
                    "content_preview": obs.get("content", "")[:500],
                },
                "line_number": line_num,
            })

    # Prepare memory records from storage
    memory_keys = [
        key for key in storage.list_keys("memory")
        if key.endswith(".md") and not key.startswith("memory/archive/")
    ]
    mem_records = []
    new_mtimes = dict(state.memory_mtimes)
    for key in sorted(memory_keys):
        # Use content hash as a proxy for mtime when reading from storage
        mem_content = storage.read(key)
        if mem_content is None:
            continue
        current_mtime = hashlib.md5(mem_content.encode()).hexdigest()

        # Skip if unchanged
        if state.memory_mtimes.get(key) == current_mtime:
            continue

        try:
            post = frontmatter.loads(mem_content)
        except Exception:
            continue

        # Skip suppressed files
        if post.get("suppress", False):
            new_mtimes[key] = current_mtime
            continue

        # Extract text to embed
        mem_text = post.content
        if "## Synthesized Memory" in mem_text:
            parts = mem_text.split("## Synthesized Memory")
            human_section = parts[0].strip()
            synthesized = parts[1].strip()
            filtered_lines = [l for l in synthesized.splitlines()
                              if not l.strip().startswith("_Last synthesized")]
            synthesized = "\n".join(filtered_lines).strip()
            mem_text = f"{human_section}\n\n{synthesized}" if human_section else synthesized
        else:
            mem_text = mem_text.strip()

        if not mem_text:
            new_mtimes[key] = current_mtime
            continue

        fname = key.split("/")[-1]
        topic = str(post.get("topic", fname.replace(".md", "")))
        mem_records.append({
            "id": _sanitize_id(f"mem:{fname}"),
            "text": mem_text,
            "metadata": {
                "topic": topic,
                "last_updated": str(post.get("last_updated", "")),
                "expires": str(post.get("expires", "")),
                "pinned": bool(post.get("pinned", False)),
                "content_preview": mem_text[:500],
            },
        })
        new_mtimes[key] = current_mtime

    raw_records, new_raw_ids = prepare_raw_records(
        pipeline_leads=pipeline_leads or [],
        bugs=bugs or [],
        cancellations=cancellations or {},
        sales_entries=sales_entries or [],
        previous_ids=state.raw_record_ids,
    )

    if not obs_records and not mem_records and not raw_records and not sidecar_records:
        print("   No new data to ingest.")
        return

    # Initialize clients
    pc = Pinecone(api_key=pinecone_api_key)
    pc_index = pc.Index(index_name)
    vo = voyageai.Client(api_key=voyage_api_key)

    # Embed and upsert new observations
    if obs_records:
        obs_count = _embed_and_upsert(
            vo, pc_index, obs_namespace, embedding_model, obs_records
        )
        print(f"   Upserted {obs_count} observation vectors.")
        state.last_obs_line = obs_records[-1]["line_number"] + 1
        save_ingest_state(state, storage)

    # Re-ingest historical observations enriched with person_id from sidecar
    if sidecar_records:
        sidecar_count = _embed_and_upsert(
            vo, pc_index, obs_namespace, embedding_model, sidecar_records
        )
        print(f"   Re-upserted {sidecar_count} sidecar-enriched observation vectors.")
        state.sidecar_enriched_lines = sorted(
            enriched_set | {r["line_number"] for r in sidecar_records}
        )
        save_ingest_state(state, storage)

    # Embed and upsert memories
    if mem_records:
        mem_count = _embed_and_upsert(
            vo, pc_index, mem_namespace, embedding_model, mem_records
        )
        print(f"   Upserted {mem_count} memory vectors.")
        state.memory_mtimes = new_mtimes

    # Embed and upsert raw records
    if raw_records:
        raw_count = _embed_and_upsert(
            vo, pc_index, raw_namespace, embedding_model, raw_records
        )
        print(f"   Upserted {raw_count} raw_data vectors.")
        state.raw_record_ids = new_raw_ids

    save_ingest_state(state, storage)
