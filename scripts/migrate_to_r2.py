#!/usr/bin/env python3
"""
One-shot migration: copy all runtime state files from local data/ into R2.

Run this ONCE before flipping storage.r2.enabled to true.
Human-authored files (data/people/, data/projects.md, etc.) are skipped.

Usage:
    python scripts/migrate_to_r2.py [--dry-run]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Files/dirs managed by humans — do not migrate to R2
HUMAN_AUTHORED = {
    "people",           # data/people/*.md
    "projects.md",
    "recurring.json",
    "meeting_index.json",
    "memory/decisions.md",
}

# Credential/token files that must never leave local disk
SKIP_FILES = {
    ".slides_token.json",
}

# Dirs that are gitignored and shouldn't be migrated
SKIP_DIRS = {"drafts", "__pycache__"}


def should_skip(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    if parts[0] in SKIP_DIRS:
        return True
    if parts[-1] in SKIP_FILES:
        return True
    for human in HUMAN_AUTHORED:
        if rel_path == human or rel_path.startswith(human + "/"):
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="List files without uploading")
    args = parser.parse_args()

    with open("config.json") as f:
        config = json.load(f)

    r2_cfg = config.get("storage", {}).get("r2", {})
    if not r2_cfg.get("account_id") or r2_cfg["account_id"] == "YOUR_CLOUDFLARE_ACCOUNT_ID":
        print("ERROR: account_id not set in config.json", file=sys.stderr)
        sys.exit(1)

    access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    if not access_key or not secret_key:
        print("ERROR: R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY not set in environment", file=sys.stderr)
        sys.exit(1)

    import boto3
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{r2_cfg['account_id']}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    bucket = r2_cfg["bucket"]

    data_dir = Path(config.get("data_dir", "data"))
    if not data_dir.exists():
        print(f"ERROR: {data_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    files = sorted(f for f in data_dir.rglob("*") if f.is_file())
    uploaded = 0
    skipped = 0

    for path in files:
        rel = str(path.relative_to(data_dir))
        if should_skip(rel):
            print(f"  skip  {rel}")
            skipped += 1
            continue

        if args.dry_run:
            print(f"  would upload  {rel}")
            uploaded += 1
            continue

        try:
            s3.upload_file(str(path), bucket, rel)
            print(f"  ✓  {rel}")
            uploaded += 1
        except Exception as e:
            print(f"  ✗  {rel}: {e}", file=sys.stderr)

    print(f"\n{'[dry run] ' if args.dry_run else ''}Done — {uploaded} files {'would be ' if args.dry_run else ''}uploaded, {skipped} skipped.")


if __name__ == "__main__":
    main()
