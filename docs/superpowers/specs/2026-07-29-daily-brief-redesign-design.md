# Daily Brief Redesign: "Today" Tab

**Date:** 2026-07-29
**Status:** Design approved, pending spec review

## Problem

The daily brief email has stopped earning attention. Two root causes, diagnosed during brainstorming:

1. **Content/format.** Recent additions (open loops, to-dos) turned the brief into a wall of text. Trent's ADHD reflex on a wall of text is to read *none* of it. On days he opened it, it didn't change his plan.
2. **No value glance.** On days he skipped it, he felt nothing inside was worth his time.

Delivery mechanism (email) is *not* the primary problem — but it compounds it: the email buries in the inbox and, being static, can't hide detail. Any all-in-one static artifact rebuilds the wall.

**The original instinct** ("move off email, manually generate outside the inbox") only addresses location. The real fix is **content discipline + progressive disclosure on a surface Trent already opens every morning.**

## Solution Overview

Replace the email brief with a pre-computed **"Today" tab in the Registry UI** (the browser tab already open in Trent's morning routine).

- **Pure pull.** No email, no Slack nudge. Trent opens the tab when ready; the brief is already there, instant.
- **Pre-computed.** The existing ~7am GitHub Actions run is repurposed to assemble the brief before Trent wakes, so there is no generation wait.
- **Progressive disclosure.** Three scannable headlines up top; all heavy detail hidden behind expand-on-click cards. The wall never forms.

Design principle throughout: **ruthless cut + best-effort, show-your-work sourcing.** The tab shows only what it confidently finds, labels its sources, and never fabricates or pads with "N/A".

## The Today Tab (layout)

A new tab in the Registry UI. Roughly one screen before any expanding.

### ① Meetings today
Every meeting on today's calendar, one compact line each (`9:00 · Acme Barbell demo · external`).
- **External meetings** render as collapsed cards → expand to the external prep block.
- **Configured internal meetings** render as collapsed cards → expand to their config-driven prep block.
- **Unconfigured internal meetings** are just a line (no prep block).

### ② Needs you today
The 1–3 tasks/horizon items **due today or overdue/at-risk**, ranked. **Hard cap of 3.** This is *not* the task list — the full list stays in the Work tab. When nothing is actually urgent, this section says "nothing due" rather than padding.

### ③ What moved
Other reps' OS demos completed in roughly the last 24h, one line each:
`Rachel · Iron Valley S&C · demo · follow-up booked Thu`
Signal + tidy outcome/next-step only. **No substance dump** (objections/features/competitor mentions are explicitly a separate future initiative). Sourced org-wide from Avoma, excluding Trent's own calls.

## External Meeting Prep Block (auto-sourced)

Any external meeting on the calendar automatically gets the full prep block. Sourced by matching the attendee's email/domain across data sources via **identity resolution**. Each line renders only if confidently found; empty sources simply don't render.

- **Recap** — 2–3 lines from the last Avoma call with this person/company.
- **Open items** — see extraction rule below.
- **Deal context** — pipeline stage, size, age, product (OS vs Strength) from the pipeline cache.
- **People** — attendees, titles, contact-file notes.
- **Last touch** — e.g. "last spoke 12 days ago".
- **Email context** — recent Gmail threads with the attendees.
- **Cold-demo fallback** — no Avoma history → lean on email + topics the prospect wrote in the invite; label clearly as "first touch — no prior history".

### Open-items extraction rule (Option A — recompute, no storage)
At brief-generation time, pull the last call's transcript and run a **strict extraction**: only explicit, spoken commitments ("I'll send the pricing doc," "we'll circle back Thursday") — **never inferred or implied tasks.** This directly fixes the current Slack Avoma-processing behavior, which over-infers action items.

- **No storage.** Open items are recomputed each morning; nothing is written to any people profile.
- **Known limitation, accepted:** no closure tracking. If Trent already did the follow-up, it still shows until the next call happens. This is acceptable for a *prep refresher* (Trent eyeballs it).
- **Explicitly out of scope:** writing tracked, closable action items into people profiles (this was considered as "Option B" and deferred to its own future project — a curated action-item tracker — to avoid landing over-inflated items in real profiles).

## Internal Meeting Prep (config-driven)

Internal prep varies per recurring meeting, so it is **composable config in `data/meeting_index.json`**, not one-size-fits-all. Five ingredients:

| Ingredient | What it pulls |
|---|---|
| `meetings_tab` | Open loops/threads + last summary from the Meetings tab. **Universal — every configured meeting.** |
| `avoma_context` | Latest Avoma recording of this recurring meeting, for detail beyond thread notes. |
| `attendee_tasks` | Registry tasks *owned by* named attendees (so their action items don't slip). |
| `email_context` | Recent Gmail threads with named people, then Claude-filtered to a named topic (e.g. partnerships). Topic filtering is best-effort/fuzzy — accepted. |
| `mode` | `recap` (what we discussed / what's open) vs `agenda` (what I need to put in & cover). |

### The 7 configured meetings (Trent supplies title + attendee match rules)
- **OS Dev Sync** → `meetings_tab` + `avoma_context` + `attendee_tasks`(James Peters + attendees) · `recap`
- **1:1 OS Marketing** → `meetings_tab` + `email_context`(Nicole / partnerships+projects) + `attendee_tasks`(Nicole) · `recap`
- **OS Marketing 2.0** → `meetings_tab` + `email_context`(Rachel Newman, Nicole Foley / partnerships) + `attendee_tasks`(Rachel, Nicole) · `recap`
- **Luke 1:1** → `meetings_tab` only · `recap`
- **Rev Dept Heads** → **`agenda`** mode (adapt the existing pre-meeting Slack nudge skeleton into "what to put in the agenda / cover"); currently has no reliable transcript ingest.
- **Product Planning** → `meetings_tab` · `recap` (light; little transcript history)
- **OS Sit Down** (Quinn) → `meetings_tab` + `attendee_tasks`(Quinn) · `recap`

`meeting_index.json` currently has only 3 entries and must be expanded to cover all 7 (title + attendee match rules per meeting).

## Identity Resolution (shared component)

A named component that matches a calendar attendee to the right registry person across name/email variants. It powers:
1. External prep matching (recap, open items, deal, people).
2. Internal `attendee_tasks` lookup.
3. "What moved" attribution.
4. Dedup before auto-provisioning (don't create duplicate people).

## Attendee Auto-Provisioning

During the morning run, for each **external** attendee on today's calendar who resolves to **no** existing registry person, create a lightweight stub profile directly (no pending gate — a home must exist before the post-call transcript is processed).

- **Stub contents:** name, email, company/domain, title (if in the invite), and **provenance** (`auto-created from calendar, YYYY-MM-DD, meeting: <title>`).
- **Bloat guards:**
  - Skip internal teammates.
  - Skip meetings with **6 or more attendees** (only ≤5-attendee meetings provision).
- Provenance tags make auto-created stubs identifiable and prunable later.

## Architecture

- **Generation** repurposes the existing ~7am GitHub Actions brief run. It no longer sends email. It:
  1. Reads today's calendar.
  2. Runs identity resolution + auto-provisioning (writes new stubs to `people_registry.json`).
  3. Assembles the structured brief (headlines + external prep + internal prep).
  4. Commits `brief_today.json` and any new people stubs to `origin/main`.
- **Storage:** `brief_today.json` is a git-anchored registry store on `origin/main`, read by the Registry UI via the existing `git show origin/main:<file>` snapshot mechanism. Per repo convention, the workflow's commit-back `git add` must include `brief_today.json` and `people_registry.json`.
- **Shared generation library:** generation logic lives in a library callable from both `main.py` (Actions) and `tools/server.py` (the Flask server), so a **"Refresh" button** in the Today tab can recompute on demand.
- **Rendering:** the Today tab is added to `tools/registry_ui.html` + `tools/server.py`, reading `brief_today.json` from the main-anchored snapshot.

## Cut From the Old Brief

Removed entirely from the daily surface (some still live in their own tabs):
- Full task/open-loop list (only ≤3 due/at-risk survive in "Needs you today"; full list stays in Work tab)
- Slack DM summaries
- Pipeline digest / stale-cache warnings
- Memory/observation callouts
- "Surfaced today" buyer-story prompts
- Weekly-synthesis bits
- **The email send itself.**

## Open Items to Verify First (implementation step 1)

Before building features on top of them:
1. **Avoma API — attendee search.** Confirm the API supports "calls where attendee X participated" (external prep recap/open-items lookup). Name-vs-email mismatches will cause misses.
2. **Avoma API — org-wide recent demos.** Confirm "demos org-wide completed in last ~24h, excluding Trent" is queryable (Trent confirms the key is org-scoped; verify the response shape). Falls back to Trent's own recent closed-loop calls if not.
3. New capabilities to build: attendee-owned task query, topic-scoped email pull, agenda-mode internal prep, identity resolution.

## Non-Goals / Out of Scope

- Slack or email delivery of the new brief (pure pull only).
- Substance digest of other reps' demos — objections/features/competitor mentions (separate future initiative).
- Writing tracked/closable action items into people profiles ("Option B" — separate future project).
- Deep transcript ingest for Rev Dept Heads / Product Planning (they rely on Meetings-tab content + agenda mode for now).
