---
name: parse-internal-meeting
description: Use when Trent drops an INTERNAL team-meeting transcript (Slack huddle / Loom recording) and wants it parsed into action items, decisions, and a summary — e.g. "parse my huddle with Nicole and Rachel", "here's the marketing sync transcript", "process this internal meeting". NOT for external customer/prospect calls (use query-avoma) and NOT for looking up existing recordings.
---

# Parse Internal Meeting

Parse an internal team-meeting transcript from Trent's seat: bucket what matters to him,
filter noise, review with him, then write approved items to the registry.

Spec: `docs/superpowers/specs/2026-07-23-parse-internal-meeting-design.md`.

## Scope

INTERNAL team meetings only (Trent + colleagues: Nicole, Rachel, Luke, Teofe, Quinn, etc.).
For external customer/prospect calls, stop and use `query-avoma` instead.

## Step 1 — Get the input

You need two things:
1. The transcript (pasted, or a file path). Loom transcripts are usually UNLABELED (no
   speaker names) — that is expected.
2. A one-line context header from Trent: **who was in it (+ roles) and what it was about.**

If the header is missing, ASK for it before parsing — attribution depends on it. If the
transcript has no speaker labels, attribute best-effort and FLAG every uncertain
attribution in the readout; never guess silently.

## Step 2 — Load context (read the room first)

Before parsing, load:
- `data/people/*.md` for each named attendee (roles, history, how Trent refers to them).
- `data/projects.md` and `data/memory/decisions.md` (always).
- If the meeting maps to an existing recurring series (see Step 4), load its prior sessions
  from `GET /api/bootstrap` → `meetings` → the matching meeting's `sessions` — that is the
  accumulated context that makes this parse sharper.
- Pull vector memory / pipeline cache only if the topics clearly call for it.

Speak Trent's language: product split is OS vs Strength (tag facts by product); use people's
short names; know GTM/pipeline terms. When unsure of a term, check the people files and
decisions.md rather than guessing.

## Step 3 — Parse into four buckets (never one flat list)

1. **I owe** — commitments Trent made.
2. **Owed to me** — commitments others made that Trent is waiting on.
3. **Decisions made** — conclusions to remember/act on (NOT tasks).
4. **Team tasks I own the outcome of** — assigned to others, Trent accountable.

FILTER OUT / demote to a one-line footnote (do NOT make these action items):
- Unresolved brainstorming (ideas floated, not decided).
- Others' internal tasks Trent has no stake in.
- Hypotheticals / "someday" (no owner, deadline, or real intent).

KEEP as context (put in the summary, NEVER as a task): status updates / FYI.

## Step 4 — Resolve which meeting this ties to (HARD STOP on ambiguity)

Call `GET /api/bootstrap` and read `meetings` (each has `id`, `name`, `people_ids`).
- If the transcript clearly matches exactly one recurring series (by name + attendees),
  use it (`kind: "recurring"`, that `meeting_id`).
- If it is a brand-new recurring meeting, propose creating the series (`kind: "recurring"`,
  empty `meeting_id`).
- If it is a one-off / impromptu meeting, use `kind: "oneoff"` (no series is created).
- If there is ANY ambiguity — no clear match, multiple plausible matches, or unclear whether
  it recurs — STOP and ask Trent to pick from the existing meetings, name a new series, or
  declare it one-off. Never auto-create a series or guess.

Resolve attendee names to `people_ids` using `GET /api/bootstrap` → `people` (each `{id,
name}`). Trent's own id is his people-registry id (look it up; do not hardcode). If a name
does not resolve, ask.

## Step 5 — Present the readout (tight, ranked)

Show:
- One-line headline: what the meeting was really about.
- The four buckets, each ranked by importance.
- Low-confidence items and uncertain attributions flagged inline.
- Nothing else.

## Step 6 — Review + comment loop

Ask Trent to comment freely — drop items, recategorize, fix an owner, add something you
missed. Revise and re-present. Do NOT write anything until he explicitly says commit.

Remember the owner rule (the action-vs-monitor axis):
- I owe → owner = Trent.
- Owed to me → owner = the person who owes it.
- Team task I own → owner = the assignee.

## Step 7 — Write back (only on explicit approval)

1. Ensure the Registry server is running (`GET http://localhost:8787/api/bootstrap` succeeds).
   If not, launch it (see the `registry-ui` skill or `python3 tools/server.py`).
2. Build the approved-items payload (schema below) and write it to a temp file in the
   scratchpad.
3. Run: `python -m scripts.meeting_writeback <payload.json>`
4. Report back exactly what was written (the command prints a `created` list), including
   any `errors`. If there are errors, surface them — the write did NOT fully land.

Payload schema:

```json
{
  "meeting": {"kind": "recurring|oneoff", "meeting_id": "<slug or empty>",
              "name": "<meeting name>", "people_ids": ["..."], "date": "YYYY-MM-DD"},
  "summary": "Headline + summary + FYI/status context as one body string.",
  "commitments": [{"text": "...", "owner": "<trent id>"}],
  "owed_to_me":  [{"text": "...", "owner": "<person id>"}],
  "team_tasks":  [{"text": "...", "owner": "<person id>"}],
  "decisions":   ["..."]
}
```

Write-back routing (handled by the orchestrator — do not re-implement, just build the payload):
- **Recurring:** summary → session; commitments → thread (owner) promoted to task;
  owed-to-me + team tasks → threads (owner = person_id); decisions → decisions.md.
- **One-off:** summary → `MEETING_NOTES`-tagged note; ALL action items → Work-tab tasks with
  their owner; decisions → decisions.md. No meeting record is created.
