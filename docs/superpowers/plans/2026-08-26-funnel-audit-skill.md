# Funnel Audit Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill `funnel-audit` that maintains a catalog of TeamBuildr OS marketing assets tagged by funnel stage, and audits campaigns / generates MOFU ideas grounded in real call, pipeline, and positioning data.

**Architecture:** A deterministic Python helper (`lib/funnel_catalog.py`) owns the catalog file — storage, controlled vocabularies, validation, dedupe, and dispersion aggregation, all unit-tested. A prose skill (`.claude/skills/funnel-audit/SKILL.md`) orchestrates the four modes (seed, campaign audit, dispersion, MOFU ideation), calls the helper for anything deterministic, and does the LLM reasoning + grounding-source reads. The catalog is one committed JSON file; no runtime job, cron, R2, or Pinecone touches it.

**Tech Stack:** Python 3 (stdlib only — `json`, `pathlib`, `secrets`, `datetime`, `collections`), pytest, Markdown skill with YAML frontmatter.

## Global Constraints

- **Catalog path:** `data/funnel/content_catalog.json` — a JSON list of asset records.
- **Git-tracked:** add `!data/funnel/` and `!data/funnel/**` to `.gitignore` (the `data/*` allow-list pattern; mirrors `!data/people/` + `!data/people/**`).
- **Stage vocabulary:** `TOFU` (=awareness), `MOFU` (=consideration), `BOFU` (=evaluation+decision). `sub_stage` ∈ `awareness|consideration|evaluation|decision` and MUST be consistent with `stage`.
- **`product` defaults to `os`.** Never let `strength`/`both` content inflate OS MOFU counts.
- **Type is a controlled vocabulary** — never free text. `stage` and `type` are independent axes; unusual combos warn, never block.
- **ICP slugs (hard-coded):** `sports_performance`, `crossfit`, `pt_studio`, `hybrid_clinic_gym`, `boutique`.
- **Guardrail layer flags, never suppresses** — generated ideas leaning on non-`[PROVABLE]` claims or brushing a positioning rule carry a visible `⚠ guardrail:` note; the call stays with Trent.
- **Generated assets land as `planned`, never `live`.** The skill outputs briefs, not finished copy.
- **Every audit/ideation output leads with a "Sources pulled" block** naming calls scanned (date range), deals referenced, and unique-prospect counts; sources that could not be reached are named, never silently omitted.
- **Style:** `from __future__ import annotations`, module docstring, type hints, `pathlib.Path`. Tests import `from lib import funnel_catalog`, run via `pytest` (`testpaths = tests`).
- **After any catalog write, remind the user to commit + push** (`origin/main` is a live datastore; rebase before push).

---

### Task 1: Catalog storage, vocabularies, and git wiring

**Files:**
- Create: `lib/funnel_catalog.py`
- Create: `data/funnel/content_catalog.json`
- Modify: `.gitignore` (append allow-list lines)
- Test: `tests/test_funnel_catalog.py`

