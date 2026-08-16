# Handoff: Fix the Registry UI "Pending" tab (person resolution)

**Created:** 2026-06-23 · **Status:** investigation complete, not started
**Goal:** Make the Registry UI "Pending" tab actually show unresolved people and let me resolve them (confirm / assign / new / skip), persisting the result.

> Paste this file into a new session to start. It already contains the root-cause analysis — you don't need to re-discover it, but verify the line numbers (the UI file changes often).

## TL;DR

The Pending tab shows "No Pending Resolutions" even though there's real unresolved-people data committed in git. It's broken in **three independent ways**, and fixing it is a small rebuild, not a one-liner. Decide the approach (below) before coding.

## Background: what "unresolved people" are

`scripts/build_people_registry.py` scans pipeline leads, Avoma/observation participants, and people files. Anything it can't auto-match (no match, or a fuzzy name match 85–99% it won't auto-merge) gets flagged into **`data/people_unresolved.json`** — which **is committed to git** and accumulates over time. Current shape (real data on `origin/main`):

```json
{
  "unresolved": [
    { "entity": "Jeff Davidson", "email": null, "source": "avoma",
      "candidate_id": null, "candidate_score": 0, "added": "2026-05-20" }
  ],
  "previously_notified": [ "...entity strings..." ]
}
```

This is the durable, authoritative list. The tab should be built on it.

## The three problems

### Problem 1 — Tab reads a ghost file as its primary source
[tools/registry_ui.html:1053](tools/registry_ui.html#L1053) loads `data/people_unresolved_state.json` as the **primary** list, and only uses the committed `people_unresolved.json` as **enrichment** joined onto it ([joinUnresolved(), line 1076](tools/registry_ui.html#L1076)):

```js
state.unresolvedState = await readJSON(state.dir, 'data/people_unresolved_state.json') // PRIMARY
state.unresolvedRich  = await readJSON(state.dir, 'data/people_unresolved.json')       // enrichment only
...
function joinUnresolved() {
  if (!state.unresolvedState?.entities?.length) return [];   // <-- bails here, always
  ...
}
```

`people_unresolved_state.json` is **gitignored and was only ever written inside the `person_resolution.yml` CI run** (by `scripts/resolve_observations.py`). On any normal local checkout it doesn't exist → `unresolvedState` is null → `joinUnresolved()` returns `[]` → empty tab. (PR #9, the Telegram→Slack migration, removed that CI write when it retired the Telegram reply loop — but the tab was already disconnected before that, because the UI is main-anchored and the state file was never on `main`.)

### Problem 2 — The tab is on a legacy data path the rest of the app abandoned
Everything else in the UI (tasks, projects, people, notes) goes through the Flask server's origin/main snapshot: `fetchJSON(${API}/api/...)` → [tools/server.py](tools/server.py) `SNAPSHOT` (see `rebuild_snapshot()` ~line 56 and the `/api/*` routes). The Pending tab instead still uses the **old File System Access directory-handle** path (`readJSON(state.dir, ...)`, `writeJSON(state.dir, ...)`).

- `server.py` has **no** unresolved/pending endpoint and **no** SNAPSHOT field for it (confirmed: `grep -n "unresolved\|pending\|resolution" tools/server.py` → nothing).
- **First thing to verify in the new session:** is `state.dir` / `loadData()` even still wired, or is it dead alongside the `/api/bootstrap` path ([line 2707](tools/registry_ui.html#L2707))? `loadData()` does a *required* `readJSON(state.dir, 'data/people_registry.json')` at [line 1050](tools/registry_ui.html#L1050), yet the Registry tab works via `/api/people` — so the dir-handle path may be vestigial. Trace which load path actually runs on boot before you build on either.

### Problem 3 — Decisions go nowhere (the "apply" half doesn't exist)
The Save button writes `data/people_resolution_decisions.json` ([line ~1370](tools/registry_ui.html#L1370)). **Nothing consumes that file** — confirmed: `grep -rn "people_resolution_decisions" --include=*.py .` returns nothing. So even with a working tab, confirming/assigning/creating/skipping a person records intent but never actually resolves anyone (no alias added, no person created, no skiplist entry). The backend that *applies* decisions has to be built or wired — likely into `scripts/build_people_registry.py` (it already has skiplist/alias logic; resolution decisions should feed aliases + a skiplist so resolved/skipped entities stop reappearing).

## Decision points (settle these first — brainstorm before coding)

1. **Data path:** add `GET /api/unresolved` (+ a SNAPSHOT field reading `people_unresolved.json` from origin/main) and a write endpoint for decisions, consistent with the rest of the UI? **(Recommended.)** Or keep the dir-handle path? Recommend the server path — it's the documented architecture (see CLAUDE.md "Registry UI" + memory `project_registry_ui_main_anchored`).
2. **What "resolve" means / where decisions are applied:** confirm→add alias to existing `candidate_id`; assign→link to a chosen person; new→create a person; skip→add to a skiplist so it stops resurfacing. Where does this run — a new endpoint that mutates `people_registry.json` on origin/main (via the existing `mutate()`/`main_storage` write path), or a batch the next `build_people_registry.py` run consumes? Decide before building.
3. **Scope guard:** is the goal just *display* the unresolved list, or the full resolve-and-persist loop? They're separable; you can ship display first.

## Recommended approach (one option, adjust after brainstorming)

1. **Server:** add `people_unresolved` to `SNAPSHOT` (read `people_unresolved.json` from origin/main) + a `GET /api/unresolved` route. Add a write route (`POST /api/unresolved/resolve` or similar) that applies a decision through the main-anchored `mutate()` write path used by tasks/notes.
2. **UI:** make `people_unresolved.json` (`{unresolved: [...]}`) the **primary** source; delete the `people_unresolved_state.json` dependency and the `joinUnresolved()` state-file gate; fetch via `/api/unresolved`. Route Save through the new write endpoint (not `writeJSON(state.dir,...)`).
3. **Apply backend:** implement confirm/assign/new/skip against `people_registry.json` (+ a skiplist), so a resolved entity disappears from `people_unresolved.json` on the next registry rebuild.

## Key files
- [tools/registry_ui.html](tools/registry_ui.html) — `loadData()` (~1048), `joinUnresolved()` (~1076), `renderPendingView()` (~1118), Save (~1360–1372), `state` (~1038), boot/`API` (~1849, ~2707).
- [tools/server.py](tools/server.py) — `SNAPSHOT` / `rebuild_snapshot()` (~48–73), `/api/*` routes; `lib/git_sync.py` + `lib/main_storage.py` for the origin/main read/write pattern.
- [scripts/build_people_registry.py](scripts/build_people_registry.py) — produces `people_unresolved.json`; has the skiplist/alias/fuzzy-match logic (the natural home for "apply").
- `data/people_unresolved.json` (committed), `data/people_registry.json` (committed) — the real data.

## How to run / repro
```bash
# launch the UI (skill: registry-ui) or:
python3 tools/server.py          # Flask on :8787
# open tools/registry_ui.html, go to the Pending tab → currently empty
git show origin/main:data/people_unresolved.json | head   # the data that SHOULD appear
```

## Suggested kickoff for the new session
Use `superpowers:brainstorming` to settle the three decision points above, then `writing-plans`. The architecture constraint to honor: **the Registry UI treats `origin/main` as the single source of truth via `server.py`** (CLAUDE.md "Registry UI" section; memory `project_registry_ui_main_anchored`, `project_registry_pending_tab_disconnected`). Don't reintroduce the local dir-handle path.
