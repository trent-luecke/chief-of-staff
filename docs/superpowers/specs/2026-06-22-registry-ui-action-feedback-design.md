# Registry UI — Action Feedback Layer

**Date:** 2026-06-22
**Status:** Approved — ready for implementation plan
**Scope:** Single-file change to `tools/registry_ui.html`

## Problem

When you action something in the Registry UI — mark a task done, delete a task,
change an owner or due date, add an agenda item, save a session — the UI gives no
indication that anything is happening during the network round-trip. The request
processes silently, then the whole view rebuilds at once. The result feels like
"nothing happened, then it snapped." There's no in-flight signal and no success
confirmation.

The actions funnel through a small number of mutation helpers, so a centralized
fix covers all of them cheaply.

## Decision

Build a **Saving → Saved feedback arc** (chosen over optimistic UI and a
both/hybrid approach). The instant you act, the UI shows that a save is in flight;
on completion it confirms success, or surfaces a clear error on failure. The
existing full re-render stays — it now lands *after* "Saving → Saved," so the
change reads as the expected end of an action rather than an unexplained jump.

Explicitly **out of scope:** optimistic DOM updates, undo, and reworking the
re-render strategy.

## Architecture

Three small pieces, all added to `tools/registry_ui.html`.

### 1. Toast — `toast(msg, kind)`

- A single fixed-position container, **bottom-right**.
- `toast('Saved', 'success')`, `toast('Failed: …', 'error')`, and a transient
  `'pending'` kind for "Saving…".
- Fade + slide in via CSS.
- Auto-dismiss: success ~2s, error ~5s (errors linger so they aren't missed).
- Stacks if multiple fire; newest on top or bottom (implementer's call —
  bottom-anchored stack is fine).
- One function, reused everywhere. No external dependencies — plain DOM + CSS,
  consistent with the rest of this self-contained HTML file.

### 2. Per-element busy state

- The element that was clicked (button / row / chip) gets a `.busy` class the
  instant the action starts.
- Visual: subtle dim (reduced opacity) plus a small inline spinner. For buttons,
  this composes with the existing `disabled` handling.
- Cleared when the request settles. If the element is about to be removed by a
  re-render anyway (e.g. a deleted row), clearing is moot — the rebuild replaces it.

### 3. Centralized arc in the mutation helpers

This is the key move: rather than editing ~20 call sites, wire the arc into the
two functions every mutating request already passes through.

- **`fetchJSON(url, opts)`** (`tools/registry_ui.html:1867`) — the primary helper
  for tasks, projects, people, notes.
- **`patchMeeting(method, path, payload)`** (`tools/registry_ui.html:3321`) — the
  meetings-doc helper for agenda / threads / sessions.

For any non-GET request, the helper automatically:
1. Shows a "Saving…" indication on start.
2. On success → "✓ Saved" success toast.
3. On failure → error toast (replacing the current silent-catch / `alert`
   behavior).

Each call site may pass an **optional label** for a friendlier message; the helper
falls back to a generic "Saved". Suggested label map:

| Action | Label |
|--------|-------|
| complete task | Task completed |
| delete task | Task deleted |
| due / owner / project change | Task updated |
| add task | Task added |
| agenda add/delete | Agenda updated |
| thread add/toggle | Threads updated |
| session save | Session saved |
| project create / edit / delete | Project created / updated / deleted |
| person merge / edit | Person updated |

The label is passed via `opts` on `fetchJSON` (e.g. `opts.label`) and as an extra
argument or field on `patchMeeting`. Implementation should keep the existing
offline/503 handling in `fetchJSON` intact — offline still throws and shows the
offline chrome; the arc applies to requests that actually go out.

### Per-element wiring

The helper drives the global toast arc on its own. The `.busy` class is applied at
the call sites that have a reference to the clicked element (the click handlers in
the task/project/meeting list containers). Where a handler has no convenient
element reference, the toast alone is sufficient — the busy class is an
enhancement, not a requirement for every action.

## Bug fixed as a side effect

Several handlers currently do `await fetchJSON(...).catch(() => {})` and then
re-render unconditionally — e.g. task **delete** (`tools/registry_ui.html:2098`),
due-date and owner patches (`:2107`, `:2118`), project delete (`:2515`), and the
standalone-task owner change (`:2550`). Today a failed server push is swallowed and
the view rebuilds as if it succeeded — a **phantom success**.

Routing failures through the centralized error toast means a failed write surfaces
visibly instead of silently looking done. As part of this work, those silent
`.catch(() => {})` swallows are removed or converted so the error reaches the arc.
The scattered `alert('Failed…')` calls are replaced with the error toast for
consistency.

Note: the re-render after a failed write may still occur; the important change is
that the user *sees the failure*. (Whether to skip the re-render on failure is a
minor implementation detail — surfacing the error is the requirement.)

## Error handling

- Network / server errors → error toast with the failure message, element
  un-busied.
- Offline (503 / `state.online === false`) → existing offline chrome continues to
  govern; the arc does not need to duplicate it, but a write attempted while
  offline should still produce a clear, non-success signal (the existing thrown
  error is fine to route into an error toast).

## Testing

Manual, against the running UI on port 8787 (launch via the `registry-ui` skill or
`python3 tools/server.py`):

1. **Success path** — perform a real action (e.g. add then complete a task) and
   confirm: per-element busy spinner appears, "Saving…" shows, "✓ Saved" toast
   confirms, view rebuilds cleanly after.
2. **Error path** — toggle the UI offline (or stop the server) and attempt a
   write; confirm an error toast appears and no phantom success.
3. **Coverage spot-check** — exercise at least one action from each surface: task,
   project, meeting agenda/session, person.

No automated test harness exists for this HTML file; verification is manual.

## Files touched

- `tools/registry_ui.html` — CSS for toast + `.busy`; `toast()` function; busy
  helper; changes to `fetchJSON` and `patchMeeting`; optional labels and `.busy`
  application at click-handler call sites; replace `alert('Failed…')` and silent
  `.catch(() => {})` swallows.
