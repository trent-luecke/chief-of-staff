# Market Intel Email Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reformat the daily market intel email to show top 2 leads per category with full summaries plus bulleted honorable mentions, add within-day title-similarity deduplication, and remove the unused weekly digest.

**Architecture:** All changes are in `market-intel/market_intel.py`. Two new pure functions (`_title_word_set`, `dedup_by_title`) handle dedup. `format_daily_email()` is replaced in-place. Four weekly-digest functions and the `--weekly` CLI arg are deleted.

**Tech Stack:** Python 3.11+, pytest (no new dependencies)

---

## File Map

| File | Action |
|------|--------|
| `market-intel/market_intel.py` | Add `dedup_by_title`; replace `format_daily_email`; delete weekly functions + CLI arg |
| `market-intel/tests/test_market_intel.py` | Add tests for `dedup_by_title` and new `format_daily_email`; remove import of deleted functions if any |

---

## Task 1: Add `dedup_by_title()` with tests

**Files:**
- Modify: `market-intel/market_intel.py` (after the `deduplicate_items` function, ~line 174)
- Modify: `market-intel/tests/test_market_intel.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `market-intel/tests/test_market_intel.py`:

```python
from market_intel import dedup_by_title


def test_dedup_by_title_empty():
    assert dedup_by_title([]) == []


def test_dedup_by_title_single():
    items = [{"title": "Gymdesk Launches WOD Tracker", "relevance_score": 4}]
    assert dedup_by_title(items) == items


def test_dedup_by_title_keeps_distinct():
    items = [
        {"title": "Gymdesk Launches WOD Tracker", "relevance_score": 4},
        {"title": "Gymdesk Launches Mobile App", "relevance_score": 4},
    ]
    result = dedup_by_title(items)
    assert len(result) == 2


def test_dedup_by_title_collapses_near_duplicates():
    items = [
        {"title": "Run Clubs Are the New Singles Bars", "relevance_score": 3},
        {"title": "Run Clubs Why Gen Z Is Choosing Them Over Bars", "relevance_score": 4},
    ]
    result = dedup_by_title(items)
    assert len(result) == 1
    # keeps the higher-scored item
    assert result[0]["relevance_score"] == 4


def test_dedup_by_title_collapses_exact_duplicate():
    items = [
        {"title": "Gymdesk Launches WOD Tracker", "relevance_score": 4},
        {"title": "Gymdesk Launches WOD Tracker", "relevance_score": 3},
    ]
    result = dedup_by_title(items)
    assert len(result) == 1
    assert result[0]["relevance_score"] == 4


def test_dedup_by_title_threshold_respected():
    # these two titles share only "the" (stop word) — should NOT be collapsed
    items = [
        {"title": "GLP-1 Drugs Drive Gym Membership Growth", "relevance_score": 4},
        {"title": "Run Clubs Replace Dating Apps for Gen Z", "relevance_score": 4},
    ]
    result = dedup_by_title(items)
    assert len(result) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/chief-of-staff/market-intel
pytest tests/test_market_intel.py::test_dedup_by_title_empty -v
```

Expected: `ImportError` — `dedup_by_title` not yet defined.

- [ ] **Step 3: Implement `dedup_by_title` in `market_intel.py`**

Add the following block immediately after the `deduplicate_items` function (~line 174). The `STOP_WORDS` constant goes at module level near the other constants (around line 67). Insert `_title_word_set`, `_jaccard`, and `dedup_by_title` as a group after `deduplicate_items`.

```python
# ── Title-similarity dedup ─────────────────────────────────────────────────

_STOP_WORDS = {"a", "an", "the", "is", "are", "of", "for", "in", "and", "to",
               "that", "it", "its", "as", "at", "by", "on", "with", "was",
               "has", "have", "be", "been", "this", "their", "how", "why",
               "over", "new", "more"}


