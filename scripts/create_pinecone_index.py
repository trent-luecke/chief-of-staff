#!/usr/bin/env python3
"""One-time script: create the chief-of-staff Pinecone index."""

import json
import os
import sys

from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

from pinecone import Pinecone, ServerlessSpec


def main():
    api_key = os.environ.get("PINECONE_API_KEY", "")
    if not api_key:
        print("ERROR: PINECONE_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(_ROOT, "config.json")) as f:
        config = json.load(f)

    vector_cfg = config.get("vector", {})
    index_name = vector_cfg.get("index_name", "chief-of-staff")
    dimension = vector_cfg.get("embedding_dimension", 512)

    pc = Pinecone(api_key=api_key)

    # Check if index already exists
    existing = [idx.name for idx in pc.list_indexes()]
    if index_name in existing:
        print(f"Index '{index_name}' already exists. Nothing to do.")
        desc = pc.describe_index(index_name)
        print(f"  Dimension: {desc.dimension}")
        print(f"  Metric: {desc.metric}")
        print(f"  Host: {desc.host}")
        return

    print(f"Creating index '{index_name}' (dim={dimension}, cosine, AWS us-east-1)...")
    pc.create_index(
        name=index_name,
        dimension=dimension,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    print(f"Index '{index_name}' created successfully.")
    try:
        desc = pc.describe_index(index_name)
        print(f"  Host: {desc.host}")
    except Exception as e:
        print(f"  (Could not fetch index details: {e})")


if __name__ == "__main__":
    main()
