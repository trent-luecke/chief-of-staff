"""Vector ingest: embed observations and memory files into Pinecone via Voyage AI."""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

import frontmatter
import voyageai

from pinecone import Pinecone


@dataclass
class IngestState:
    last_obs_line: int = 0
    memory_mtimes: dict = field(default_factory=dict)


def load_ingest_state(path: str) -> IngestState:
    try:
        with open(path) as f:
            data = json.load(f)
        return IngestState(
            last_obs_line=data.get("last_obs_line", 0),
            memory_mtimes=data.get("memory_mtimes", {}),
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return IngestState()


def save_ingest_state(state: IngestState, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(asdict(state), f, indent=2)


def _sanitize_id(raw: str) -> str:
    """Replace non-ASCII characters so Pinecone vector IDs are always valid ASCII."""
    return raw.encode("ascii", errors="replace").decode("ascii")


def build_observation_text(obs: dict) -> str:
    """Build the text string to embed for a single observation."""
    parts = [f"{obs.get('type', 'unknown')}: {obs.get('content', '')}"]
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
                        "content_preview": obs.get("content", "")[:200],
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
            "id": f"mem:{fname}",
            "text": text,
            "metadata": {
                "topic": topic,
                "last_updated": str(post.get("last_updated", "")),
                "expires": str(post.get("expires", "")),
                "pinned": bool(post.get("pinned", False)),
                "content_preview": text[:200],
            },
        })
        new_mtimes[fname] = current_mtime

    return records, new_mtimes


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
    obs_file: str,
    memory_dir: str,
    pinecone_api_key: str,
    voyage_api_key: str,
    index_name: str,
    embedding_model: str,
    obs_namespace: str = "observations",
    mem_namespace: str = "memories",
    state_file: str = "data/vector_ingest_state.json",
) -> None:
    """Run the full ingest pipeline: embed new observations + updated memories."""
    state = load_ingest_state(state_file)

    # Prepare records
    obs_records = prepare_observation_records(obs_file, start_line=state.last_obs_line)
    mem_records, new_mtimes = prepare_memory_records(memory_dir, state.memory_mtimes)

    if not obs_records and not mem_records:
        print("   No new data to ingest.")
        return

    # Initialize clients
    pc = Pinecone(api_key=pinecone_api_key)
    pc_index = pc.Index(index_name)
    vo = voyageai.Client(api_key=voyage_api_key)

    # Embed and upsert observations
    if obs_records:
        obs_count = _embed_and_upsert(
            vo, pc_index, obs_namespace, embedding_model, obs_records
        )
        print(f"   Upserted {obs_count} observation vectors.")
        state.last_obs_line = obs_records[-1]["line_number"] + 1
        save_ingest_state(state, state_file)

    # Embed and upsert memories
    if mem_records:
        mem_count = _embed_and_upsert(
            vo, pc_index, mem_namespace, embedding_model, mem_records
        )
        print(f"   Upserted {mem_count} memory vectors.")
        state.memory_mtimes = new_mtimes

    save_ingest_state(state, state_file)
