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
- `processors.meeting_memory.find_meeting_for_event` / `load_meeting_index` — recipe config matching (`memory_file` basename gives the `meeting_id` slug).
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
    "blocks": [
      "open_threads",
      "last_session",
      {"block": "project_next_actions", "expand_threshold": 5, "max_per_project": 3},
      "pipeline_sales"
    ],
    "instruction": "Walk through each project below in turn — these are the ones I keep Luke informed on. For each, give a one-line high-level status backed by its open tasks (the tasks are the signal of what I'm working on next), and call out any blocker. This is my update to Luke, project by project."
  }
}
```

- `blocks` — ordered subset of the catalog (below). Each entry is either a **plain string** (block name, default params) or an **object** `{"block": "<name>", ...params}` when the block accepts parameters. Only listed blocks are gathered.
- `instruction` — optional per-meeting synthesis steer. Omitted → a default prompt runs.
- Entry with **no** `prep_recipe` → meeting renders `prep: null` (today's behavior, unchanged).

**Required code change:** `MeetingConfig` (`processors/meeting_memory.py:9`) is constructed via `MeetingConfig(**m)`; adding `prep_recipe` to the JSON will raise `TypeError` unless the dataclass gains `prep_recipe: Optional[dict] = None`. This field is additive and ignored by all existing consumers.

## Block catalog

Each block is a function `gather(ctx) -> str | None` returning a titled markdown chunk, or `None`/empty when its source has nothing (the block is then silently dropped — **never** a fabricated or empty-headed section). `ctx` carries the calendar event, matched `MeetingConfig`, `config`, and `storage`.

| Block | Source | Gather behavior |
|---|---|---|
| `open_threads` | Meetings registry: `replay_local(data_dir)[meeting_id]` → `render_for_prep`'s open-threads portion | Matched via `find_meeting_for_event`; `meeting_id` = memory-file basename. Empty threads → dropped. |
| `last_session` | Meetings registry: `replay_local(data_dir)[meeting_id]` → `meetings_lib.last_session(mtg)` | Most-recent session body from the live `meetings.jsonl` log (same state `open_threads` loads). No meeting / no sessions → dropped. |
| `project_next_actions` | Active projects where a resolved attendee is a `member` (see below) | Per project, surface open tasks (the "what's next" signal). Task selection: ≤`expand_threshold` open tasks → show all; >`expand_threshold` → show `max_per_project` with nearest due_date/horizon. No projects → dropped. |
| `pipeline_sales` | `data/pipeline_cache.json` (stage breakdown) + metrics engine (`_format_demos_line`, sales MTD) | Current state, not deltas. Engine unreachable → sales line shows "(unavailable)", pipeline still renders. Both absent → dropped. |

### `project_next_actions` — project selection & task capping

**Project selection — attendee-scoped, role-agnostic.** The block pulls the active projects that the meeting's attendees are attached to, so the update set is curated by *who you tag on which projects* rather than by any per-meeting config. Self-maintaining — no `people_ids` upkeep (that field is empty on 4 of 7 configs):

1. From `event.attendee_details`, take internal attendees (`identity.is_internal(email, internal_domains)`).
2. Resolve each to a `person_id` via `identity.build_lookup(load_people(storage))` → `find_by_email` (fall back to `resolve` on name).
3. Select `projects_registry.json` projects with `status == "active"` where any resolved `person_id` ∈ `project.members[].id`. **Any member role counts** (`owner` / `contact` / `collaborator`) — no role filter. The projects↔people link already exists via `project.members`.

So for the Luke 1:1, the prep walks exactly the projects Luke is a member of. Trent curates that set by adding Luke as a member (the `contact` role — "keep informed" — is the natural label, but selection doesn't depend on which role) on the projects he reports to Luke on. Until Luke is a member of at least one active project, this block produces nothing and is silently dropped (non-fatal).

**Task capping params:**

| Param | Default | Meaning |
|---|---|---|
| `expand_threshold` | `5` | If a project has this many or fewer open tasks, show all of them. |
| `max_per_project` | `3` | When a project exceeds `expand_threshold`, show this many tasks, chosen by nearest due_date/horizon. |

**Task selection per project:** collect the project's open tasks from `tasks.jsonl` (`lib.tasks`). If `count <= expand_threshold`, surface all. If `count > expand_threshold`, sort by nearest scheduling date — `due_date` if present, else `horizon`, tasks with neither last — and take the first `max_per_project`. (So a project with 5 open tasks shows 5; a project with 6 shows the 3 most time-sensitive.) Projects are ordered by their most imminent task's date, so the work nearest at hand leads.

## Synthesis + wiring

`meeting_prep_recipe.build_prep(event, meeting_cfg, config, storage, api_key) -> str | None`:

1. Resolve the recipe from `meeting_cfg.prep_recipe`. No recipe → return `None`.
2. Gather each listed block in order. Normalize each entry: a string → block name with default params; an object → `block` name + params passed to the gather function. Drop blocks returning falsy.
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

- **Per-block gather** (deterministic, no API): fixture Meetings registry state (threads + sessions), a fixture `projects_registry` + `tasks.jsonl`, and a fixture `pipeline_cache`. Assert each block's output and its empty-source drop.
- **`project_next_actions` selection:** mixed internal/external attendees → correct person_id resolution → projects where a resolved attendee is a member (any role); attendee resolving to nobody, or resolving to a person on no active project → block dropped.
- **Task selection:** project with ≤`expand_threshold` open tasks → all shown; project with >`expand_threshold` → exactly `max_per_project`, chosen by nearest `due_date`/`horizon` (tasks with neither sort last); project ordering by most-imminent task.
- **Recipe resolution:** meeting with recipe vs without; string-form vs object-form block entries both parse; unknown block name in a recipe is ignored with a log line.
- **Non-fatal paths:** a block that raises is dropped; an LLM error yields `prep: null`; a meeting with zero producing blocks yields `prep: null` and makes no LLM call.
- **Caching:** second generation same day with unchanged recipe reuses prep (LLM mocked, asserted called once); recipe edit (hash change) re-invokes.
- **Synthesis assembly:** LLM mocked — assert gathered context is passed and `instruction` is included when present.

## Seeded recipe (this pass)

Only **Luke 1:1** gets a `prep_recipe`, exactly as shown in the schema example: all four blocks, `project_next_actions` with `expand_threshold: 5` / `max_per_project: 3` (attendee-scoped, so it walks the projects Luke is a member of), and a project-by-project walkthrough instruction.

**Data setup precondition:** the `project_next_actions` block only produces content once Luke is a member of at least one active project. Luke is currently not a member of any project in `projects_registry.json`, so as part of validating this pass, Trent tags Luke (`contact` role) on the projects he reports to Luke on — via the Registry UI. Until then the block is silently dropped and the prep is built from the other three blocks.

Verify the recipe populates in `brief_today.json` and renders in the Today tab. The remaining six meetings stay recipe-less.

## Follow-ups (out of scope here)

- Author recipes for the other six configured meetings.
- Plan 3 (external meeting prep), Plan 5 ("what moved").
- Optional: a Meetings-tab affordance to edit recipes instead of hand-editing JSON.
