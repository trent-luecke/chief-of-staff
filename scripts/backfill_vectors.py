#!/usr/bin/env python3
"""One-time backfill: embed all existing observations and memory files into Pinecone."""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

import voyageai
from pinecone import Pinecone

from processors.vector_ingest import (
    prepare_observation_records,
    prepare_memory_records,
    _embed_and_upsert,
    save_ingest_state,
    IngestState,
)


def main():
    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
    if not pinecone_key or not voyage_key:
        print("ERROR: PINECONE_API_KEY and VOYAGE_API_KEY must be set.", file=sys.stderr)
        sys.exit(1)

    with open(_ROOT / "config.json") as f:
        config = json.load(f)

    vector_cfg = config.get("vector", {})
    memory_cfg = config.get("memory", {})

    index_name = vector_cfg.get("index_name", "chief-of-staff")
    model = vector_cfg.get("embedding_model", "voyage-3-lite")
    obs_ns = vector_cfg.get("observations_namespace", "observations")
    mem_ns = vector_cfg.get("memories_namespace", "memories")
    state_file = str(_ROOT / vector_cfg.get("ingest_state_file", "data/vector_ingest_state.json"))

    obs_file = str(_ROOT / memory_cfg.get("observations_file", "data/memory/observations.jsonl"))
    memory_dir = str(_ROOT / memory_cfg.get("dir", "data/memory"))

    pc = Pinecone(api_key=pinecone_key)
    pc_index = pc.Index(index_name)
    vo = voyageai.Client(api_key=voyage_key)

    # Backfill all observations from line 0
    print("Loading all observations...")
    obs_records = prepare_observation_records(obs_file, start_line=0)
    print(f"  {len(obs_records)} observation records to embed.")

    if obs_records:
        print("Embedding and upserting observations...")
        count = _embed_and_upsert(vo, pc_index, obs_ns, model, obs_records)
        print(f"  Upserted {count} observation vectors.")

    # Backfill all memory files
    print("Loading all memory files...")
    mem_records, new_mtimes = prepare_memory_records(memory_dir, previous_mtimes={})
    print(f"  {len(mem_records)} memory records to embed.")

    if mem_records:
        print("Embedding and upserting memories...")
        count = _embed_and_upsert(vo, pc_index, mem_ns, model, mem_records)
        print(f"  Upserted {count} memory vectors.")

    # Save state so daily ingest picks up from where backfill left off
    state = IngestState(
        last_obs_line=obs_records[-1]["line_number"] + 1 if obs_records else 0,
        memory_mtimes=new_mtimes,
    )
    save_ingest_state(state, state_file)
    print(f"  State saved: next daily ingest starts at line {state.last_obs_line}.")
    print("Backfill complete.")


if __name__ == "__main__":
    main()