**Interfaces:**
- Produces:
  - Constants: `STAGES: list[str]`, `SUB_STAGES: list[str]`, `STAGE_SUBSTAGE: dict[str, list[str]]`, `TYPE_STAGE_HINT: dict[str, str | None]`, `TYPES: set[str]`, `ICPS: list[str]`, `PRODUCTS: list[str]`, `STATUSES: list[str]`, `SOURCES: list[str]`, `DEFAULT_CATALOG_PATH: Path`
  - `load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> list[dict]` — `[]` if file missing.
  - `save_catalog(assets: list[dict], path: Path = DEFAULT_CATALOG_PATH) -> None` — pretty JSON (indent=2), creates parent dir.
  - `new_asset_id() -> str` — `"asset-" + secrets.token_hex(3)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_funnel_catalog.py
from pathlib import Path

from lib import funnel_catalog as fc


def test_load_missing_catalog_returns_empty(tmp_path):
    assert fc.load_catalog(tmp_path / "nope.json") == []


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "sub" / "content_catalog.json"
    assets = [{"id": "asset-abc123", "title": "X"}]
    fc.save_catalog(assets, path)
    assert path.exists()
    assert fc.load_catalog(path) == assets


def test_new_asset_id_shape():
    aid = fc.new_asset_id()
    assert aid.startswith("asset-")
    assert len(aid) == len("asset-") + 6
    assert fc.new_asset_id() != fc.new_asset_id()


def test_vocabularies_present():
    assert fc.STAGES == ["TOFU", "MOFU", "BOFU"]
    assert fc.STAGE_SUBSTAGE["BOFU"] == ["evaluation", "decision"]
    assert "interactive_tool" in fc.TYPES
    assert fc.TYPE_STAGE_HINT["interactive_tool"] is None
    assert fc.TYPE_STAGE_HINT["blog"] == "TOFU"
    assert set(fc.ICPS) == {
        "sports_performance", "crossfit", "pt_studio", "hybrid_clinic_gym", "boutique",
    }
    assert fc.PRODUCTS == ["os", "strength", "both"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_funnel_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.funnel_catalog'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/funnel_catalog.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_funnel_catalog.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Create the empty catalog scaffold and wire git**

Create `data/funnel/content_catalog.json` with exactly:

```json
[]
```

Append to `.gitignore` (after the existing `!data/...` allow-list block, e.g. after line 51):

```
!data/funnel/
!data/funnel/**
```

- [ ] **Step 6: Verify the catalog file is tracked, not ignored**

Run: `git check-ignore data/funnel/content_catalog.json; echo "exit=$?"`
Expected: no path printed and `exit=1` (git check-ignore exits 1 when the path is NOT ignored — i.e. it will be tracked).

- [ ] **Step 7: Commit**

```bash
git add lib/funnel_catalog.py tests/test_funnel_catalog.py .gitignore data/funnel/content_catalog.json
git commit -m "feat(funnel): catalog storage, vocabularies, git wiring"
```

---

### Task 2: Asset validation and mistag warning

**Files:**
- Modify: `lib/funnel_catalog.py`
- Test: `tests/test_funnel_catalog.py`

**Interfaces:**
- Consumes: vocabulary constants and `STAGE_SUBSTAGE` from Task 1.
- Produces:
  - `validate_asset(asset: dict) -> list[str]` — list of human-readable error strings; empty means valid. Required fields: `title, type, stage, sub_stage, product, icp, status, source`. `sub_stage` must be listed under `stage` in `STAGE_SUBSTAGE`. `icp` must be a non-empty list of known slugs. `publish_date`/`added_at`, if present, must be ISO dates.
  - `stage_type_warning(asset: dict) -> str | None` — a warning string if the type's typical stage differs from the asset's stage; `None` otherwise (including stage-flexible types).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_funnel_catalog.py

def _valid_asset(**overrides):
    base = {
        "title": "CrossFit ROI calculator",
        "type": "roi_calculator",
        "stage": "BOFU",
        "sub_stage": "evaluation",
        "product": "os",
        "icp": ["crossfit"],
        "status": "planned",
        "source": "campaign_audit",
    }
    base.update(overrides)
    return base


def test_validate_accepts_good_asset():
    assert fc.validate_asset(_valid_asset()) == []


def test_validate_flags_unknown_type():
    errs = fc.validate_asset(_valid_asset(type="tiktok_dance"))
    assert any("type" in e for e in errs)


def test_validate_flags_substage_stage_mismatch():
    errs = fc.validate_asset(_valid_asset(stage="TOFU", sub_stage="evaluation"))
    assert any("sub_stage" in e for e in errs)


def test_validate_flags_unknown_icp_and_empty_icp():
    assert any("icp" in e for e in fc.validate_asset(_valid_asset(icp=["yoga_studio"])))
    assert any("icp" in e for e in fc.validate_asset(_valid_asset(icp=[])))


def test_validate_flags_missing_required_field():
    a = _valid_asset()
    del a["title"]
    assert any("title" in e for e in fc.validate_asset(a))


def test_validate_flags_bad_publish_date():
    assert any("publish_date" in e for e in fc.validate_asset(_valid_asset(publish_date="05/14/2026")))


def test_stage_type_warning_fires_on_odd_combo():
    w = fc.stage_type_warning(_valid_asset(type="blog", stage="BOFU", sub_stage="decision"))
    assert w is not None and "blog" in w


def test_stage_type_warning_silent_on_expected_and_flexible():
    assert fc.stage_type_warning(_valid_asset(type="roi_calculator", stage="BOFU")) is None
    assert fc.stage_type_warning(
        _valid_asset(type="interactive_tool", stage="TOFU", sub_stage="awareness")
    ) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_funnel_catalog.py -k "validate or warning" -v`
Expected: FAIL — `AttributeError: module 'lib.funnel_catalog' has no attribute 'validate_asset'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to lib/funnel_catalog.py

_REQUIRED = ("title", "type", "stage", "sub_stage", "product", "icp", "status", "source")


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_funnel_catalog.py -v`
Expected: PASS (all validate/warning tests green)

- [ ] **Step 5: Commit**

```bash
git add lib/funnel_catalog.py tests/test_funnel_catalog.py
git commit -m "feat(funnel): asset validation and mistag warning"
```

---

### Task 3: Duplicate detection and theme-reuse nudges

**Files:**
- Modify: `lib/funnel_catalog.py`
- Test: `tests/test_funnel_catalog.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `_normalize(text: str) -> str` — lowercase, trimmed, internal whitespace collapsed to single spaces.
  - `find_duplicates(asset: dict, catalog: list[dict]) -> list[dict]` — catalog entries whose normalized `title` matches the candidate's, or whose non-empty `url` matches.
  - `similar_themes(theme: str, catalog: list[dict]) -> list[str]` — distinct existing themes whose normalized form equals the candidate's or where one normalized form contains the other (substring), for a reuse nudge. Excludes exact-normalized-equal-and-identical duplicates of the input casing only by de-duping the returned list.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_funnel_catalog.py

def test_normalize_collapses_case_and_space():
    assert fc._normalize("  Member   Retention ") == "member retention"


def test_find_duplicates_by_title_and_url():
    catalog = [
        _valid_asset(title="Member Retention Guide", url="https://a.co/x"),
        _valid_asset(title="Other"),
    ]
    by_title = fc.find_duplicates(_valid_asset(title="member  retention guide"), catalog)
    assert len(by_title) == 1
    by_url = fc.find_duplicates(_valid_asset(title="Totally New", url="https://a.co/x"), catalog)
    assert len(by_url) == 1
    assert fc.find_duplicates(_valid_asset(title="Nothing Alike"), catalog) == []


def test_similar_themes_matches_fragments():
    catalog = [
        _valid_asset(theme="member retention"),
        _valid_asset(theme="pricing transparency"),
    ]
    hits = fc.similar_themes("retention", catalog)
    assert "member retention" in hits
    assert "pricing transparency" not in hits
    assert fc.similar_themes("brand awareness", catalog) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_funnel_catalog.py -k "normalize or duplicates or similar" -v`
Expected: FAIL — `AttributeError: ... has no attribute '_normalize'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to lib/funnel_catalog.py


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_funnel_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lib/funnel_catalog.py tests/test_funnel_catalog.py
git commit -m "feat(funnel): duplicate detection and theme-reuse nudges"
```

---

### Task 4: `add_asset` and dispersion aggregation

**Files:**
- Modify: `lib/funnel_catalog.py`
- Test: `tests/test_funnel_catalog.py`

**Interfaces:**
- Consumes: `validate_asset`, `new_asset_id` (Tasks 1–2).
- Produces:
  - `add_asset(asset: dict, catalog: list[dict], today: str | None = None) -> dict` — validates (raises `ValueError` with joined errors if invalid), returns a copy with `id` and `added_at` filled if missing (`today` defaults to `date.today().isoformat()`), and appends that copy to `catalog` in place. Does NOT write to disk — the caller loads/saves.
  - `dispersion(catalog: list[dict]) -> dict` — aggregate counts. Keys: `total`, `by_stage`, `by_type`, `by_icp` (list-flattened), `by_theme`, `by_product`, `by_status`, and `by_stage_status` (nested `{stage: {status: n}}` so "planned vs live" is visible per stage). Each breakdown is a plain `dict[str, int]` sorted by descending count.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_funnel_catalog.py
import pytest


def test_add_asset_fills_id_and_date_and_appends():
    catalog = []
    stored = fc.add_asset(_valid_asset(), catalog, today="2026-08-26")
    assert stored["id"].startswith("asset-")
    assert stored["added_at"] == "2026-08-26"
    assert catalog == [stored]


def test_add_asset_preserves_existing_id_and_date():
    stored = fc.add_asset(
        _valid_asset(id="asset-fixed1", added_at="2026-01-01"), [], today="2026-08-26"
    )
    assert stored["id"] == "asset-fixed1"
    assert stored["added_at"] == "2026-01-01"


def test_add_asset_raises_on_invalid():
    with pytest.raises(ValueError):
        fc.add_asset(_valid_asset(type="bad_type"), [])


def test_dispersion_counts_axes():
    catalog = [
        _valid_asset(stage="TOFU", sub_stage="awareness", type="blog",
                     icp=["crossfit", "sports_performance"], theme="retention",
                     status="live", product="os"),
        _valid_asset(stage="TOFU", sub_stage="awareness", type="blog",
                     icp=["crossfit"], theme="retention", status="planned", product="os"),
        _valid_asset(stage="MOFU", sub_stage="consideration", type="webinar",
                     icp=["pt_studio"], theme="onboarding", status="planned", product="both"),
    ]
    d = fc.dispersion(catalog)
    assert d["total"] == 3
    assert d["by_stage"] == {"TOFU": 2, "MOFU": 1}
    assert d["by_type"]["blog"] == 2
    assert d["by_icp"]["crossfit"] == 2
    assert d["by_theme"]["retention"] == 2
    assert d["by_product"]["os"] == 2
    assert d["by_stage_status"]["TOFU"] == {"live": 1, "planned": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_funnel_catalog.py -k "add_asset or dispersion" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'add_asset'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to lib/funnel_catalog.py


def add_asset(asset: dict, catalog: list[dict], today: str | None = None) -> dict:
    """Validate `asset`, fill id/added_at if absent, append to `catalog`, return it.

    Raises ValueError if the asset fails validation. Does not persist — the
    caller is responsible for save_catalog().
    """
    errors = validate_asset(asset)
    if errors:
        raise ValueError("invalid asset: " + "; ".join(errors))
    stored = dict(asset)
    stored.setdefault("id", new_asset_id())
    stored.setdefault("added_at", today or date.today().isoformat())
    catalog.append(stored)
    return stored


def _counted(pairs) -> dict[str, int]:
    """A count dict sorted by descending count, then key."""
    counts = Counter(pairs)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def dispersion(catalog: list[dict]) -> dict:
    """Aggregate the catalog across every axis the dispersion report renders."""
    by_stage_status: dict[str, Counter] = {}
    for a in catalog:
        stage = a.get("stage", "?")
        by_stage_status.setdefault(stage, Counter())[a.get("status", "?")] += 1

    return {
        "total": len(catalog),
        "by_stage": _counted(a.get("stage", "?") for a in catalog),
        "by_type": _counted(a.get("type", "?") for a in catalog),
        "by_icp": _counted(slug for a in catalog for slug in a.get("icp", [])),
        "by_theme": _counted(a["theme"] for a in catalog if a.get("theme")),
        "by_product": _counted(a.get("product", "?") for a in catalog),
        "by_status": _counted(a.get("status", "?") for a in catalog),
        "by_stage_status": {
            stage: dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))
            for stage, c in by_stage_status.items()
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_funnel_catalog.py -v`
Expected: PASS (all tests in the file green)

- [ ] **Step 5: Commit**

```bash
git add lib/funnel_catalog.py tests/test_funnel_catalog.py
git commit -m "feat(funnel): add_asset and dispersion aggregation"
```

---

### Task 5: The `funnel-audit` skill (four-mode router + grounding)

**Files:**
- Create: `.claude/skills/funnel-audit/SKILL.md`

**Interfaces:**
- Consumes: the full public API of `lib/funnel_catalog.py` (Tasks 1–4).
- Produces: a skill the model follows. No Python export; verified by frontmatter validity and a manual dry-run gate (Task 6).

This is a prose deliverable — no TDD cycle. The steps write the file and verify it loads.

- [ ] **Step 1: Write the skill file**

Create `.claude/skills/funnel-audit/SKILL.md` with exactly this content:

````markdown
---
name: funnel-audit
description: >
  Audits and shapes the TeamBuildr OS marketing funnel. Maintains a catalog of
  marketing assets tagged by funnel stage (TOFU/MOFU/BOFU), and runs four modes:
  seed the catalog from a strategy doc, audit a campaign concept for funnel-stage
  coverage, report content dispersion across stages, and generate grounded MOFU
  ideas. Use when Trent says "audit this campaign", "where are we thin in the
  funnel", "give me MOFU ideas", "log these assets", "seed the funnel catalog",
  or pastes a marketing strategy/campaign document and wants funnel analysis.
  Grounded in Avoma calls, the JTBD positioning snapshot, market-intel, and the
  pipeline cache. This is a content-classification and advisory tool, NOT a
  performance-measurement one — performance analysis is deferred until HubSpot
  can be connected.
---

# Funnel Audit

This skill maintains a catalog of TeamBuildr OS marketing assets and reasons
over it to shore up the middle of the funnel. TeamBuildr's funnel shape:
**TOFU = Awareness** (abundant), **MOFU = Consideration** (the structural gap —
the only stretch that should be content-carried but currently isn't), and
**BOFU = Evaluation + Decision** (mostly a salesperson + the platform, with some
sales-enablement content). Do not report toward a 33/33/33 balance — MOFU
thinness is the point.

## The catalog

The single source of truth is `data/funnel/content_catalog.json`, owned by the
deterministic helper `lib/funnel_catalog.py`. **Never hand-edit the JSON or
re-implement its logic** — call the helper. Read it in a Python session:

```python
from pathlib import Path
from lib import funnel_catalog as fc

catalog = fc.load_catalog()          # list[dict], [] if empty
# ... classify / mutate via fc.add_asset(asset, catalog, today="YYYY-MM-DD") ...
fc.save_catalog(catalog)             # persists to data/funnel/content_catalog.json
```

Vocabularies live in the helper: `fc.STAGES`, `fc.SUB_STAGES`,
`fc.STAGE_SUBSTAGE`, `fc.TYPES` (+ `fc.TYPE_STAGE_HINT`), `fc.ICPS`,
`fc.PRODUCTS`, `fc.STATUSES`, `fc.SOURCES`. Every asset written MUST pass
`fc.validate_asset` (=[] errors). Record shape:

```
id, title, type, stage, sub_stage, product(default "os"), theme,
icp[list], status, publish_date, url, source, campaign, added_at, notes
```

**Before writing any asset:** run `fc.stage_type_warning` (surface odd
stage/type combos to Trent, don't block), `fc.find_duplicates` (ask before
creating a near-duplicate), and `fc.similar_themes` (offer an existing theme so
"retention" / "member retention" don't fragment). Generated ideas are written
`status="planned"`, `source="campaign_audit"` (or `"manual"`) — never `"live"`.

**After any catalog write**, tell Trent to commit + push (origin/main is a live
datastore; rebase before push):

```bash
git add data/funnel/content_catalog.json && git commit -m "data(funnel): update content catalog"
git pull --rebase origin main && git push origin main
```

## Grounding sources (read automatically for Modes 2 and 4)

Every audit/ideation output MUST begin with a **"Sources pulled"** block: which
calls were scanned (with date range), which deals were referenced, and the
unique-prospect counts behind each claim. If a source can't be reached, say so
in that block — never silently omit it.

1. **Avoma transcripts — the MOFU goldmine.** Scan analyzed call data for
   recurring consideration-stage questions/objections and count how many
   *unique* prospects raised each. Route by shape (per project convention):
   enumeration/date/"all"/"count" → `query-avoma` skill (live REST); content /
   patterns / "what do prospects ask about X" → the `avoma-transcripts` MCP
   `search_transcripts`. Attribute mentions to reps in `config.json` →
   `avoma.sales_rep_emails`. A question 6 prospects asked unprompted is a MOFU
   brief writing itself.
2. **JTBD + positioning snapshot — the guardrail layer.**
   `docs/teambuildr-jtbd-product-knowledge-snapshot.md` tags claims
   `[PROVABLE] / [POSITIONING] / [INTERNAL] / [GUARDRAIL]`. Check every generated
   idea against it. If an idea leans on a non-`[PROVABLE]` claim or brushes a
   guardrail (attacking "two invoices / two products", framing CRM/marketing as
   a gap, claiming published price vs. PushPress/Wodify/Walla), **keep the idea
   but attach a visible `⚠ guardrail:` note** naming the rule and why — do NOT
   suppress it. Cite which `[PROVABLE]` claims back each brief.
3. **market-intel competitor data** — read `market-intel/data/competitors/*.md`,
   `market-intel/data/trends/`, `market-intel/data/features/` so comparison
   content is current and steers around themes competitors already own. Reach
   for live web search only to fill a specific gap.
4. **Pipeline cache** — `data/pipeline_cache.json`. **Check `fetched_at`
   freshness first**; if older than `config.json` → `pipeline.cache_stale_warn_days`
   (7) days, say so and offer the `sync-pipeline-cache` skill before trusting it.
   Late-stage statuses are in `pipeline.late_stage_statuses`. Prioritize MOFU/BOFU
   ideas for the ICP segment with deals actively stalling in consideration now.

## Mode routing

Detect the mode from what Trent provides:

### Mode 1 · Seed
Trigger: Trent pastes a YTD strategy / initiatives doc, or "seed the catalog".
1. Extract each asset/initiative from the doc.
2. Classify each into `stage / sub_stage / type / product / icp / theme`,
   `status` (usually `live` for existing assets), `source="seed"`, and
   `publish_date` if the doc gives one.
3. Present ALL proposed rows as a table for Trent to correct BEFORE writing.
   Run `stage_type_warning` + `similar_themes` per row and show the flags.
4. On approval, `add_asset` each into the loaded catalog, `save_catalog`, then
   give the commit/push reminder.

### Mode 2 · Campaign audit (core loop)
Trigger: Trent pastes a campaign concept/outline, or "audit this campaign".
Read grounding sources 1–4 first; open with the Sources-pulled block. Then:
1. Map each *intended* asset in the campaign to a funnel stage.
2. Cross-reference the existing catalog — covered vs. net-new (only `live`/`draft`
   count as covered; `planned` is intent, not coverage).
3. Flag coverage gaps against the campaign's own goal, emphasizing the **MOFU
   bridge**: does Awareness content hand off to a Consideration asset, or
   dead-end before the salesperson?
4. Generate specific gap-filling assets: title, format (`type`), stage, the
   prospect pain it answers (with unique-prospect count), supporting
   `[PROVABLE]` claims, and any `⚠ guardrail:` flag.
5. Offer to log the campaign's assets to the catalog (`status="planned"`,
   `source="campaign_audit"`, `campaign=<name>`), then the commit/push reminder.

### Mode 3 · Dispersion report
Trigger: "where are we thin", "show funnel dispersion", "what's our balance".
1. `d = fc.dispersion(fc.load_catalog())`.
2. If `d["total"]` is small (< ~10), state plainly the catalog is sparse and
   conclusions are weak until seeded — no false confidence.
3. Render the stage split and the secondary axes (`by_type`, `by_icp`,
   `by_theme`, `by_product`, `by_stage_status`). Frame narratively around the
   MOFU bridge, not equal buckets. Call out theme-continuity gaps (a theme loud
   at TOFU that vanishes by MOFU) using `by_theme` cross-referenced with stage.

### Mode 4 · MOFU ideation
Trigger: "give me MOFU ideas", "consideration-stage content".
Read grounding sources 1, 2, 4; open with the Sources-pulled block. Generate
Consideration-stage briefs anchored to (a) real gaps from the catalog and (b)
real prospect questions from Avoma, each with supporting `[PROVABLE]` claims and
any `⚠ guardrail:` flag. Offer to log accepted ideas (`status="planned"`).

## Out of scope (deferred)
- Performance / "what's lagging" — blocked on HubSpot; the catalog's `sub_stage`
  + `url` are built ready for it.
- Auto-population from HubSpot, passive nudges/dashboards, finished-copy drafting.
````

- [ ] **Step 2: Verify the frontmatter parses**

Run:
```bash
python3 - <<'PY'
import re, pathlib
t = pathlib.Path(".claude/skills/funnel-audit/SKILL.md").read_text()
m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
assert m, "no YAML frontmatter block found"
body = m.group(1)
assert "name: funnel-audit" in body, "name missing"
assert "description:" in body, "description missing"
print("frontmatter OK; body chars:", len(t))
PY
```
Expected: prints `frontmatter OK; body chars: <n>` with no assertion error.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/funnel-audit/SKILL.md
git commit -m "feat(funnel): funnel-audit skill with four-mode router and grounding"
```

---

### Task 6: Seed dry-run acceptance gate

**Files:** none created — this is the end-to-end validation the spec's success criteria require.

**Interfaces:**
- Consumes: everything above + Trent's real YTD strategy doc.

No TDD cycle — this is a manual acceptance checklist run WITH Trent.

- [ ] **Step 1: Confirm the test suite is green**

Run: `pytest tests/test_funnel_catalog.py -v`
Expected: PASS (all tests).

- [ ] **Step 2: Dry-run Mode 1 against the real YTD doc**

Ask Trent for the YTD strategy/initiatives doc. Invoke the skill (Mode 1) and
produce the proposed classification table — but STOP before writing. Present the
table for Trent's review.

- [ ] **Step 3: Acceptance check (Trent confirms)**

Confirm with Trent that:
- Stage / type / ICP / product tags are right after minimal correction.
- `stage_type_warning` fired only on genuinely odd rows.
- No obvious asset from the doc was dropped.

If tags are systematically off, note the pattern and adjust the Mode 1
classification guidance in `SKILL.md`, then re-run Step 2.

- [ ] **Step 4: Write the approved seed and verify persistence**

On Trent's approval, let the skill write the catalog, then verify:

Run:
```bash
python3 -c "from lib import funnel_catalog as fc; c=fc.load_catalog(); print(len(c),'assets'); print(fc.dispersion(c)['by_stage'])"
```
Expected: a non-zero asset count and a stage breakdown that matches the doc.

- [ ] **Step 5: Commit the seeded catalog**

```bash
git add data/funnel/content_catalog.json
git commit -m "data(funnel): seed content catalog from YTD strategy doc"
git pull --rebase origin main && git push origin main
```

---

## Self-Review

**Spec coverage:**
- Catalog spine + schema + vocabularies → Tasks 1–2. ✓
- Byproduct-capture (`planned`/`campaign_audit`, log-on-audit) → Tasks 4–5. ✓
- Four modes → Task 5. ✓
- Grounding sources + "Sources pulled" block → Task 5. ✓
- Guardrail flags-not-suppresses → Task 5 (Global Constraints + source 2). ✓
- Dispersion framed against MOFU (not 33/33/33) → Tasks 4 (aggregation) + 5 (framing). ✓
- Error handling (empty catalog, stale pipeline, mistag warn, dedupe, theme fragmentation, source-unreachable, push discipline) → Tasks 2–5. ✓
- Git wiring (`.gitignore` allow-list, local-only, commit/push reminder) → Tasks 1, 5. ✓
- HubSpot-readiness (deferred, `sub_stage`/`url` ready) → schema (Task 1) + Task 5 out-of-scope. ✓
- Success criteria (seed classification agreed, catalog grows without homework) → Task 6. ✓

**Placeholder scan:** No TBD/TODO/"handle appropriately" — all code and commands are concrete. ✓

**Type consistency:** `load_catalog`/`save_catalog`/`new_asset_id`/`validate_asset`/`stage_type_warning`/`find_duplicates`/`similar_themes`/`add_asset`/`dispersion` and all constant names are used identically across Tasks 1–6 and the SKILL.md examples. ✓
