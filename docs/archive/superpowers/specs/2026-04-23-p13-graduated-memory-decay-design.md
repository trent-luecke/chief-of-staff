# P13 — Graduated Memory Decay Design

**Date:** 2026-04-23
**Status:** Approved

---

## Problem

The memory system uses a binary 90-day TTL. A synthesized memory from 89 days ago carries the same weight as one from yesterday. Memories about closed deals, resolved issues, and people you no longer work with persist until they expire, polluting context with stale noise.

Reference: Donovan Li's system applies daily decay rates (0.02 recently-accessed, 0.05 normal, 0.08 abandoned, immune if pinned). Abandoned memories halve in relevance every ~9 days; this is the tier that matters most for a personal system at this scale.

---

## Approach

**Abandonment-only decay.** During synthesis, scan all existing memory files. Any file that hasn't had new observations written in more than `abandon_threshold_days` (default 60) gets its expiry shortened to `today + abandon_ttl_days` (default 14). Files that are pinned or already expiring within 14 days are left alone.

Read tracking (retriever writing `last_accessed` back to files) was considered and rejected — the 550-token budget already naturally deprioritizes old memories, and the abandonment tier is where the practical noise gain is.

---

## Changes

### `processors/memory_synthesizer.py`

**New function: `_apply_abandonment_decay(memory_dir, abandon_threshold_days, abandon_ttl_days)`**

- Scans all `*.md` files in `memory_dir`
- Reads `activity_last_seen` and `pinned` from frontmatter (`activity_last_seen` is already written by synthesis on every update — this is the first place it gets read)
- If `activity_last_seen < today - abandon_threshold_days` and not pinned:
  - Sets `expires = min(current_expires, today + abandon_ttl_days)`
  - Writes frontmatter-only update (content unchanged)
- Wraps each file in try/except, skips on any error

**Updated run sequence in `synthesize()`:**
```
_apply_abandonment_decay()   ← new, runs first
_archive_expired_files()     ← existing, unchanged
_load_recent_observations()  ← existing
Claude call                  ← existing
write updated memory files   ← existing, now preserves pinned/suppress
```

Abandonment runs before archiving so freshly-shortened files can be archived in the same pass.

**Bug fix: preserve `pinned` and `suppress` on synthesis write**

Currently `synthesize()` hardcodes `pinned=False` and `suppress=False` when writing updated files, silently unsetting any manually-set flags. Fix: read existing values from the file before writing and carry them forward.

**New params on `synthesize()`** (with defaults, backward-compatible):
- `abandon_threshold_days: int = 60`
- `abandon_ttl_days: int = 14`

### `config.json`

Add under existing `memory` block:
```json
"abandon_threshold_days": 60,
"abandon_ttl_days": 14
```

### `main.py`

Pass new config values through to `synthesize()` call.

---

## What doesn't change

- `memory_retriever.py` — stays read-only, no new write path
- Frontmatter schema — no new fields; `activity_last_seen` already exists
- `pinned` behavior — pinned memories are immune, same as today (and now correctly preserved)
- Token budget — 550 tokens, unchanged

---

## Error handling

`_apply_abandonment_decay()` wraps each file in try/except and skips on failure. A malformed file or missing frontmatter field never blocks the synthesis run — same pattern used throughout the synthesizer.

---

## When this matters

Only produces visible effects at 60+ days of operation. Before that, no memories are old enough to be flagged abandoned. This is intentionally a "set it and forget it" improvement — no tuning needed after deployment.
