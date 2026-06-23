# Open Loops in the Daily Brief — Design

**Date:** 2026-06-23
**Status:** Approved, pending implementation plan

## Problem

The Meetings tab in the Registry UI lets Trent capture per-meeting "open loops"
(unclosed `threads` in `data/meetings.jsonl`). Today these loops are only
surfaced in the ~20-min pre-meeting Slack prep (`render_for_prep` →
`build_recurring_internal_context` → `nudger.py`). They never appear in the
morning brief, so loops on meetings that aren't scheduled today stay invisible —
exactly the meetings most likely to have forgotten commitments.

Goal: surface every open loop in the morning brief, each tagged with its meeting
and owner, so the standing backlog is visible once a day.

## Why this is a deterministic section (architecture)

The brief is **not** a deterministic render of its context blocks. Every block
(calendar, meeting prep, people, etc.) is fed into a single Claude call that
synthesizes them into two lists — `act_today` and `what_moved` — as plain
action sentences with "no brackets, no source tags" (`processors/brief.py`
SYSTEM_PROMPT). The only section that bypasses the LLM and renders verbatim is
`metric_flags`, which is pre-computed and passed straight to the email template.

The chosen layout (two buckets, grouped by meeting, owner + age annotations)
therefore can only exist if rendered deterministically, mirroring the
`metric_flags` pattern. Feeding open loops into the LLM prompt instead would
dissolve them into ≤7 woven sentences with no grouping and most loops dropped —
rejected.

## Behavior

A new **Open Loops** section in the brief email, rendered deterministically.
Two buckets:

- **OPEN LOOPS — TODAY**: loops belonging to meetings that have a calendar event
  today. Never capped.
- **OPEN LOOPS — OTHER**: every other open loop. Capped at the 10 most
  recently created loops; overflow rendered as a `+N more open loops` line.

Within each bucket, loops are grouped by meeting. Meeting display name comes from
`data/meeting_index.json` (`name` field), falling back to the title-cased slug
when no config entry exists. Each loop line shows:

- the loop text,
- the owner, resolved from `person_id` → `canonical_name` via
  `data/people_registry.json` (fallback: the raw `person_id` if unresolved; no
  owner shown if `person_id` is null),
- an age tag: `· {N}d`, or `· today` when created today.

Within a meeting, loops sort **oldest-first** so stale loops rise to the top.
If there are zero open loops across all meetings, the entire section is omitted
(matching how `what_moved` renders conditionally).

### Example

```
OPEN LOOPS — TODAY
• Rev Dept Heads
   - Finalize Q3 quota model — Quinn Kastle · 9d
   - Pricing page copy sign-off · 2d

OPEN LOOPS — OTHER
• Luke 1:1
   - Loop Luke in on onboarding metric · 21d
   +3 more open loops
```

## Components

### 1. `lib/meetings.py` — `open_loops_buckets(...)` (pure function)

```
open_loops_buckets(state, meeting_names, today_ids, person_names, today, other_cap=10)
```

- `state`: replayed meetings dict (`{slug: {threads, sessions, ...}}`).
- `meeting_names`: `{slug: display_name}` map.
- `today_ids`: set of slugs whose meeting has a calendar event today.
- `person_names`: `{person_id: name}` resolver map.
- `today`: explicit `datetime.date` (no hidden `now()` — keeps it testable and
  consistent with the module's determinism rules).
- `other_cap`: max loops in the OTHER bucket (default 10).

Returns:

```
{
  "today": [ {"meeting_name": str, "loops": [ {"text", "owner", "age_days"} ] } ],
  "other": [ ... same shape ... ],
  "other_more": int,   # count of OTHER loops dropped by the cap
}
```

All bucketing, owner resolution, age computation, sorting, and capping live
here. OTHER cap selects the 10 most recently created loops (by `created_ts`
desc), then regroups them by meeting for display; remaining count → `other_more`.
`owner` is `None` when `person_id` is null; the raw `person_id` string when the
id isn't in `person_names`.

### 2. `pipeline.py` — `build_open_loops(today_events, meeting_configs, storage)`

Thin wiring, computed in the process stage next to `build_meeting_prep`:

- `meetings_lib.replay_local()` for state.
- Reuse `find_meeting_for_event` (the matcher `build_meeting_prep` already uses)
  over `today_events` to compute `today_ids`.
- Build `meeting_names` from `meeting_configs`.
- Load `people_registry.json` and build the `{id: canonical_name}` map.
- Call `open_loops_buckets(...)` with `today = datetime.now().date()`.

Stored on `ProcessedContext` (e.g. `ctx.open_loops`).

### 3. `processors/brief.py` — `BriefContent`

Add `open_loops: dict = field(default_factory=dict)`.

### 4. `pipeline.py` — assignment

Assign `brief.open_loops = ctx.open_loops` after `generate_brief` returns
(post-hoc, like the existing `act_today` warning inserts), so the section
survives even the brief-error fallback path.

### 5. `templates/morning_brief.html` — render

New `{% if brief.open_loops and (brief.open_loops.today or brief.open_loops.other) %}`
section rendering the two buckets, styled consistently with existing sections
(reuse `.section` / list styling). Render `+N more open loops` when
`other_more > 0`.

`outputs/sender.py` needs no signature change — it already passes `brief` to the
template.

## Edge cases

- **Loop on a meeting not scheduled today** → always OTHER (intended).
- **Slug in `meetings.jsonl` with no `meeting_index.json` entry** → display name
  = title-cased slug; can't be in TODAY (no calendar_pattern to match).
- **`person_id` null** → no owner shown. **`person_id` unresolved** → show raw id.
- **Zero open loops** → section omitted entirely.
- **Age** from `thread.created_ts` (ISO8601 UTC, `%Y-%m-%dT%H:%M:%S`):
  `(today - created_date).days`; `0` → `today`.

## Testing

Unit tests on `open_loops_buckets` (pure, fixed `today`):

- today vs other bucketing.
- owner resolution: resolved name, unresolved id passthrough, null → no owner.
- age computation against a fixed `today` (including the `today` / 0-day case).
- OTHER cap + `other_more` count math (e.g. 13 OTHER loops, cap 10 → 10 shown,
  `other_more == 3`).
- empty state → `{"today": [], "other": [], "other_more": 0}`.

Optional: a template render smoke test asserting the section appears when
`open_loops` is populated and is absent when empty.

## Out of scope

- Agenda items in the brief (they land in session logs naturally — explicitly
  excluded).
- Feeding open loops into the LLM `act_today` synthesis (rejected above).
- Any change to the pre-meeting Slack prep path (already surfaces open loops).
- Automated thread→task promotion (remains a manual UI action).
