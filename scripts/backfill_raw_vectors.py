#!/usr/bin/env python3
"""One-time backfill: embed all existing pipeline leads, bugs, and cancellations
into the raw_data Pinecone namespace.

Run once after deploying P15:
    python scripts/backfill_raw_vectors.py
"""
import dataclasses
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.notion_bugs import fetch_bugs
from collectors.sheets import fetch_cancellations_mtd
from lib.google_auth import build_sheets_service
from processors.vector_ingest import (
    IngestState,
    load_ingest_state,
    prepare_raw_records,
    _embed_and_upsert,
    save_ingest_state,
)
from pinecone import Pinecone
import voyageai


CONFIG_PATH = "config.json"
PIPELINE_CACHE = "data/pipeline_cache.json"
STATE_FILE = "data/vector_ingest_state.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def main():
    config = load_config()
    vector_cfg = config.get("vector", {})
    sheets_cfg = config.get("sheets", {})

    pinecone_key = os.environ.get("PINECONE_API_KEY", "")
    voyage_key = os.environ.get("VOYAGE_API_KEY", "")
    notion_token = os.environ.get("NOTION_TOKEN", "")

    if not pinecone_key or not voyage_key:
        print("ERROR: PINECONE_API_KEY and VOYAGE_API_KEY required.", file=sys.stderr)
        sys.exit(1)

    index_name = vector_cfg["index_name"]
    embedding_model = vector_cfg["embedding_model"]
    raw_namespace = vector_cfg.get("raw_data_namespace", "raw_data")

    # Load existing ingest state
    state = load_ingest_state(STATE_FILE)

    # 1. Pipeline leads
    all_leads = []
    try:
        with open(PIPELINE_CACHE) as f:
            all_leads = json.load(f).get("leads", [])
        print(f"Loaded {len(all_leads)} pipeline leads from cache.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: Could not load pipeline cache: {e}")

    # 2. Bug tickets (all statuses, not just open)
    bugs = []
    if notion_token:
        try:
            print("Fetching all bug tickets from Notion...")
            bug_objects = fetch_bugs(notion_token)
            bugs = [dataclasses.asdict(b) for b in bug_objects]
            print(f"Fetched {len(bugs)} bug tickets.")
        except Exception as e:
            print(f"WARNING: Bug fetch failed: {e}")
    else:
        print("WARNING: NOTION_TOKEN not set — skipping bugs.")

    # 3. All cancellations (month=None to get full history)
    cancellations = {"count": 0, "entries": []}
    cancel_sheet_id = sheets_cfg.get("cancellations_spreadsheet_id", "")
    cancel_tab = sheets_cfg.get("cancellations_tab_name", "MONTHLY Cancellations")
    if cancel_sheet_id:
        try:
            print("Fetching all cancellations from Sheets...")
            svc = build_sheets_service()
            cancellations = fetch_cancellations_mtd(svc, cancel_sheet_id, cancel_tab, month=None)
            print(f"Fetched {cancellations['count']} cancellation entries.")
        except Exception as e:
            print(f"WARNING: Cancellations fetch failed: {e}")

    # Prepare records — ignore previous_ids so everything gets re-embedded
    records, new_raw_ids = prepare_raw_records(
        pipeline_leads=all_leads,
        bugs=bugs,
        cancellations=cancellations,
        sales_entries=[],  # sales are MTD only; no historical backfill needed
        previous_ids={},   # force re-embed of everything
    )

    if not records:
        print("No records to backfill.")
        return

    print(f"\nEmbedding {len(records)} records into '{raw_namespace}' namespace...")

    pc = Pinecone(api_key=pinecone_key)
    pc_index = pc.Index(index_name)
    vo = voyageai.Client(api_key=voyage_key)

    count = _embed_and_upsert(vo, pc_index, raw_namespace, embedding_model, records)
    print(f"Upserted {count} vectors into '{raw_namespace}'.")

    # Update state with new raw_record_ids
    state.raw_record_ids = new_raw_ids
    save_ingest_state(state, STATE_FILE)
    print(f"State updated: {len(new_raw_ids)} raw record IDs tracked.")
    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
