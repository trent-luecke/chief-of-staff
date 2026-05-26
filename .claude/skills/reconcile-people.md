---
name: reconcile-people
description: Apply pending people resolution decisions to the registry and commit. Use when Trent says "reconcile pending people resolutions" or "apply resolution decisions".
---

## When to use

When `data/people_resolution_decisions.json` exists and has a non-empty `decisions` array.

## Steps

1. Read `data/people_resolution_decisions.json`. If file doesn't exist or `decisions` is empty, report "No pending decisions found." and stop.
2. Read `data/people_registry.json`
3. Apply mutations (see below) to the in-memory registry object
4. Write updated registry back to `data/people_registry.json`
5. Delete `data/people_resolution_decisions.json` from disk
6. Stage and commit:
   ```
   git add data/people_registry.json
   git commit -m "chore: apply people resolution decisions (N resolved)"
   ```
   (Replace N with actual count of decisions applied)
7. Push: `git push`
8. Report summary (see format below)

## Mutation logic per action

**`confirm` or `assign`** (both require `target_id`):
- Look up the person in `registry.people` where `id === target_id`
- If not found: skip this decision, add "Warning: target_id `<id>` not found" to report, continue
- If `decision.entity` is not already in `person.aliases`: append it
- Set `person.last_seen` to today's date as `YYYY-MM-DD`

**`new`** (requires `canonical_name`):
- Generate `id`: lowercase the canonical_name, replace spaces and non-alphanumeric chars with hyphens, collapse consecutive hyphens, strip leading/trailing hyphens
  - "Tzach Feinsilver" → "tzach-feinsilver"
  - "Summit Performance Institute" → "summit-performance-institute"
- If that id already exists in `registry.people`, append `-2`, incrementing until unique
- Append to `registry.people`:
  ```json
  {
    "id": "<generated>",
    "canonical_name": "<from decision.canonical_name>",
    "aliases": ["<decision.entity>"],
    "email": "<decision.email or empty string>",
    "type": "<decision.type or 'unknown'>",
    "pipeline_record": "",
    "people_file": "",
    "created": "<today YYYY-MM-DD>",
    "last_seen": "<today YYYY-MM-DD>"
  }
  ```

**`skip`**:
- Ensure `registry.skiplist` array exists at the top level of the registry object (create empty array if absent)
- Append `decision.entity` to `registry.skiplist` if not already present

## Safety invariants

- Never delete existing registry entries
- Never overwrite `canonical_name` on existing entries
- Never remove existing aliases — only append new ones
- Read-modify-write as one atomic operation (read full file → modify in memory → write full file)
- If `target_id` missing for confirm/assign: skip that decision and report warning, do not abort the run

## After completing

Report in this format:
```
Applied N decisions: X aliases added, Y new stubs created, Z skipped.
Registry committed and pushed.
```

Include any warnings (missing target_ids) after the summary line.
