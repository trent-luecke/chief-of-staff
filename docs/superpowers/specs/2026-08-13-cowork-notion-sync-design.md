# Cowork Notion-Sync Routine — Design

**Date:** 2026-08-13
**Status:** Design — pending review
**Author:** Trent + Claude

## Problem

Every night the Chief of Staff system emails/DMs Trent an **Avoma digest** in Slack — a summary of the day's demo, follow-up, and onboarding calls. Today Trent reads that digest and **manually re-enters the same information** into the two Notion trackers:

- **OS Sales Pipeline Tracker** (demos / follow-ups → status, last-contacted, call notes)
- **OS Customer Onboarding Tracker** (onboarding calls → phase, completed items, notes)

This is pure toil, and it is redundant: the digest is generated *by our own system*, so the structured data already exists one step upstream. This design eliminates the manual re-entry.

## Key insight

`scripts/avoma_sync.py` (runs nightly in GitHub Actions) already builds fully-structured payloads — `pipeline_updates` and `onboarding_updates` — with every field Notion needs (lead/customer name, call date, inferred status, onboarding items completed, next steps, is-new-lead, account owner, buying signals, objections). It then **flattens them into the Slack prose and discards the structure**.

Therefore we do **not** parse the Slack digest (lossy, fragile). We tap the structured payloads at the source and hand them to a local routine that writes them to Notion.

## Why a local routine (the auth constraint)

The two write targets are **claude.ai OAuth connectors** (Notion MCP `mcp__2942ad11-…`), not local API tokens. GitHub Actions cannot authenticate to them — which is exactly why `avoma_sync.py` can send Slack (bot token) but cannot write Notion from the cloud.

**De-risk result (proven empirically 2026-08-13):** scheduled tasks created via the `scheduled-tasks` MCP run **in-app** ("Scheduled tasks run while this app is open"), so they **inherit the app's live claude.ai connectors**. A one-time scheduled probe successfully fetched the OS Customer Onboarding Tracker read-only. Notion is not in `mcp-needs-auth-cache.json`. Auth is **not** a blocker for a local in-app routine.

The real gotcha is **one-time tool pre-approval**: the first scheduled call to any tool pauses on a permission prompt and, unattended, halts. Approvals granted once are stored on the task and auto-applied to future runs. So the rollout includes a deliberate **first supervised run** to pre-approve the toolset.

## Goals

- Zero manual re-entry of Avoma digest data into Notion on a normal day.
- Apply-all-then-report: write every update automatically, then post one Slack summary with consequential changes flagged for after-the-fact review (decision made 2026-08-13).
- Idempotent and conflict-free: a call is never double-written; concurrent producer/consumer never corrupt the queue.
- Fails safe: a Notion write error leaves that entry to retry, never loses it.

## Non-goals

