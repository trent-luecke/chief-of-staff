# Registry UI — People Resolution Interface

**Date:** 2026-05-26
**Status:** Approved
**Approach:** Single self-contained HTML file (no build step, no server, no dependencies)

---

## Goal

A static HTML file in `tools/registry_ui.html` that serves as the visual workspace for people resolution. When the nightly job flags unresolved entities, Telegram sends a short nudge. Open the HTML file in Chrome, grant folder access once, work through resolutions visually, and the UI writes a decisions file. A Claude Code skill reads that file, applies mutations to `people_registry.json`, and commits.

---

## Deliverables

| Artifact | Description |
|---|---|
| `tools/registry_ui.html` | Single self-contained HTML file. Inline CSS + JS (ES module style). No build. Open in Chrome, grant folder access once per session. |
| `data/people_resolution_decisions.json` | Written by the UI. Read and deleted by the skill. Ephemeral handoff file — not a persistent store. |
| `.claude/skills/reconcile-people.md` | Project-scoped Claude Code skill. Reads decisions, mutates registry, commits and pushes. |
| `scripts/resolve_observations.py` | Single change: simplify `_build_notification()` to short-form message. |

---

## Interaction Flow

1. Nightly resolution job finds unresolved entities
2. Telegram sends: *"5 unresolved entities from tonight's run. Open your people tracker HTML artifact to reconcile new items."*
3. Open `tools/registry_ui.html` directly from the repo in Chrome
4. Browser prompts for folder access to the repo root — grant once per session
5. UI reads `people_unresolved_state.json`, `people_registry.json`, and `observations.jsonl` (optional)
6. Work through each unresolved entity — confirm, assign, create, or skip
7. Click "Save Decisions" — UI writes `data/people_resolution_decisions.json`
8. Switch to Claude Code and say: *"reconcile pending people resolutions"*
9. Skill reads decisions file, mutates `people_registry.json`, commits and pushes

---

## File: `tools/registry_ui.html`

Single self-contained file. No build step. Requires Chrome or Edge (File System Access API). On load, detect browser support and show a hard block with clear message if unsupported: *"This tool requires Chrome or Edge."*

### File System Access

```javascript
const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
```

All reads/writes use this handle. Helper navigates nested directories:

```javascript
async function getFileHandle(dirHandle, filePath) {
  const parts = filePath.split('/');
  let current = dirHandle;
  for (const part of parts.slice(0, -1)) {
    current = await current.getDirectoryHandle(part, { create: false });
  }
  return await current.getFileHandle(parts[parts.length - 1], { create: true });
}
```

### Data Layer

On load, read four sources:

| File | Role | Handling if missing |
|---|---|---|
| `data/people_unresolved_state.json` | Primary entity list (index, entity, type, candidate_id, candidate_name, confidence) | Show "No pending resolutions." empty state |
| `data/people_unresolved.json` | Enrichment (source, added date, email) — joined on `entity` string | Degrade to "unknown" for source/date fields |
| `data/people_registry.json` | Registry for Assign search and Registry Browser view | Required — show error if missing |
| `data/memory/observations.jsonl` | Observation snippets (optional enrichment) | Silent degrade — isolated try/catch, show "no observations on file" inline |

**Join logic:** `people_unresolved_state.json` defines the ordered entity list for the current batch. Cross-reference each entity against `people_unresolved.json` by matching the `entity` string to pull `source`, `added` (first-seen date), and `email`. If an entity appears in the state file but not in the unresolved file, render the card anyway with source/date shown as "unknown".

**Before coding the join:** Read the actual field names from the live `people_unresolved.json` file structure — don't assume field names from the spec description.

**Observations loading:** Read defensively — skip malformed lines silently. For Pending Resolutions view, only load observations matching `entity` string or `primary_person_id` of candidate. For Recent Observations view, limit to last 200 lines. Wrap the entire observations read in its own isolated try/catch — a missing or unreadable observations file must not affect registry reads or decision writes.

### Three Views

**View 1 — Pending Resolutions (default)**

One card per entity. Each card shows:
- Entity string (large, monospace)
- Source badge + first-seen date (from join; "unknown" if missing)
- Observation snippet (from `observations.jsonl`; "no observations on file" in muted text if absent)
- If candidate exists: candidate name, type badge, confidence % — from registry
- Four action buttons: **Confirm** (disabled if no candidate) / **Assign to…** / **New Person** / **Skip**

**Confirm** — one click, marks resolved.

**Assign to…** — inline typeahead filtering registry canonical names + aliases. Click to select.

**New Person** — inline form expands: canonical name (required), email (optional), type selector (lead / customer / partner / internal / unknown). Submit collapses form and marks card resolved.

