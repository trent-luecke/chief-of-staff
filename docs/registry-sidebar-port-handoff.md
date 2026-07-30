# Registry Sidebar Reskin — Port Handoff

Reads this next: **give this whole file to the new session as its first message** (or paste the "Kickoff prompt" section at the bottom). It has everything needed to port the approved sidebar-nav + Airtable-inspired reskin from a design-preview mockup into the real `tools/registry_ui.html`.

## What's approved and where it lives

| Artifact | Location |
|---|---|
| Design spec (decisions + rationale) | [`docs/superpowers/specs/2026-07-29-registry-sidebar-reskin-design.md`](superpowers/specs/2026-07-29-registry-sidebar-reskin-design.md) |
| Implementation plan (built the mockup) | [`docs/superpowers/plans/2026-07-29-registry-sidebar-reskin.md`](superpowers/plans/2026-07-29-registry-sidebar-reskin.md) |
| **Reference implementation** (the actual approved HTML/CSS/JS — read this first) | [`docs/registry-sidebar-mockup-reference.html`](registry-sidebar-mockup-reference.html) |
| Published interactive preview (Trent reviewed and approved this) | https://claude.ai/code/artifact/0bfdb3b2-8fd6-4aac-ae15-abfcb62fd942 |

**Why a reference HTML file exists in the repo:** the mockup was built and verified in a prior session's temporary scratchpad directory, which does not survive into a new session. The file at `docs/registry-sidebar-mockup-reference.html` is a byte-identical copy of what Trent actually approved — treat it as the source of truth for exact CSS token values, icon SVGs, and JS structure, not the design spec's prose (the spec is faithful but the reference file is literal).

## What this is NOT

- The reference file is a standalone mockup with **hardcoded sample data** (`PEOPLE_SAMPLE`, `WORK_DATA`) — it has no real data binding, no server calls, and no add/edit/merge functionality wired up. Porting means replacing that sample data and rendering logic with calls into the real app's existing state and render functions — not copying the file wholesale.
- Nothing in the real `tools/registry_ui.html` has been touched yet. This port has not started.

## The porting task, concretely

### 1. Replace the top tab bar with the rail

Real file: `tools/registry_ui.html`

- Current tab markup: lines ~1041-1049 (`<nav class="tabs">...`), 7 buttons: `today, pending, registry, observations, work, notes, meetings`. Note the real app has an **`observations`** tab that the mockup's 6-item rail doesn't include (the mockup was scoped to Today/Pending/People/Work/Notes/Meetings — Observations wasn't part of the sidebar brainstorm). Decide with Trent whether Observations becomes a 7th flat rail item (recommended: yes, same as it is today, just moved) — don't drop it silently.
- Current click-dispatch: `setupTabs()` at line ~3122 (`document.querySelectorAll('.tab').forEach(...)`, calls `switchTab(view)` then one `if (view === 'x') renderXView()` per tab).
- Current active-state + show/hide logic: `switchTab(name)` at line ~1900 — toggles `.active` on the clicked tab and toggles `.hidden` on each `#view-{name}` container.
- **Port plan:** replace the `.tabs` nav markup with the mockup's rail markup structure (`.rail`, `.rail-item` — see reference file's `SECTIONS` array and `renderRail()`), keep `switchTab()`'s hide/show logic mostly as-is (it doesn't care whether the trigger was a tab or a rail button), and add the sub-panel container + logic (see below) only for `registry` (People) and `work`.

### 2. Add the sub-panel for People and Work only

The reference file's `renderSubpanel()` pattern (checks `SECTIONS.find(s => s.id === activeSection).hasChildren`) is the model. In the real app:
- **People sub-panel filters:** All People / Leads / Customers / Partners / Internal / Unknown, filtering by the existing `type` field already used for badges in `renderRegistryView()` (real file, ~line 1770). Currently `renderRegistryView(filter = '')` filters by a text search string against name/alias/email — you'll need to either add a second filter parameter for `type`, or thread the sub-panel's selected type through as an additional predicate alongside the existing text search (don't replace text search — People's search box is real functionality the mockup deliberately left in place).
- **Work sub-panel filters:** All Work / Projects / Standalone / Routines, matching `renderWorkView()`'s existing three groupings (real file, ~line 2743 — it already renders Projects, a Standalone section, and Routines; check the exact section boundaries there before assuming the mockup's grouping names match 1:1). This is very likely a matter of conditionally skipping sections based on the active sub-filter, not building new logic.