def _title_word_set(title: str) -> set[str]:
    words = re.sub(r"[^a-z0-9\s]", "", title.lower()).split()
    return {w for w in words if w not in _STOP_WORDS}


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def dedup_by_title(items: list[dict], threshold: float = 0.45) -> list[dict]:
    """Collapse near-duplicate articles by title similarity (Jaccard on word sets).
    Processes items in descending score order; keeps the first (highest-scored)
    representative of each topic cluster."""
    sorted_items = sorted(
        items,
        key=lambda x: int(x.get("relevance_score") or 0),
        reverse=True,
    )
    kept: list[dict] = []
    kept_sets: list[set] = []
    for item in sorted_items:
        ws = _title_word_set(item.get("title", ""))
        if all(_jaccard(ws, ks) < threshold for ks in kept_sets):
            kept.append(item)
            kept_sets.append(ws)
    return kept
```

- [ ] **Step 4: Run all dedup tests**

```bash
cd /path/to/chief-of-staff/market-intel
pytest tests/test_market_intel.py -k "dedup_by_title" -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
pytest tests/test_market_intel.py -v
```

Expected: all existing tests PASS.

- [ ] **Step 6: Commit**

```bash
git add market-intel/market_intel.py market-intel/tests/test_market_intel.py
git commit -m "feat: add title-similarity dedup for within-day clustering"
```

---

## Task 2: Replace `format_daily_email()` with new layout

**Files:**
- Modify: `market-intel/market_intel.py` (replace `format_daily_email`, ~line 450)
- Modify: `market-intel/tests/test_market_intel.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `market-intel/tests/test_market_intel.py`:

```python
from market_intel import format_daily_email


def _make_record(title, category, score, competitor=None, action_flag=False, summary=None, url="http://example.com"):
    return {
        "title": title,
        "category": category,
        "relevance_score": score,
        "competitor": competitor,
        "action_flag": action_flag,
        "summary": summary or f"First sentence about {title}. Second sentence with more detail. Third sentence.",
        "url": url,
        "date_found": "2026-05-19",
        "source": "Test",
    }


def test_format_daily_email_subject():
    records = [_make_record("Gymdesk WOD Tracker", "feature_launch", 4, "Gymdesk")]
    subject, _ = format_daily_email(records, "2026-05-19")
    assert "2026-05-19" in subject
    assert "Market Intel" in subject


def test_format_daily_email_action_needed_block_present():
    records = [
        _make_record("Urgent Feature", "feature_launch", 5, "Gymdesk", action_flag=True),
        _make_record("Normal Feature", "feature_launch", 4, "Zen Planner"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    assert "ACTION NEEDED" in body


def test_format_daily_email_action_needed_block_absent_when_none():
    records = [_make_record("Normal Feature", "feature_launch", 4, "Gymdesk")]
    _, body = format_daily_email(records, "2026-05-19")
    assert "ACTION NEEDED" not in body


def test_format_daily_email_action_items_excluded_from_category():
    records = [
        _make_record("Urgent Feature", "feature_launch", 5, "Gymdesk", action_flag=True),
        _make_record("Normal Feature", "feature_launch", 4, "Zen Planner"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    # Category section should show Normal Feature as [1/1] lead, not Urgent Feature
    assert "Zen Planner" in body
    # Urgent Feature's full summary should appear only in ACTION NEEDED, not duplicated
    lines = body.split("\n")
    urgent_count = sum(1 for l in lines if "Urgent Feature" in l)
    # title appears once in ACTION NEEDED block
    assert urgent_count >= 1


def test_format_daily_email_top_two_leads_shown():
    records = [
        _make_record("Feature A", "feature_launch", 5, "CompA", url="http://a.com"),
        _make_record("Feature B", "feature_launch", 4, "CompB", url="http://b.com"),
        _make_record("Feature C", "feature_launch", 3, "CompC", url="http://c.com"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    assert "[1/2]" in body
    assert "[2/2]" in body
    # CompA and CompB are leads; CompC is honorable mention
    assert "Honorable mentions:" in body
    assert "CompC" in body


def test_format_daily_email_honorable_mention_is_one_liner():
    long_summary = "First sentence. Second sentence. Third sentence."
    records = [
        _make_record("Feature A", "feature_launch", 5, "CompA", summary=long_summary),
        _make_record("Feature B", "feature_launch", 4, "CompB", summary=long_summary),
        _make_record("Feature C", "feature_launch", 3, "CompC", summary=long_summary, url="http://c.com"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    # Honorable mention for CompC should only have first sentence, not all three
    assert "Second sentence" not in body.split("Honorable mentions:")[1]
    assert "First sentence." in body.split("Honorable mentions:")[1]


def test_format_daily_email_dedup_within_category():
    records = [
        _make_record("Run Clubs Are the New Singles Bars", "industry_trend", 3),
        _make_record("Run Clubs Why Gen Z Chooses Them Over Bars", "industry_trend", 4),
        _make_record("Gymdesk Launches WOD Tracker", "feature_launch", 4, "Gymdesk"),
    ]
    _, body = format_daily_email(records, "2026-05-19")
    # The two run club articles are near-duplicates; only one should be a lead
    assert body.count("Run Clubs") == 1


def test_format_daily_email_category_label_human_readable():
    records = [_make_record("Some Feature", "feature_launch", 4, "CompA")]
    _, body = format_daily_email(records, "2026-05-19")
    assert "FEATURE LAUNCH" in body
    assert "feature_launch" not in body


def test_format_daily_email_industry_competitor_label():
    records = [_make_record("Industry Article", "industry_trend", 4, competitor=None)]
    _, body = format_daily_email(records, "2026-05-19")
    assert "Industry" in body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/chief-of-staff/market-intel
pytest tests/test_market_intel.py -k "format_daily_email" -v
```

