# Plan 4 — Internal Meeting Prep Recipes (Today tab)

**Date:** 2026-08-04
**Status:** Design approved, pending spec review
**Depends on:** Plan 1 (identity + provisioning), Plan 2 (Today tab + `brief_today.json` generation) — both merged 2026-07-29.

## Problem

The Today tab (`processors/today_brief.py`) renders every meeting card with `prep: None` hardcoded at line 57. Plan 2 shipped this deliberately as a placeholder — the design doc states *"`prep` is always `null` in Plan 2 (Plans 3/4 populate it)."* As a result, recurring internal meetings the user has configured (e.g. the Luke 1:1) show **"No prep yet."** even though the underlying data — open threads, last-session notes, related projects — already exists in the data layer.

This is not a name-matching or classification bug. The meeting is present in `brief_today.json` under its real calendar title ("Luke / Trent"), correctly classified `internal`. The prep feature simply was never built.

## Goal

Populate `prep` on internal meeting cards in the Today tab using **per-meeting recipes**: each configured meeting declares which data blocks to gather, and an LLM synthesis step shapes them into a short prep brief. Gathering is deterministic and traceable; only the final shaping uses an LLM.

**This pass seeds exactly one recipe (Luke 1:1)** to validate end-to-end. The other six configured meetings remain recipe-less (and thus `prep: null`, unchanged) until their recipes are authored in a follow-up.

## Non-goals

- **External meeting prep** — Plan 3, out of scope. The block gathering here is internal-only.
- **"What moved" org-wide feed** — Plan 5, out of scope.
- Authoring recipes for all seven configured meetings — follow-up work.
- Changing the emailed-brief prep path (`processors/meeting_prep.py`, `processors/brief.py`). That legacy system is untouched.
- A Meetings-tab UI for editing recipes — recipes are hand-edited in `meeting_index.json`, consistent with how meeting configs are maintained today.

## Approach (A): new focused module

Add `processors/meeting_prep_recipe.py`. `today_brief._meeting_dict` calls it for internal meetings that resolve to a recipe. The legacy `processors/meeting_prep.py` (dept-heads / external branching for the emailed brief) is **not** reused or modified — this keeps the Today-tab path free of that coupling. Proven low-level helpers are reused directly:

- `lib.meetings.replay_local` / `render_for_prep` / `open_threads` / `last_session` — Meetings registry.
- `processors.meeting_memory.find_meeting_for_event` / `load_meeting_index` / `load_last_session_summary` — config matching + memory-file session log.
- `lib.identity` (`load_people`, `build_lookup`, `find_by_email`, `resolve`) — attendee → person_id resolution (Plan 1).

Rejected alternatives:
- **B — extend legacy `meeting_prep.py`:** reuses more code but drags dept-heads/external classification into the Today-tab path. Rejected for coupling.
- **C — precompute in a separate job:** decouples LLM latency but adds a moving part for 1–3 meetings/day. Rejected as overkill.

## Recipe schema (`data/meeting_index.json`)

Each meeting entry gains an optional `prep_recipe`:

```json
{
  "calendar_pattern": "luke / trent",
  "memory_file": "data/meeting_memory/luke_1on1.md",
  "name": "Luke 1:1",
  "prep_recipe": {
    "blocks": ["open_threads", "last_session", "project_next_actions", "pipeline_sales"],
    "instruction": "Focus on sales pipeline movement and any blockers Luke owns. Keep it to 4-5 bullets."
  }
}
```

