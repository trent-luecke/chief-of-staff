"""Marketing-funnel content catalog: storage, vocabularies, validation,
dedupe, and dispersion aggregation for the funnel-audit skill.

The catalog is a single committed JSON file (a list of asset records). This
module owns every deterministic operation on it; the skill (SKILL.md) does the
LLM reasoning and grounding-source reads on top.
"""
from __future__ import annotations

import json
import secrets
from collections import Counter
from datetime import date
from pathlib import Path

DEFAULT_CATALOG_PATH = Path("data/funnel/content_catalog.json")

STAGES: list[str] = ["TOFU", "MOFU", "BOFU"]
SUB_STAGES: list[str] = ["awareness", "consideration", "evaluation", "decision"]
STAGE_SUBSTAGE: dict[str, list[str]] = {
    "TOFU": ["awareness"],
    "MOFU": ["consideration"],
    "BOFU": ["evaluation", "decision"],
}

# Format vocabulary → the stage it *usually* lives in (None = stage-flexible,
# never warns). stage and type are independent axes; the hint only drives a
# non-blocking mistag warning.
TYPE_STAGE_HINT: dict[str, str | None] = {
    "blog": "TOFU",
    "social_post": "TOFU",
    "podcast": "TOFU",
    "short_video": "TOFU",
    "infographic": "TOFU",
    "guest_article": "TOFU",
    "webinar": "MOFU",
    "ebook_guide": "MOFU",
    "email_nurture": "MOFU",
    "comparison_guide": "MOFU",
    "checklist_template": "MOFU",
    "case_study": "MOFU",
    "roi_calculator": "BOFU",
    "demo_video": "BOFU",
    "comparison_page": "BOFU",
    "objection_one_pager": "BOFU",
    "pricing_page": "BOFU",
    "customer_story": "BOFU",
    "interactive_tool": None,
}
TYPES: set[str] = set(TYPE_STAGE_HINT)

ICPS: list[str] = [
    "sports_performance", "crossfit", "pt_studio", "hybrid_clinic_gym", "boutique",
]
PRODUCTS: list[str] = ["os", "strength", "both"]
STATUSES: list[str] = ["live", "draft", "planned", "retired"]
SOURCES: list[str] = ["seed", "campaign_audit", "manual"]


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> list[dict]:
    """Return the catalog as a list of asset dicts; [] if the file is absent."""
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_catalog(assets: list[dict], path: Path = DEFAULT_CATALOG_PATH) -> None:
    """Write the catalog as pretty JSON, creating the parent directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(assets, indent=2) + "\n")


def new_asset_id() -> str:
    """A short, collision-resistant asset id like 'asset-9f2a1c'."""
    return "asset-" + secrets.token_hex(3)