### 3. Apply the theme

Reference file's `:root`-adjacent `#stage` custom properties (see the `<style>` block, search for `--canvas`) are the exact approved token values:
```
--canvas:#fdfdfc; --ink:#181d26; --body-c:#333840; --muted:#767b85;
--hairline:#e3e3e0; --surface-soft:#f7f6f3; --surface-strong:#ececea;
--accent:#0a5c3d; --accent-soft:#e2f0ea;
```
The real file's current `:root` block (line ~7) has the old dark theme (`--bg:#0f0f0f`, `--accent:#4a9eff`, etc.) — this is a straightforward token swap for most of the file.

**Badge colors need real values verified — do not assume they carry over unchanged.** The real file's current badge tokens are flat hues meant for a near-black background (`--lead:#3b82f6`, `--customer:#22c55e`, `--partner:#f59e0b`, `--internal:#6b7280`, `--unknown:#ef4444`, each used at `rgba(hue,.2)` background per `.badge-*` class — check the real file's `.badge-lead` etc. rules directly, they aren't all in one place). The mockup does **not** reuse these hex values — it has its own light-canvas-appropriate pastel bg/fg pairs instead:
```
--b-lead-bg:#e6eefc      --b-lead-fg:#1c5fc9
--b-customer-bg:#e3f3ea  --b-customer-fg:#0e7a4f
--b-partner-bg:#fcefdc   --b-partner-fg:#a9720d
--b-internal-bg:#eceded  --b-internal-fg:#68707a
--b-unknown-bg:#fbe4e1   --b-unknown-fg:#c23b2d
```
These pastel pairs are what Trent actually saw and approved (confirmed in the brainstorming round's aesthetic mockup and again in the final artifact) — they are the values to port in, replacing the real file's current dark-theme badge rgba/hue combo, not preserving it. The signature forest accent (`--accent:#0a5c3d`) stays a separate, distinct color from all five of these — never applied to a badge.

### 4. Icon set

The reference file's `ICONS` object has 6 hand-built SVGs (today/pending/people/work/notes/meetings), all sharing one visual language (20x20 viewBox, `stroke-width:1.6`, rounded caps). If Observations becomes a 7th rail item, a 7th icon needs to be designed in the same style — don't reuse or approximate one of the existing 6.

## Explicitly out of scope for this port (per the original spec)

- No new functionality — every button, form, and action that works today in the real app must keep working exactly as it does now.
- Deciding whether Observations, Notes, or Meetings ever get their own sub-panels later is **not** part of this port — only People and Work get one, per the approved spec.

## Suggested approach for the new session

Given this is now a real, non-trivial change to a ~4,100-line production file (not a throwaway mockup), recommend re-entering brainstorming briefly to confirm the Observations-tab question above with Trent, then `superpowers:writing-plans` for a proper task-by-task plan, then `superpowers:subagent-driven-development` or `superpowers:executing-plans` to execute — same pattern used to build the mockup, but this time the tasks touch a real git-tracked file, so normal commit/review/branch discipline applies (unlike the mockup, which had no git involved at all).

---

## Kickoff prompt (paste this as your first message in the new session)

```
I approved a sidebar-nav + Airtable-inspired reskin for the People Registry as a mockup in a prior
session. Now I want to port it into the real tools/registry_ui.html. Read
docs/registry-sidebar-port-handoff.md first — it has the design spec, the plan that built the
mockup, the exact reference HTML/CSS/JS to port from, and the specific real-file line numbers/
functions this touches (switchTab, setupTabs, renderRegistryView, renderWorkView, the :root theme
tokens). One open question flagged in the handoff doc: the mockup's 6-item rail didn't include the
real app's "Observations" tab — decide with me whether it becomes a 7th flat rail item before
planning further. Then walk me through brainstorming → plan → execution for the real port.
```