- `blocks` — ordered subset of the catalog (below). Only listed blocks are gathered.
- `instruction` — optional per-meeting synthesis steer. Omitted → a default prompt runs.
- Entry with **no** `prep_recipe` → meeting renders `prep: null` (today's behavior, unchanged).

**Required code change:** `MeetingConfig` (`processors/meeting_memory.py:9`) is constructed via `MeetingConfig(**m)`; adding `prep_recipe` to the JSON will raise `TypeError` unless the dataclass gains `prep_recipe: Optional[dict] = None`. This field is additive and ignored by all existing consumers.

## Block catalog

Each block is a function `gather(ctx) -> str | None` returning a titled markdown chunk, or `None`/empty when its source has nothing (the block is then silently dropped — **never** a fabricated or empty-headed section). `ctx` carries the calendar event, matched `MeetingConfig`, `config`, and `storage`.

| Block | Source | Gather behavior |
|---|---|---|
| `open_threads` | Meetings registry: `replay_local(data_dir)[meeting_id]` → `render_for_prep`'s open-threads portion | Matched via `find_meeting_for_event`; `meeting_id` = memory-file basename. Empty threads → dropped. |
| `last_session` | `data/meeting_memory/<file>.md` via `load_last_session_summary` | Verbatim most-recent `### date` entry. No file / no entries → dropped. |
| `project_next_actions` | **Live-attendee inference** (see below) | Resolve internal attendees → person_ids → active projects where they are `members` → each project's open tasks (next action). No matched projects → dropped. |
| `pipeline_sales` | `data/pipeline_cache.json` (stage breakdown) + metrics engine (`_format_demos_line`, sales MTD) | Current state, not deltas. Engine unreachable → sales line shows "(unavailable)", pipeline still renders. Both absent → dropped. |

### `project_next_actions` — live-attendee inference (design correction)

The `people_ids` field on meeting configs is empty for 4 of 7 meetings (including Luke 1:1), so inferring projects from hand-maintained `people_ids` would come up empty exactly where needed. Instead, infer from the **live calendar event attendees**, which the Today brief already carries and already resolves via Plan 1:

1. From `event.attendee_details`, take internal attendees (`identity.is_internal(email, internal_domains)`).
2. Resolve each to a `person_id` via `identity.build_lookup(load_people(storage))` → `find_by_email` (fall back to `resolve` on name).
3. Select `projects_registry.json` projects with `status == "active"` where any resolved `person_id` ∈ `project.members[].id`.
4. For each such project, pull open tasks from `tasks.jsonl` (`lib.tasks`) and surface the next action.

This is self-maintaining (tracks whoever is actually on the invite) and requires no per-meeting `people_ids` upkeep. The projects↔people link already exists via `project.members`.

## Synthesis + wiring

`meeting_prep_recipe.build_prep(event, meeting_cfg, config, storage, api_key) -> str | None`:

1. Resolve the recipe from `meeting_cfg.prep_recipe`. No recipe → return `None`.
2. Gather each listed block in order; drop blocks returning falsy.
3. If **no** block produced content → return `None` (no LLM call, no empty prep).
4. Concatenate gathered chunks as context; run **one** LLM call (model from `config.ai_model`, default `claude-sonnet-4-6`, `max_tokens≈600`) with a system prompt that renders a short bulleted prep and honors `recipe.instruction` when present.
5. Log usage via `lib.llm_logger.log_usage("meeting_prep_recipe", ...)`.
6. Return the prep string (markdown).

Wiring in `today_brief`:
- `_meeting_dict` computes `kind`; for `internal` meetings it calls a helper that (a) loads the meeting index, (b) `find_meeting_for_event`, (c) if a recipe exists, `build_prep(...)`. Result → `prep`, else `null`.
- `generate_and_write` already receives `config`, `storage`, and events; it passes `api_key` (read from env, matching existing call sites) through to `_meeting_dict`. External meetings and internal meetings without a recipe are unaffected.

### Non-fatal contract

Consistent with the brief's existing "ingest is non-fatal" posture:
- Any exception inside a block's gather → that block is dropped (logged, not raised).
- Any exception in the LLM call → `prep: null`, meeting still renders.
- The **block-gathering layer stays deterministic**; only shaping is LLM. The module docstring's "Deterministic (no LLM in Plan 2)" line is updated to scope determinism to gathering + task/meeting assembly, noting recipe synthesis as the one LLM touchpoint.

## Caching

The Today brief is pull-based and may regenerate several times a day; we must not re-run the LLM each time.

- **Cache carrier: the prior `brief_today.json` itself** — no new state file, no second storage handle. Before synthesizing, read the previously written `brief_today.json` (same `registry_storage`). If it contains a meeting with the same `id`, the same `date` (today), and a matching `prep_hash`, reuse its `prep` verbatim.
- `prep_hash` = hash of `(recipe blocks + instruction)`. Stored as a sibling field on the meeting dict alongside `prep`. Editing the recipe changes the hash → forces regeneration. A new day → `date` mismatch → regeneration.
- This keeps caching self-contained in the artifact the tab already reads, and naturally expires daily.

## Storage notes

- `meeting_index.json` is read from the working tree via `load_meeting_index` (`open(path)`), not through a storage abstraction — in Actions this is the fresh `origin/main` checkout. It is a git-tracked user-config file (CLAUDE.md allow-list).
- `brief_today.json`, Meetings registry, `projects_registry.json`, `tasks.jsonl`, `people_registry.json` are all git-anchored registry stores; the brief already accesses them via `registry_storage(config)` / `replay_local(data_dir)` on the working tree. No R2 access is introduced.

## Testing

- **Per-block gather** (deterministic, no API): fixture Meetings state, a fixture `meeting_memory` md, a fixture `projects_registry` + `tasks.jsonl`, and a fixture `pipeline_cache`. Assert each block's output and its empty-source drop.
- **Live-attendee inference:** event with mixed internal/external attendees → correct person_id resolution → correct project selection; attendee resolving to nobody → block dropped.
- **Recipe resolution:** meeting with recipe vs without; unknown block name in a recipe is ignored with a log line.
- **Non-fatal paths:** a block that raises is dropped; an LLM error yields `prep: null`; a meeting with zero producing blocks yields `prep: null` and makes no LLM call.
- **Caching:** second generation same day with unchanged recipe reuses prep (LLM mocked, asserted called once); recipe edit (hash change) re-invokes.
- **Synthesis assembly:** LLM mocked — assert gathered context is passed and `instruction` is included when present.

## Seeded recipe (this pass)

Only **Luke 1:1** gets a `prep_recipe` (all four blocks + a sales-focused instruction, as shown in the schema example). Verify it populates in `brief_today.json` and renders in the Today tab. The remaining six meetings stay recipe-less.

## Follow-ups (out of scope here)

- Author recipes for the other six configured meetings.
- Plan 3 (external meeting prep), Plan 5 ("what moved").
- Optional: a Meetings-tab affordance to edit recipes instead of hand-editing JSON.
