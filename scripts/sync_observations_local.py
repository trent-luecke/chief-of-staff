"""Pull observations.jsonl from R2 to local data/memory/ for the registry UI.

Reads storage config from config.json. If R2 is not enabled, exits silently
(LocalStorage means the file is already on disk). Safe to re-run — always
overwrites with the latest from R2.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.storage import build_storage

config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
storage = build_storage(config)

KEY = "memory/observations.jsonl"
LOCAL_PATH = ROOT / "data" / KEY

content = storage.read(KEY)
if content is None:
    print("No observations.jsonl found in storage.")
    sys.exit(0)

LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
LOCAL_PATH.write_text(content, encoding="utf-8")

lines = content.strip().splitlines()
print(f"Synced {len(lines)} observation lines → data/memory/observations.jsonl")
