"""Marketing-funnel content catalog: storage, vocabularies, validation,
dedupe, and dispersion aggregation for the funnel-audit skill.

The catalog is a single committed JSON file (a list of asset records). This
module owns every deterministic operation on it; the skill (SKILL.md) does the
LLM reasoning and grounding-source reads on top.
"""
from __future__ import annotations

import json
import re
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


_REQUIRED = ("title", "type", "stage", "sub_stage", "product", "icp", "status", "source")

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    if not _ISO_DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate_asset(asset: dict) -> list[str]:
    """Return a list of validation errors for one asset record ([] = valid)."""
    errors: list[str] = []

    for field in _REQUIRED:
        if field not in asset or asset[field] in (None, "", []):
            errors.append(f"missing required field: {field}")

    title = asset.get("title")
    if title is not None and not (isinstance(title, str) and title.strip()):
        errors.append("title must be a non-empty string")

    if asset.get("type") is not None and asset["type"] not in TYPES:
        errors.append(f"type '{asset['type']}' is not in the controlled vocabulary")

    stage = asset.get("stage")
    if stage is not None and stage not in STAGES:
        errors.append(f"stage '{stage}' must be one of {STAGES}")

    sub_stage = asset.get("sub_stage")
    if stage in STAGE_SUBSTAGE and sub_stage is not None:
        if sub_stage not in STAGE_SUBSTAGE[stage]:
            errors.append(
                f"sub_stage '{sub_stage}' is not valid for stage {stage} "
                f"(expected one of {STAGE_SUBSTAGE[stage]})"
            )

    if asset.get("product") is not None and asset["product"] not in PRODUCTS:
        errors.append(f"product '{asset['product']}' must be one of {PRODUCTS}")

    icp = asset.get("icp")
    if icp is not None:
        if not isinstance(icp, list) or not icp:
            errors.append("icp must be a non-empty list")
        else:
            bad = [s for s in icp if s not in ICPS]
            if bad:
                errors.append(f"icp contains unknown slugs: {bad} (allowed: {ICPS})")

    if asset.get("status") is not None and asset["status"] not in STATUSES:
        errors.append(f"status '{asset['status']}' must be one of {STATUSES}")

    if asset.get("source") is not None and asset["source"] not in SOURCES:
        errors.append(f"source '{asset['source']}' must be one of {SOURCES}")

    for datefield in ("publish_date", "added_at"):
        if asset.get(datefield) not in (None, "") and not _is_iso_date(asset[datefield]):
            errors.append(f"{datefield} must be an ISO date (YYYY-MM-DD)")

    return errors


def stage_type_warning(asset: dict) -> str | None:
    """Warn (non-blocking) when a type sits in an unusual stage."""
    hint = TYPE_STAGE_HINT.get(asset.get("type"))
    stage = asset.get("stage")
    if hint and stage and hint != stage:
        return (
            f"type '{asset['type']}' usually sits in {hint}, "
            f"but this asset is tagged {stage} — confirm the tag."
        )
    return None


def _normalize(text: str) -> str:
    """Lowercase, strip, and collapse internal whitespace."""
    return " ".join(str(text or "").split()).lower()


def find_duplicates(asset: dict, catalog: list[dict]) -> list[dict]:
    """Existing entries that look like the same asset (title or url match)."""
    title = _normalize(asset.get("title", ""))
    url = (asset.get("url") or "").strip()
    hits: list[dict] = []
    for existing in catalog:
        same_title = title and _normalize(existing.get("title", "")) == title
        same_url = url and (existing.get("url") or "").strip() == url
        if same_title or same_url:
            hits.append(existing)
    return hits


def similar_themes(theme: str, catalog: list[dict]) -> list[str]:
    """Distinct existing themes close to `theme` (equal or substring either way)."""
    cand = _normalize(theme)
    if not cand:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for existing in catalog:
        raw = existing.get("theme")
        if not raw:
            continue
        norm = _normalize(raw)
        if norm in seen:
            continue
        if norm == cand or cand in norm or norm in cand:
            out.append(raw)
            seen.add(norm)
    return out
