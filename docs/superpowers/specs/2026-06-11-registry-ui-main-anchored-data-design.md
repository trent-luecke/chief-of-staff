# Registry UI — Main-Anchored Data Layer

**Date:** 2026-06-11
**Status:** Design approved, pending spec review
**Scope:** `tools/server.py`, `tools/registry_ui.html` only. No CI consumer changes, no data-format migration.

## Problem

The registry UI's git-as-data layer behaves inconsistently across entity types, causing data loss and "random branch" behavior:

1. **Working-tree clobber + race.** On every page load, `_sync_tasks_from_main` runs a background thread that does `git checkout origin/main -- data/tasks.jsonl`, overwriting (and staging) the file in whatever branch is checked out. This destroys any `tasks.jsonl` content not yet on `origin/main`, and because it races the API read, what the UI shows depends on timing. (Observed live: 7 uncommitted tasks were wiped by a page load.)

2. **Inconsistent write targets.** Only task writes go to `main` (via `_git_push_tasks`'s worktree mechanism). Projects, notes, and note-tags write to the **current branch** via `_git_commit_push`. So a task's `project_id` can reference a project that exists only on a feature branch while the task lives on `main`.

3. **Reads come from the working tree** (current branch) for all five datasets, while only `tasks.jsonl` is force-synced from `main` — three different behaviors in one app.

### Why `main` is the canonical home

All CI consumers operate on `main`: the 7am daily brief (`brief.py`, `pipeline.py`), the Telegram bot (`query_tools.py`), Avoma processing (`avoma_phase2.py`), and Slack task-add (`slack_add_task.py`) all read/write these files in GitHub Actions and commit back to `main`. The local UI (running on a feature branch) is the only actor that diverges. Therefore the fix is to make the UI honest about `main` being the single source of truth — not to introduce a second store.

### Approach decision

Considered: (1) fix git-as-data properly, (3) replace with a local SQLite store + sync bridge to `main`. Chose **Option 1**. Rationale: single-user tool, occasional edits, and the data's real home is unavoidably git-on-`main` because CI lives there. SQLite would add a permanent two-store reconciliation problem to solve a concurrency risk that barely exists here. The observed bugs are wiring mistakes, not inherent to git-as-data.

## Model

**One rule: `main` is the only data home. The UI reads from `main` into memory and writes back to `main` — never the working tree, never the current branch.**

| Concern | Today | New |
|---|---|---|
| Reads (tasks, projects, people, notes, tags) | working tree (current branch) | in-memory snapshot sourced from `origin/main` |
| Tasks writes | worktree → `main` | worktree → `main` (unchanged) |
| Projects / notes / tags writes | `_git_commit_push` → current branch | worktree → `main` |
| Freshness | background thread clobbers `tasks.jsonl` on page load | snapshot rebuilt on page load + **Refresh** button |
| Offline | partial timeout handling | connectivity-gated: writes blocked + banner |

The working-tree `git checkout origin/main -- …` is **deleted entirely**. The UI no longer interacts with the checked-out branch at all.

## Read path

A single in-memory snapshot built from `origin/main` serves every GET.

```
build_snapshot():
    online = git_fetch_main(timeout=8s)        # success/failure IS the online signal
    for each file (tasks.jsonl, projects_registry.json,
                   people_registry.json, notes.jsonl, notes_tags.json):
        raw = `git show origin/main:data/<file>`   # reads the committed blob; no working-tree touch
        parse into memory (replay jsonl logs; json.load the JSON files)
    return snapshot{ data..., online, fetched_at }
```

**Built when:** once on page load (HTML calls `GET /api/bootstrap`); on each **Refresh** click; and immediately after a successful write (refreshed from the just-pushed `origin/main`).

**Served:** every GET (`/api/tasks`, `/api/projects`, `/api/people`, `/api/registry`, `/api/notes`, `/api/notes/tags`) reads from the snapshot — instant, no network, no current-branch disk access.

**Offline / fetch failure:** fall back to `git show origin/main:…` against the last-fetched `origin/main` ref and mark `online=false` — last-known data is still shown. First load with no prior fetch and no network → empty datasets, `online=false`.

`git show origin/main:data/<file>` reads the committed blob directly and never modifies checked-out files. The snapshot lives in Flask process memory; a server restart rebuilds it on next load (no persistence needed).

## Write path

All mutations route through one generalized writer (promoting today's `_git_push_tasks` to all datasets):

```
write_to_main(file, mutate_fn, commit_msg):
    if not git_fetch_main(timeout): return {status: "offline"}   # gated before this too (see Connectivity)
    worktree = git worktree add --detach <tmp> origin/main
    current   = read `file` from worktree (origin/main's version)
    new       = mutate_fn(current)        # apply change to MAIN's latest, not a stale local copy
    write new into worktree
    git -C worktree add + commit + push HEAD:refs/heads/main
    remove worktree
    rebuild snapshot from new origin/main
    return {status: "ok", ...}
```

`mutate_fn` applies the change to `main`'s current version, handling two file shapes:

- **Append-only logs (`tasks.jsonl`, `notes.jsonl`):** append the new event line(s). Union-merge (already built for tasks) means concurrent CI writes coexist — both line sets survive. Inherently safe.
- **Whole-file JSON (`projects_registry.json`, `notes_tags.json`):** `json.load` main's current file → apply structured add/edit/delete → `json.dump`. Re-reading `main` immediately before writing shrinks the clobber window to truly-simultaneous writes only — negligible for rarely-edited projects/tags. **No format migration.**

**Cascade** (`DELETE /api/projects/<id>` also completes its tasks): both the project-registry mutation and the task completions go through `write_to_main` to `main`, removing today's split where the two halves land on different branches.

This replaces `_git_commit_push` for all data writes; `_git_commit_push`-to-current-branch is removed for data files.

## Connectivity gating (block-when-offline)

One signal, derived from the `git fetch origin main` that already runs on load/refresh/write.

**Server:**
- `build_snapshot` and `write_to_main` both attempt a bounded `git fetch origin main`; its success/failure is the online signal (no separate health check).
- `GET /api/bootstrap` returns `{ online, fetched_at, tasks, projects, people, notes, tags }`.
- Every write endpoint re-checks first: a failed pre-write fetch returns `503 {status:"offline"}` and makes **no commit attempt** — a failed write is impossible, not merely handled.

**UI (`registry_ui.html`):**
- Read `online` from bootstrap on load and each Refresh.
- **Offline:** persistent banner ("⚠ Offline — can't reach `main`. Showing last-known data; editing disabled.") and all create/edit/complete/delete controls disabled. Refresh stays enabled (re-checks connectivity).
- **Online:** banner hidden, controls enabled.
- Defense in depth: a `503` mid-session flips the UI to offline state until the next successful Refresh.

This makes the observed failure mode impossible: when `main` is unreachable the UI won't start the edit and the server won't accept it, so no change can be stranded in an uncommitted working tree.

## Changes vs. unchanged

**Changes (2 files):**
- `tools/server.py` — delete `_sync_tasks_from_main` + the `/` background thread; remove `_git_commit_push` for data files; add `build_snapshot()`, a `MainSnapshot` holder, generalized `write_to_main(file, mutate_fn, msg)`, and `GET /api/bootstrap`; rewrite all GETs to serve from the snapshot and all writes to route through `write_to_main`.
- `tools/registry_ui.html` — call `/api/bootstrap` on load; add a **Refresh** button; add the offline banner + write-control disabling.

**Unchanged:** `lib/tasks.py`, `lib/projects.py`, `lib/notes.py` (pure mutation logic reused as `mutate_fn` bodies); all CI consumers; every data-file format.

## Error handling

- Bounded `git fetch` (8s) — failure → `online=false`, serve last-known blob, block writes.
- Worktree removed in a `finally` (today's pattern), plus `git worktree prune` on server startup to clean orphans from a hard crash.
- Push failure after a passing pre-check → `503`, no partial state (the worktree commit is local-only until push; failed push reaches nothing on `main`).
- Malformed/missing file on `main` → treat as empty dataset, log a warning, don't crash the snapshot.

## Testing

- **Unit:** each `mutate_fn` (append-line; JSON add/edit/delete) — pure functions, no git.
- **Unit:** snapshot parsing (jsonl replay + JSON load) from a fixture blob.
- **Integration (mock `subprocess`):** `write_to_main` happy path; offline path (fetch fails → no commit); union-merge with a concurrent remote line.
- **Manual smoke:** create/complete/delete a task + project + note online, verify on `origin/main`; drop the network and confirm banner + disabled controls + clean Refresh recovery.