- Not parsing or reading the Slack digest text.
- Not moving `avoma_sync.py` off the cloud (it must keep running nightly regardless of whether the laptop is on).
- Not a per-write approval gate (explicitly rejected — it re-adds the toil we're removing).
- Not touching the Registry UI or other registry stores.

## Architecture

```
avoma_sync.py (cloud, nightly)            PRODUCER  [~10 lines added]
  builds pipeline_updates + onboarding_updates          (already exists)
  → append each as one JSONL line to data/notion_updates_queue.jsonl
  → git add + commit to origin/main (existing commit-back step)

                    │  git
                    ▼
Cowork routine (local, weekday ~8:10am)   CONSUMER  [new — the missing piece]
  1. git-sync latest queue from origin/main
  2. read queue; skip entries whose id ∈ data/state/notion_updates_seen.json
  3. for each fresh entry, invoke the matching updater skill:
        target=pipeline   → notion-os-pipeline-updater
        target=onboarding → notion-os-onboarding-updater
     on success, add id to the local seen-set
  4. post ONE Slack DM: "Synced N calls. Flagged: <new records / status jumps>."
```

### Component 1 — Producer hook (`scripts/avoma_sync.py`)

After the existing loop builds `pipeline_updates` / `onboarding_updates` (and regardless of Slack success), append a normalized entry per update to the queue. Each entry carries a stable `id` derived from the call so re-runs of the nightly job never enqueue the same call twice (reuse the existing `avoma_sync_seen` UUID as the basis).

- Add `data/notion_updates_queue.jsonl` to the workflow commit-back `git add` list in `.github/workflows/avoma_sync.yml` (alongside `pipeline_cache.json` and `avoma_sync_seen.json`).
- Non-fatal: a queue-write failure must not break the nightly job (wrap like the existing demo-push).

### Component 2 — The queue (`data/notion_updates_queue.jsonl`)

- **Migrate** the current empty `data/notion_updates_queue.json` (`[]`) to **JSONL** named `data/notion_updates_queue.jsonl` — one JSON object per line, append-only.
- Add `data/notion_updates_queue.jsonl merge=union` to `.gitattributes` (same pattern as `tasks.jsonl`) so concurrent appends never conflict.
- Update the gitignore allow-list: `!data/notion_updates_queue.jsonl`.
- Update the existing `queue_notion_update` tool in `processors/query_tools.py` to **append one JSONL line** instead of read-array → mutate → write-whole-array. This fixes a latent lost-write/conflict bug and lets the manual Telegram path and the avoma producer share one queue.

**Unified entry schema:**

```jsonc
{
  "id": "avoma:<call_uuid>",         // stable; basis for idempotency
  "timestamp": "2026-08-13T05:41:00Z",
  "source": "avoma" | "manual",
  "target": "pipeline" | "onboarding",
  "name": "Alina Bushma",            // lead or customer name
  "call_date": "2026-08-12",
  "action": "update",                // manual path may use add_note/update_stage/...
  // pipeline fields
  "inferred_status": "In-Trial / Post Demo",
  "is_new_lead": false,
  "account_owner": "Chris",
  "buying_signals": [...],
  "objections": [...],
  // onboarding fields
  "onboarding_completed": [...],
  "onboarding_next_steps": [...],
  "status_update": "Phase complete — advance to next phase",
  // shared
  "summary": "…",
  "note": "", "stage": "", "follow_up_date": "", "reason": ""   // manual-path passthrough
}
```

The consumer routes on `target`; the updater skills already know how to look up the record by name and apply notes/status.

### Component 3 — The consumer (Cowork scheduled routine)

A recurring scheduled task (`scheduled-tasks` MCP, cron `10 8 * * 1-5` local — off the :00 mark) whose self-contained `SKILL.md` prompt:

1. Runs a small helper to `git pull` origin/main and emit the list of **fresh** entries (queue minus `notion_updates_seen.json`).
2. For each fresh entry, invokes `notion-os-pipeline-updater` or `notion-os-onboarding-updater` with the entry's fields.
3. Records each successfully-applied `id` in the local seen-set.
4. Posts one Slack DM summary via the existing `lib/slack_post` (`open_dm` + `post_message`, `slack_user_id` from config), listing what synced and **flagging** entries where `is_new_lead` is true, a status/stage changed, or a delete occurred.

The deterministic parts (git sync, fresh-entry selection, seen-set update, Slack post) live in thin Python helpers the routine calls; the **Notion writes** go through the LLM updater skills (they need the in-app connector). This keeps the LLM's judgment surface small and the run reliable.

### Component 4 — Idempotency & git flow

- **One-way git:** producer appends to the queue (cloud → origin/main); consumer is **read-only toward git** (pull only, never push).
- **Local seen-set:** `data/state/notion_updates_seen.json` (gitignored, laptop-local) tracks applied `id`s. Mirrors `avoma_sync_seen.json`. This is the dedup authority for the consumer.
- **Bounded queue:** the nightly producer prunes queue lines older than 30 days when it runs, keeping the file small. (Consumer never mutates the committed queue.)

## Failure modes

| Situation | Behavior |
|-----------|----------|
| Laptop/app closed at fire time | Task runs on next app launch (built-in catch-up). |
| Empty / all-seen queue | Silent no-op — no Slack spam. |
| One Notion write fails mid-batch | That `id` is not marked seen → retried next run; report notes the miss. |
| Nightly job re-enqueues same call | Same `id` → consumer skips via seen-set. |
| Concurrent producer append + git merge | `merge=union` on the JSONL → no conflict. |
| Name doesn't match a Notion record | pipeline-updater creates a new record (flagged in report); onboarding-updater surfaces it in the report for manual handling. |

## Rollout

1. **Producer + queue + tool change** (code): add the hook, migrate to JSONL, update `.gitattributes` / gitignore / `queue_notion_update`. Merge and let one nightly run populate the queue.
2. **Consumer helpers** (code): git-sync + fresh-entry selection + seen-set + Slack summary.
3. **Create the Cowork routine** (`scheduled-tasks` MCP) with the self-contained prompt.
4. **First supervised run** — click "Run now", approve every tool the routine touches (Notion read + the updater skills' Notion writes, Bash, Slack post). Approvals persist to the task.
5. **Verify** against a known day: confirm the trackers match the digest and the Slack summary is accurate.
6. Enable the weekday cron. Watch the first few autonomous mornings.

## Testing

- Unit: producer emits one well-formed queue line per update; JSONL append is atomic; `queue_notion_update` appends (no array rewrite); fresh-entry selection excludes seen ids; prune drops >30-day lines.
- Integration (supervised): run the consumer against a seeded queue on a scratch Notion row; confirm idempotency (second run writes nothing) and partial-failure retry.

## Open questions

1. **New-record creation for unmatched onboarding customers** — pipeline-updater creates records for unknown leads; should onboarding do the same automatically, or only flag for manual add? (Leaning: flag-only for onboarding, since onboarding records carry more required fields.)
2. **Report verbosity** — always post a summary, or only when there's something flagged? (Leaning: post whenever ≥1 entry synced; silent when nothing synced.)
3. **Cron time** — is ~8:10am on a weekday reliably after the app is open on Trent's machine? Adjust if his mornings start later.
