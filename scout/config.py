"""Config + path resolution for the Fitness Scout module."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
BRIEFS_DIR = DATA_DIR / "briefs"
CANDIDATES_FILE = DATA_DIR / "candidates.jsonl"
COVERED_FILE = DATA_DIR / "covered.jsonl"
GROUNDING_FILE = BASE_DIR / "os_grounding.md"
CONFIG_FILE = CONFIG_DIR / "scout_config.json"


def load_config() -> dict:
    """Load scout_config.json."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_grounding() -> str:
    """Load the hand-curated OS grounding profile as raw text."""
    return GROUNDING_FILE.read_text(encoding="utf-8")