**Skip** — inline confirmation ("Mark as skip? This adds it to the permanent skiplist.") with Confirm/Cancel before committing.

Progress indicator at top: "3 of 5 resolved" — live-updating as cards are resolved.

**Save Decisions** button (sticky bottom): disabled until ≥1 decision. Writes `data/people_resolution_decisions.json`. Shows brief "Saved." confirmation state. **Session merging:** on load, read any existing decisions file and pre-populate state — later decision for the same entity wins.

---

**View 2 — Registry Browser**

Tab at top. Searchable list: canonical name, type badge (color-coded), last seen date, alias count. Click any person to expand: full alias list, email, pipeline record (text), people file path, recent observations from `observations.jsonl` filtered by `primary_person_id`. Degrades gracefully if observations file is absent.

---

**View 3 — Recent Observations**

Tab at top. Last 200 lines of `observations.jsonl`, grouped by `primary_person_id` where set. Unkeyed observations in a separate "Unattributed" section at bottom. Filter by person name or observation type. Full silent degradation if file is absent — show "No observations file found."

---

### Design

Internal operational tool — utilitarian, dense, fast.

- Dark theme. Near-black background, tight typography, high contrast
- Monospace font for entity strings and IDs; clean sans-serif for everything else
- Color-coded type badges: lead (blue), customer (green), partner (amber), internal (gray), unknown (red)
- Cards with clear visual separation — developer tool aesthetic, not SaaS product
- No animations except subtle fade-in on card load and brief success flash on save

---

## File: `data/people_resolution_decisions.json`

Written by UI on "Save Decisions". Read and deleted by the reconcile-people skill.

```json
{
  "decided_at": "2026-05-26T14:30:00",
  "source_message_id": "98234",
  "decisions": [
    {"index": 1, "entity": "mike-w-apex", "action": "confirm", "target_id": "mike-woodby"},
    {"index": 2, "entity": "tzach1968@gmail.com", "action": "new", "canonical_name": "Tzach Feinsilver", "email": "tzach1968@gmail.com", "type": "unknown"},
    {"index": 3, "entity": "#support-tickets", "action": "skip"},
    {"index": 4, "entity": "james-apex-holland", "action": "assign", "target_id": "mike-woodby"}
  ]
}
```

`source_message_id` sourced from `people_unresolved_state.json` → `telegram_message_id`. Set to `null` if not present.

**Actions:**
- `confirm` — accept fuzzy match candidate; requires `target_id`
- `assign` — alias to explicit person; requires `target_id`
- `new` — create new stub; requires `canonical_name`, optional `email` and `type`
- `skip` — add to permanent skiplist

---

## Skill: `.claude/skills/reconcile-people.md`

Project-scoped. Triggered by: *"reconcile pending people resolutions"* or *"apply resolution decisions"*.

**Steps:**
1. Read `data/people_resolution_decisions.json` — verify exists and `decisions` is non-empty
2. Read `data/people_registry.json`
3. Apply mutations per decision (see below)
4. Write updated registry to `data/people_registry.json`
5. Delete `data/people_resolution_decisions.json`
6. Commit: `git add data/people_registry.json && git commit -m "chore: apply people resolution decisions (N resolved)"`
7. Push
8. Report summary

**Mutation logic:**

| Action | Mutation |
|---|---|
| `confirm` / `assign` | Add entity to target person's `aliases` if not present. Update `last_seen` to today. |
| `new` | Create stub: id = slugified canonical_name, aliases = [entity], created/last_seen = today. All other fields from decision or empty string. |
| `skip` | Append entity to top-level `skiplist` array (create if absent). |

**Safety invariants:**
- Never delete existing registry entries
- Never overwrite `canonical_name` on existing entries
- Never remove existing aliases — only append
- If `target_id` doesn't exist for confirm/assign: skip that decision, report the error, continue the run
- Read-modify-write in one operation — no partial writes

**Post-run report:** "Applied N decisions: X aliases added, Y new stubs created, Z skipped. Registry committed and pushed."

---

## Change: `scripts/resolve_observations.py`

Single change to `_build_notification()`. Remove the numbered entity list, fuzzy match percentages, and all reply-format instructions. New message:

```
{n} unresolved entities from tonight's run.

Open your people tracker HTML artifact to reconcile new items.
```

`_classify_entity()` and the `entities` list written to `people_unresolved_state.json` are unchanged — the UI reads them.

---

## What This Does Not Change

- `ask.py` reply handler — remains for backward compat
- `people_unresolved_state.json` — still written by nightly job, now consumed by UI
- `observations.jsonl` — read-only from UI, never written
- `people_registry.json` — written only by the skill, never directly by UI
- Daily brief pipeline — no changes