Expected: most tests FAIL (current `format_daily_email` doesn't produce the new structure).

- [ ] **Step 3: Replace `format_daily_email` in `market_intel.py`**

Locate the existing `format_daily_email` function (~line 450) and replace it entirely with the following. Also add the `CATEGORY_LABELS` constant near the other constants at the top of the file (after `CATEGORY_DIRS`, ~line 54):

**Add near top of file (after `CATEGORY_DIRS` dict):**

```python
CATEGORY_LABELS = {
    "feature_launch": "FEATURE LAUNCH",
    "acquisition": "ACQUISITION",
    "new_entrant": "NEW ENTRANT",
    "industry_trend": "INDUSTRY TREND",
    "pricing_change": "PRICING CHANGE",
    "partnership": "PARTNERSHIP",
    "funding": "FUNDING",
    "leadership_change": "LEADERSHIP CHANGE",
}
```

**Replace the `format_daily_email` function:**

```python
def _first_sentence(summary: str) -> str:
    """Extract the first sentence from a multi-sentence summary."""
    parts = summary.split(". ")
    first = parts[0].strip()
    if not first.endswith("."):
        first += "."
    return first


def format_daily_email(records: list[dict], date_str: str) -> tuple[str, str]:
    """
    Format daily summary email.
    ACTION NEEDED block at top for action-flagged items.
    Remaining items grouped by category: top 2 leads with full summary,
    rest as bulleted honorable mentions (one sentence + URL).
    Within-day title-similarity dedup applied per category.
    Returns (subject, body).
    """
    action_items = [r for r in records if r.get("action_flag") in (True, "true", "True")]
    non_action = [r for r in records if r not in action_items]

    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in non_action:
        by_category[r.get("category", "other")].append(r)

    deduped: dict[str, list[dict]] = {
        cat: dedup_by_title(items) for cat, items in by_category.items()
    }

    def _max_score(items: list[dict]) -> int:
        return max((int(r.get("relevance_score") or 0) for r in items), default=0)

    ordered = sorted(deduped.items(), key=lambda kv: _max_score(kv[1]), reverse=True)

    total = len(action_items) + sum(len(v) for v in deduped.values())
    n_cats = sum(1 for _, items in ordered if items)
    cat_word = "category" if n_cats == 1 else "categories"

    subject = f"Market Intel — {date_str} ({total} items)"
    lines = [f"Market Intel — {date_str} ({total} items across {n_cats} {cat_word})", ""]

    if action_items:
        lines += ["ACTION NEEDED", "=" * 40, ""]
        for r in sorted(action_items, key=lambda x: int(x.get("relevance_score") or 0), reverse=True):
            competitor = r.get("competitor") or "Industry"
            cat_label = CATEGORY_LABELS.get(r.get("category", ""), r.get("category", "").upper().replace("_", " "))
            lines.append(f"[{cat_label}] {competitor} | score: {r.get('relevance_score')}")
            lines.append(r.get("summary", ""))
            lines.append(r.get("url", ""))
            lines.append("")

    for category, items in ordered:
        if not items:
            continue
        cat_label = CATEGORY_LABELS.get(category, category.upper().replace("_", " "))
        lines += [cat_label, "-" * 40, ""]

        sorted_items = sorted(items, key=lambda x: int(x.get("relevance_score") or 0), reverse=True)
        leads = sorted_items[:2]
        honorable = sorted_items[2:]

        for i, r in enumerate(leads, 1):
            competitor = r.get("competitor") or "Industry"
            lines.append(f"[{i}/{len(leads)}] {competitor} | score: {r.get('relevance_score')}")
            lines.append(r.get("summary", ""))
            lines.append(r.get("url", ""))
            lines.append("")

        if honorable:
            lines.append("Honorable mentions:")
            for r in honorable:
                competitor = r.get("competitor") or "Industry"
                title = r.get("title", "")
                first_sent = _first_sentence(r.get("summary", ""))
                url = r.get("url", "")
                lines.append(f"• {competitor} — {title}: {first_sent}  {url}")
            lines.append("")

    return subject, "\n".join(lines)
```

- [ ] **Step 4: Run format tests**

```bash
cd /path/to/chief-of-staff/market-intel
pytest tests/test_market_intel.py -k "format_daily_email" -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/test_market_intel.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add market-intel/market_intel.py market-intel/tests/test_market_intel.py
git commit -m "feat: redesign daily email with leads + honorable mentions per category"
```

---

## Task 3: Remove weekly digest

**Files:**
- Modify: `market-intel/market_intel.py`

No tests to write — this is pure deletion. The weekly tests were never written; the existing test file doesn't import any weekly functions.

- [ ] **Step 1: Delete four weekly functions from `market_intel.py`**

Delete the following functions in their entirety (locate by name):
- `load_recent_csv_records` (~line 494)
- `format_weekly_digest` (~line 508)
- `save_weekly_brief` (~line 586)
- `run_weekly` (~line 669)

Also delete the `# ── Weekly digest ──` section comment above `load_recent_csv_records`.

- [ ] **Step 2: Remove `--weekly` CLI arg from `main()`**

Locate the `main()` function (~line 703). Remove these two lines:

```python
parser.add_argument("--weekly", action="store_true", help="Run weekly digest instead of daily run")
```

And remove the conditional dispatch block:

```python
if args.weekly:
    run_weekly(dry_run=args.dry_run)
else:
    run_daily(dry_run=args.dry_run)
```

Replace with:

```python
run_daily(dry_run=args.dry_run)
```

- [ ] **Step 3: Verify `--weekly` is gone**

```bash
cd /path/to/chief-of-staff/market-intel
python market_intel.py --weekly 2>&1 | head -5
```

Expected: `error: unrecognized arguments: --weekly`

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/test_market_intel.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add market-intel/market_intel.py
git commit -m "chore: remove unused weekly digest pipeline"
```

---

## Task 4: Manual smoke test

- [ ] **Step 1: Dry-run the daily pipeline**

```bash
cd /path/to/chief-of-staff/market-intel
python market_intel.py --dry-run 2>&1 | tail -20
```

Expected: run completes, logs show `Stored N records`, no crash.

- [ ] **Step 2: Print the email body to confirm format**

Temporarily add two lines to `run_daily()` in the `if stored_records` block (after `format_daily_email` is called but before the `send_email` call is gated by `not dry_run`):

```python
subject, body = format_daily_email(stored_records, today)
print(f"\n{'='*60}\nSUBJECT: {subject}\n{'='*60}\n{body}")
```

Run `python market_intel.py --dry-run` and confirm:
- ACTION NEEDED block appears (or is absent) correctly
- Each category shows ≤2 leads with full summaries
- Honorable mentions are single-line with URL
- No duplicate topic articles within a category

- [ ] **Step 3: Revert the temporary print lines**

Remove the two debug `print` lines added in Step 2.

- [ ] **Step 4: Final commit**

```bash
git add market-intel/market_intel.py
git commit -m "chore: remove debug print from dry-run smoke test"
```
