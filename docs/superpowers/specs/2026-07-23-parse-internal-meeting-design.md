# Design: `parse-internal-meeting` skill

**Date:** 2026-07-23
**Owner:** Trent Luecke
**Status:** Approved design — ready for implementation plan

## Problem

Trent drops internal team-meeting transcripts (Slack huddles, recorded via Loom) into
Claude Code sessions to get action items and summaries. The results feel context-blind:
the parser behaves like a transcription service that watched the meeting with no ground
knowledge. Concretely, the last parse (marketing huddle with Nicole and Rachel):

- Over-extracted — surfaced things that weren't real action items.
- Flattened everything into one undifferentiated "action items" list.
- Had no way to attribute commitments or read the room, because nothing feeds it context.

Root causes, separated:

1. **No parsing frame.** There's no reference for how to read an *internal* meeting from
   Trent's seat — what's pertinent, what's noise, how to bucket, how to speak his language.
   All existing transcript machinery (`transcript_scan.py`, `interview_parser.py`,
   `query-avoma`, Avoma ingest) is tuned for *external* customer/prospect calls.
2. **Low-fidelity input.** Slack huddles recorded on Loom produce a single, unlabeled
   transcript. Loom is a screen-recording tool, not a meeting recorder, so there are no
   speaker labels — which breaks any per-speaker attribution the frame needs.
3. **No context accumulation.** Because summaries aren't stored anywhere durable per
   meeting, every parse starts cold.

## Scope

**In scope:** A Claude Code skill that parses *internal* team-meeting transcripts, presents
a tight structured readout, runs a comment/approval loop, and (on approval) writes results
into the registry via the existing storage layer.

**Explicitly out of scope:**

- A parsing page in the Registry UI. Abandoned by decision — parsing runs in Claude Code
  sessions. Results still surface in the Registry UI because write-back targets `origin/main`.
- External customer/prospect calls (owned by `query-avoma`, Avoma ingest, `transcript_scan.py`).
- Changing the recording platform. Loom-today is accepted; Slack-native huddle transcripts
  (speaker-labeled, on paid Slack tiers) are noted as a future input upgrade the frame will
  handle without a rewrite, but investigating/adopting them is a separate track.

## Chosen approach

**Approach C — reference-frame skill + thin write-back helper.**

The skill is a markdown playbook (`SKILL.md`) that governs how Claude reads an internal
transcript in-context: what context to load first, how to bucket and filter, how to speak
Trent's language, and how to write approved results back. A thin write-back helper handles
the one fragile part — committing structured records to `origin/main` with correct schema —
by calling the existing `lib.meetings` / `lib.tasks` functions through
`lib.storage.registry_storage(config)`.

Rejected:
- **Approach A (pure skill, freehand write-back):** hand-writing registry records each run
  risks wrong storage target / malformed schema / skipped commit. The helper removes that.
- **Approach B (Python extractor + JSON pipeline):** the failure was judgment/context, not
  automation. A code extractor would re-encode the context-blindness and slow iteration.
- **Registry UI parsing page:** front-loads LLM-in-Flask plumbing to solve a single-surface
  problem that's already solved (outputs land in the UI regardless of where parsing happens),
  and it makes the frame — the thing that carries the value — harder to iterate.

## Location & trigger

- Skill: `.claude/skills/parse-internal-meeting/SKILL.md` (matches `query-avoma` /
  `os-feature-shaping` directory pattern).
- Triggers when Trent drops an internal transcript or asks to parse an internal/team meeting
  ("parse my huddle with Nicole and Rachel", "here's the marketing sync transcript").
- Must NOT collide with `query-avoma` (external call lookup) or Avoma ingest. The description
  scopes it to internal team meetings and to *parsing a pasted/provided transcript*, not
  looking up recorded calls.

## Input contract

- **Transcript:** Loom dump today (unlabeled); Slack-native speaker-labeled later. The frame
  handles both.
- **Context header (from Trent):** one or two lines — who was in it (+ role) and what it was
  about. Carries the attribution load the unlabeled transcript can't.
- **Graceful degradation:**
  - Missing header → ask for it before parsing (attribution depends on it).
  - No speaker labels → attribute best-effort and **explicitly flag every uncertain
    attribution**, never guess silently.

## Context load (before parsing)

Load, in order, before reading the transcript:

1. **People files** (`data/people/*.md`) for named attendees.
2. **`data/projects.md`** and **`data/memory/decisions.md`** (always).
3. **Prior sessions of the same meeting series** if this meeting maps to an existing record
   (see Write-back) — this is the accumulated context.
4. Conditionally: vector memory / pipeline cache, only if the transcript's topics clearly
   warrant it.

This is what makes the parse read like an insider rather than a stranger.

## Parsing frame (the core)

**Four separated buckets — never one flat list:**

