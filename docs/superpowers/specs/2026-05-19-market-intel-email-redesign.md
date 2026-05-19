# Market Intel Email Redesign

**Date:** 2026-05-19
**Scope:** `chief-of-staff/market-intel/market_intel.py`

## Problem

The daily market intel email is too long to process. The main causes:
1. Same-day duplication — multiple news outlets cover the same topic (e.g. run clubs) and each gets its own full-summary entry
2. Every article gets equal weight — no clear "this is the one to read" signal per category
3. The weekly digest is unused and adds maintenance surface

## Goals

- One email per day, scannable in under 2 minutes
- Top 1-2 most relevant stories per category get full treatment; everything else is a one-liner with a link
- Eliminate same-day topic duplication before formatting
- Remove the weekly digest entirely

## What's Not Changing

- Classification pipeline (Claude scoring, categories, action_flag)
- Cross-day dedup via `seen_urls.json`
- Storage (CSV log, per-category markdown files, competitor timelines)
- `--dry-run` flag
- Gmail SMTP delivery

---

## Design

### 1. Remove Weekly Digest

Delete the following from `market_intel.py`:
- `run_weekly()` function
- `format_weekly_digest()` function
- `save_weekly_brief()` function
- `load_recent_csv_records()` function
- `--weekly` CLI argument and its dispatch in `main()`

Keep: `briefs/` directory, `intel-log.csv` (historical record).

### 2. Within-Day Title Similarity Dedup

After classification, before formatting, collapse near-duplicate articles within each category.

**Algorithm:** Jaccard similarity on lowercased word sets.

```python
def title_word_set(title: str) -> set[str]:
    # lowercase, strip punctuation, split on whitespace
    # exclude stop words: "the", "a", "an", "is", "are", "of", "for", "in", "and", "to", "that"

def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0

def dedup_by_title(items: list[dict], threshold: float = 0.45) -> list[dict]:
    # greedy: iterate items sorted by score desc
    # for each item, check against already-kept items
    # if similarity >= threshold with any kept item, discard
    # otherwise keep
```

**Threshold:** 0.45. Calibrated against known duplicates:
- "Run Clubs Are the New Singles Bars" vs "Run Clubs: Why Gen Z Is Choosing Them Over Bars" → ~0.55 → collapsed ✓
- "Gymdesk Launches WOD Tracker" vs "Gymdesk Launches Mobile App" → ~0.25 → kept separate ✓

Dedup runs per-category after the full classification loop. Items already separated into categories before dedup, so cross-category collapse can't happen.

### 3. Reformatted Daily Email

Replace `format_daily_email()` with the new layout. Still plain text (no HTML).

**Structure:**

```
Market Intel — YYYY-MM-DD (N items across M categories)

ACTION NEEDED
========================================
[Full entries for action_flag=True items, sorted by score desc]

CATEGORY NAME
----------------------------------------
[1/2] Competitor | score: N
Full 2-3 sentence summary.
URL

[2/2] Competitor | score: N
Full 2-3 sentence summary.
URL

Honorable mentions:
• Competitor — Article Title: First sentence of summary.  URL
• Competitor — Article Title: First sentence of summary.  URL

NEXT CATEGORY NAME
----------------------------------------
...
```

**Rules:**
- `ACTION NEEDED` block: all action-flagged items with full summary, regardless of category. If none, block is omitted.
- Categories ordered by highest score among their leads (descending)
- Leads per category: top 2 by score (or 1 if only 1 article survives dedup in that category)
- Action-flagged items appear ONLY in the ACTION NEEDED block; they are excluded from their category section so they don't appear twice
- Honorable mentions: all remaining articles in the category after the top 2
- Honorable mention format: `• [Competitor or "Industry"] — [Title]: [first sentence of summary].  [URL]`
- First sentence extracted by splitting summary on `. ` and taking index 0, then re-appending the period
- Category header uses human-readable name: `feature_launch` → `FEATURE LAUNCH`, `industry_trend` → `INDUSTRY TREND`, etc.
- If zero articles survive after dedup and score filtering: no email sent, log a message

**Subject line:** `Market Intel — YYYY-MM-DD (N items)`

---

## Files Changed

| File | Change |
|------|--------|
| `market-intel/market_intel.py` | Remove weekly functions; add `dedup_by_title()`; replace `format_daily_email()` |

No new files. No config changes. No dependency additions.

---

## Testing

Manual dry-run after implementation:
1. `python market_intel.py --dry-run` — confirm no crash, log shows dedup counts
2. Inspect email body printed to stdout (add temporary print in dry-run path)
3. Verify action-flagged items appear in ACTION NEEDED block
4. Verify honorable mentions are one-liners with URL
5. Confirm `--weekly` flag is gone (argparse error if passed)