1. **I owe** — commitments Trent made.
2. **Owed to me** — commitments others made that Trent is waiting on.
3. **Decisions made** — conclusions to remember/act on (not tasks).
4. **Team tasks I own the outcome of** — assigned to others, Trent accountable.

**Filtered out / demoted to a footnote:**
- Unresolved brainstorming (ideas floated, not decided).
- Others' internal tasks Trent has no stake in.
- Hypotheticals / "someday" (no owner, deadline, or real intent).

**Kept as context, never promoted to tasks:**
- Status updates / FYI — these become the on-the-ground context (stored in the session body)
  that makes the *next* parse smarter.

**Speaks Trent's language:** the frame encodes his vocabulary by pointing Claude at the live
data layer (people files, decisions.md) rather than a static glossary — OS vs. Strength
product split, people shortnames/roles, GTM/pipeline terms. A short, stable who's-who +
product-split primer may be inlined; anything that drifts is loaded from data.

## Readout

Tight, ranked, no fluff:
- One-line headline: what the meeting was really about.
- The four buckets, each ranked by importance.
- Low-confidence items and uncertain attributions flagged inline.
- Nothing else.

## Approval + comment loop

Before anything is written, Trent reviews the readout and comments freely — e.g. "drop #3,
that owed-to-me is actually owed to Rachel not me, add a task about the deck Nicole
mentioned, recategorize #5." Claude revises and re-presents. **Write-back happens only on an
explicit commit.** Nothing is auto-filed.

## Write-back (thin helper)

On approval, the helper writes to `origin/main` via `lib.storage.registry_storage(config)`,
calling existing functions (no Flask server dependency):

- **Meeting series record:** reuse-or-create via `lib.meetings.append_create` (+
  `meeting_index.json` entry).
  - **Recurring** internal meeting → reuse-or-create the series so sessions accumulate.
  - **One-off** huddle → create the series with an **empty `calendar_pattern`** so it never
    fires a nudge (nudges are calendar-pattern driven).
  - Ask "recurring or one-off?" at parse time if ambiguous.
- **Session** (`lib.meetings.append_add_session`, dated): headline + summary + FYI/status
  context as the `body`. This is the durable per-meeting context reloaded on future parses.
- **Threads** (`lib.meetings.append_add_thread`, with `person_id`):
  - Owed to me → thread, `person_id` = who owes it.
  - Team task I own → thread, `person_id` = assignee.
  - My commitments → thread owned by Trent.
- **Promote-to-task** (`/promote` semantics → `lib.tasks.add_task` with
  `source=meeting-<id>`, `owner`, and `metadata` linking back to the thread):
  - **Default:** *my commitments* auto-promote to Work-tab tasks (Trent will act on them).
  - *Owed-to-me* and *team tasks* stay as threads unless Trent says promote in the approval
    step.
- **Decisions** → appended to `data/memory/decisions.md` (durable; + vector memory).

After writing, Claude confirms exactly what was written and where.

### Registry storage rules (from CLAUDE.md — must hold)

- Registry stores are git-anchored on `origin/main`, accessed via
  `lib.storage.registry_storage(config)` — never `build_storage` (R2), never a raw
  working-tree edit.
- Task records follow the `lib.tasks.add_task` schema; `tasks.jsonl` uses the `merge=union`
  driver.
- Writes must be committed back to `origin/main` so the Registry UI (which reads
  `origin/main`) sees them.

## Why this closes the original problem

Summaries are stored as **sessions on a recurring meeting series**, so the next parse of the
same meeting loads prior sessions as context. The system that "had no way of knowing the
broader context" starts accumulating it per meeting, every time a transcript is parsed — the
context problem compounds toward solved instead of resetting each time.

## Components & boundaries

1. **`SKILL.md`** — the reference frame. Governs input contract, context load, buckets,
   filter rules, language, readout shape, approval loop, and when/what to write. Iterable via
   markdown edits; this is where judgment lives.
2. **Write-back helper** (small module/script, e.g. `scripts/meeting_writeback.py` or a
   `lib` function) — takes the approved, structured result and commits it via
   `registry_storage` + `lib.meetings` / `lib.tasks`. Single responsibility: correct,
   committed registry writes. Interface: approved-items structure in → confirmation of what
   was written out. No parsing judgment inside it.

## Open items for the implementation plan

- Exact form of the write-back helper (standalone script vs. `lib` function) and how the
  skill invokes it with the approved structure.
- The approved-items data structure passed from readout → helper (bucket, text, person_id,
  promote flag, meeting mapping, recurring/one-off).
- Meeting-series matching: how to detect that a huddle maps to an existing series (by
  attendees + name) vs. needs a new record, to avoid duplicate series.
- Whether the who's-who/product-split primer is inlined in `SKILL.md` or loaded from a
  referenced data file.
- Person-ID resolution: mapping attendee names in the header to `people_ids` for threads.
