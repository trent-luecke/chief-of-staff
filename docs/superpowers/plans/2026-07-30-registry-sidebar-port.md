# Registry Sidebar Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the approved sidebar-nav + Airtable-inspired reskin from `docs/registry-sidebar-mockup-reference.html` into the real `tools/registry_ui.html` — replacing the top tab bar with an icon rail, adding People/Work sub-panels, and swapping the dark theme for the approved light theme — with zero loss of existing functionality.

**Architecture:** `tools/registry_ui.html` is a single-file static app (HTML + CSS + vanilla JS, no build step, no test harness) served by `tools/server.py` on port 8787. All changes are inline edits to this one file: a `:root` CSS token swap, a markup change from `<nav class="tabs">` to `<nav class="rail">` + `#subpanel-container`, and small additions to existing JS functions (`switchTab`, `renderRegistryView`, `renderWorkView`). No new files, no new endpoints, no server-side changes.

**Tech Stack:** Vanilla JS (ES modules), hand-written CSS custom properties, Flask dev server (`tools/server.py`) for local preview only.

## Global Constraints

- Every button, form, and action that works today in `tools/registry_ui.html` must keep working exactly as it does now — this is a nav + visual port, not a feature change.
- Exact CSS token values come from `docs/registry-sidebar-mockup-reference.html` (the literal source of truth, not the design spec's prose): `--canvas:#fdfdfc; --ink:#181d26; --body-c:#333840; --muted:#767b85; --hairline:#e3e3e0; --surface-soft:#f7f6f3; --surface-strong:#ececea; --accent:#0a5c3d; --accent-soft:#e2f0ea`.
- Badge pastel pairs (replace the old flat-hue badges, do not preserve old hex values): `--b-lead-bg:#e6eefc/--b-lead-fg:#1c5fc9`, `--b-customer-bg:#e3f3ea/--b-customer-fg:#0e7a4f`, `--b-partner-bg:#fcefdc/--b-partner-fg:#a9720d`, `--b-internal-bg:#eceded/--b-internal-fg:#68707a`, `--b-unknown-bg:#fbe4e1/--b-unknown-fg:#c23b2d`.
- Only **People** and **Work** get sub-panels. Today, Pending, Notes, Meetings stay flat single-click, identical to today.
- **Observations decision (confirmed with Trent 2026-07-30):** dropped from the rail entirely for this port — no rail button, no replacement affordance. Trent explicitly accepted that the Observations view becomes unreachable in the UI until a later round adds it back. `#view-observations` and `renderObservationsView()` are left fully intact in the code — only the nav entry point is removed — so restoring access later is a one-line addition, not a rebuild.
- No automated test suite exists for this file. "Testing" in this plan means: run `tools/server.py`, load the app in a browser, and manually verify via screenshots/console/DOM inspection. Use the Browser pane tools (`preview_start`, `navigate`, `read_page`, `read_console_messages`, `computer` screenshot) for this, not a test runner.
- Out of scope, confirmed by grep, intentionally untouched: `--success`/`--danger` tokens, `.badge-active` (project status, not people type), and all pre-existing hardcoded feature colors unrelated to the reskin (`#818cf8`, `#6d28d9`, `#ede9fe`, `#e0f2fe`, `#0369a1`, `#c4b5fd`, `#8b8b94`, `#555555` tag-picker defaults, `#ddd` dashed border, etc. — these belong to unrelated features like horizon chips and note tags and are not part of the approved reskin spec).
- Minor design call made in this plan (not explicitly specified upstream, flag to Trent if he disagrees): the People sub-panel's type filter and the Work sub-panel's section filter **persist** when navigating away and back (they are module-level state, not reset to "All" on every re-entry the way the throwaway mockup did). This avoids silently discarding a filter Trent was mid-task on.

---

### Task 1: Theme tokens + badge colors

**Files:**
- Modify: `tools/registry_ui.html:7-22` (`:root` block)
- Modify: `tools/registry_ui.html:88` (`.btn-primary:hover`)
- Modify: `tools/registry_ui.html:90` (`.btn:hover:not(:disabled)`)
- Modify: `tools/registry_ui.html:104` (`.btn-save:hover:not(:disabled)`)
- Modify: `tools/registry_ui.html:218-222` (`.badge-lead`/`.badge-customer`/`.badge-partner`/`.badge-internal`/`.badge-unknown`)
- Modify: `tools/registry_ui.html:433` (`.badge-archived`)
- Modify: `tools/registry_ui.html:497` (`.btn-add-task:hover`)

**Interfaces:**
- Produces: new canonical CSS variables (`--canvas`, `--ink`, `--body-c`, `--hairline`, `--surface-soft`, `--surface-strong`, `--accent-soft`, `--b-*-bg`/`--b-*-fg`) that Task 2's rail/subpanel CSS (added in Task 2) will reference directly.
- Consumes: nothing from other tasks. This task is fully self-contained and independently testable — no other task depends on it beyond referencing the variable names it introduces.

There are ~278 existing `var(--bg)`/`var(--surface)`/`var(--surface2)`/`var(--border)`/`var(--text)`/`var(--muted)`/`var(--accent)` call sites throughout the file. Rather than touch all of them, this task keeps those variable *names* and re-points their *values* by aliasing them to the new canonical tokens inside `:root` — one edit, zero risk to the other 278 call sites.

- [ ] **Step 1: Replace the `:root` token block**

Find this exact block at the top of the `<style>` section (lines 7-22):

```css
    :root {
      --bg: #0f0f0f;
      --surface: #181818;
      --surface2: #202020;
      --border: #2c2c2c;
      --text: #ddd;
      --muted: #666;
      --accent: #4a9eff;
      --success: #22c55e;
      --danger: #ef4444;
      --lead: #3b82f6;
      --customer: #22c55e;
      --partner: #f59e0b;
      --internal: #6b7280;
      --unknown: #ef4444;
    }
```

Replace it with:

```css
    :root {
      /* Airtable-inspired light theme, approved 2026-07-29.
         See docs/superpowers/specs/2026-07-29-registry-sidebar-reskin-design.md
         and docs/registry-sidebar-mockup-reference.html (literal source of truth). */
      --canvas: #fdfdfc;
      --ink: #181d26;
      --body-c: #333840;
      --muted: #767b85;
      --hairline: #e3e3e0;
      --surface-soft: #f7f6f3;
      --surface-strong: #ececea;
      --accent: #0a5c3d;
      --accent-soft: #e2f0ea;

      /* Legacy names kept so the ~280 existing var() call sites elsewhere in
         this file don't need to change individually. */
      --bg: var(--canvas);
      --surface: var(--surface-soft);
      --surface2: var(--surface-strong);
      --border: var(--hairline);
      --text: var(--body-c);
      --success: #22c55e;
      --danger: #ef4444;

      --b-lead-bg: #e6eefc;     --b-lead-fg: #1c5fc9;
      --b-customer-bg: #e3f3ea; --b-customer-fg: #0e7a4f;
      --b-partner-bg: #fcefdc;  --b-partner-fg: #a9720d;
      --b-internal-bg: #eceded; --b-internal-fg: #68707a;
      --b-unknown-bg: #fbe4e1;  --b-unknown-fg: #c23b2d;
    }
```

- [ ] **Step 2: Fix the three hardcoded hover shades tied to the old blue accent**

These are hover states for buttons whose base background is `var(--accent)` — they were hardcoded to a darkened blue and must become a darkened forest so hover doesn't flash blue on a green button.

Replace (line 88):
```css
    .btn-primary:hover { background: #3a8eef; }
```
with:
```css
    .btn-primary:hover { background: #084e34; }
```

Replace (line 104):
```css
    .btn-save:hover:not(:disabled) { background: #3a8eef; }
```
with:
```css
    .btn-save:hover:not(:disabled) { background: #084e34; }
```

Replace (line 497):
```css
    .btn-add-task:hover { background: #3a8eef; }
```
with:
```css
    .btn-add-task:hover { background: #084e34; }
```

- [ ] **Step 3: Fix the hardcoded dark hover shade on the secondary button**

Replace (line 90):
```css
    .btn:hover:not(:disabled) { background: #2a2a2a; }
```
with:
```css
    .btn:hover:not(:disabled) { background: #e2e1dd; }
```

- [ ] **Step 4: Replace the 5 badge-type rules with the pastel token pairs**

Replace (lines 218-222):
```css
    .badge-lead { background: rgba(59,130,246,.2); color: var(--lead); }
    .badge-customer { background: rgba(34,197,94,.2); color: var(--customer); }
    .badge-partner { background: rgba(245,158,11,.2); color: var(--partner); }
    .badge-internal { background: rgba(107,114,128,.2); color: var(--internal); }
    .badge-unknown { background: rgba(239,68,68,.2); color: var(--unknown); }
```
with:
```css
    .badge-lead { background: var(--b-lead-bg); color: var(--b-lead-fg); }
    .badge-customer { background: var(--b-customer-bg); color: var(--b-customer-fg); }
    .badge-partner { background: var(--b-partner-bg); color: var(--b-partner-fg); }
    .badge-internal { background: var(--b-internal-bg); color: var(--b-internal-fg); }
    .badge-unknown { background: var(--b-unknown-bg); color: var(--b-unknown-fg); }
```

- [ ] **Step 5: Fix `.badge-archived`, which also referenced the now-removed `--internal` var**

Replace (line 433):
```css
    .badge-archived { background: rgba(107,114,128,.2); color: var(--internal); }
```
with:
```css
    .badge-archived { background: var(--b-internal-bg); color: var(--b-internal-fg); }
```

- [ ] **Step 6: Verify no remaining references to the removed badge-hue variables**

Run:
```bash
grep -n "var(--lead)\|var(--customer)\|var(--partner)\|var(--internal)\|var(--unknown)" tools/registry_ui.html
```
Expected: no output (all five were only ever used in the 6 lines just replaced).

- [ ] **Step 7: Manual verification in browser**

Start the server and open the app (use the Browser pane's `preview_start` with `{name: "registry-ui"}` if `.claude/launch.json` has an entry, otherwise run `python3 tools/server.py` via Bash in the background and `preview_start` with `{url: "http://localhost:8787"}`).

Check:
- Page background is off-white/cream, not black.
- Buttons that used to be blue (`.btn-primary`, `.btn-save`, `.btn-add-task`) are now forest green (`#0a5c3d`) with white text.
- Open the People tab — badges show pastel backgrounds (light blue/green/amber/gray/red) with darker matching text, not the old saturated-hue-on-transparent look.
- Open the Work tab — an archived project's badge (if any exist in test data) shows the same gray pastel as Internal people badges.
- `read_console_messages` shows no new errors.

- [ ] **Step 8: Commit**

```bash
git add tools/registry_ui.html
git commit -m "Registry UI: swap dark theme tokens for approved Airtable-inspired light palette"
```

---

### Task 2: Rail nav shell (replaces the top tab bar)

**Files:**
- Modify: `tools/registry_ui.html:107-130` (`#app`, `.tabs`, `.tab` CSS rules)
- Modify: `tools/registry_ui.html:1040-1050` (`<nav class="tabs">` markup)
- Modify: `tools/registry_ui.html:1900-1907` (`switchTab()`)
- Modify: `tools/registry_ui.html:3122-3135` (`setupTabs()`)

**Interfaces:**
- Produces: `#subpanel-container` (empty `<div>`, starts `hidden`), `renderSubpanel(name)` function — Tasks 3 and 4 each add one `else if` branch to this function's body (or, as written below, it looks for `typeof renderPeopleSubpanel/renderWorkSubpanel === 'function'`, so Tasks 3/4 need zero further edits to this function — see Step 4).
- Consumes: nothing from Task 1 directly (different lines), but must land after Task 1 since it references `var(--surface-soft)` etc. by name in new CSS it adds.

This task intentionally keeps the existing **static markup + `data-view` attribute** pattern instead of porting the mockup's dynamic `SECTIONS`/`renderRail()` JS — the real file's `switchTab()`/`setupTabs()` already work by querying `data-view` on whatever has the relevant class, so only the class names and visual structure change. This is the lowest-risk read of the handoff's instruction to keep `switchTab()`'s hide/show logic "mostly as-is."

- [ ] **Step 1: Replace the `#app`/`.tabs`/`.tab` CSS rules with rail + sub-panel CSS**

Replace (lines 107-130):
```css
    #app { display: flex; flex-direction: column; min-height: 100vh; }
    .tabs {
      display: flex;
      gap: 2px;
      padding: 10px 16px 0;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .tab {
      background: none;
      color: var(--muted);
      padding: 7px 14px;
      border-radius: 4px 4px 0 0;
      border: 1px solid transparent;
      border-bottom: none;
      font-size: 13px;
    }
    .tab.active {
      background: var(--bg);
      color: var(--text);
      border-color: var(--border);
    }
    .tab:hover:not(.active) { color: var(--text); }
```
with:
```css
    #app { display: flex; flex-direction: row; min-height: 100vh; }
    .rail {
      width: 176px; flex-shrink: 0; background: var(--surface-soft);
      border-right: 1px solid var(--hairline); padding: 14px 10px;
      display: flex; flex-direction: column; gap: 2px;
    }
    .rail-item {
      display: flex; align-items: center; gap: 10px; padding: 8px 10px;
      border-radius: 7px; font-size: 13px; color: var(--muted);
      cursor: pointer; border: none; background: none; font: inherit;
      width: 100%; text-align: left;
    }
    .rail-item:hover { background: var(--surface-strong); }
    .rail-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
    .rail-item .ic { width: 18px; height: 18px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
    .rail-item .ic svg { width: 16px; height: 16px; }
    #subpanel-container {
      width: 170px; flex-shrink: 0; background: var(--canvas);
      border-right: 1px solid var(--hairline); padding: 14px 12px;
    }
    #subpanel-container.hidden { display: none; }
    .subpanel-label {
      font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase;
      color: var(--muted); font-weight: 600; margin-bottom: 8px;
    }
    .sub-item {
      display: block; width: 100%; text-align: left; padding: 6px 8px; margin-bottom: 1px;
      border-radius: 6px; font-size: 13px; color: var(--body-c);
      cursor: pointer; border: none; background: none; font: inherit;
    }
    .sub-item:hover { background: var(--surface-soft); }
    .sub-item.active { background: var(--surface-strong); color: var(--ink); font-weight: 600; }
```

- [ ] **Step 2: Replace the tab-bar markup with the rail markup**

Replace (lines 1040-1050):
```html
  <div id="app" class="hidden">
    <nav class="tabs">
      <button class="tab active" data-view="today">Today</button>
      <button class="tab" data-view="pending">Pending <span id="pending-count"></span></button>
      <button class="tab" data-view="registry">People</button>
      <button class="tab" data-view="observations">Observations</button>
      <button class="tab" data-view="work">Work</button>
      <button class="tab" data-view="notes">Notes</button>
      <button class="tab" data-view="meetings">Meetings</button>
    </nav>
    <main>
```
with:
```html
  <div id="app" class="hidden">
    <nav class="rail">
      <button class="rail-item active" data-view="today"><span class="ic"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="7.5"/><path d="M10 6v4l2.8 2.8"/></svg></span>Today</button>
      <button class="rail-item" data-view="pending"><span class="ic"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9h4.2l1.3 2.4h2.9L12.7 9H17"/><path d="M3 9V5.6C3 5 3.5 4.5 4.1 4.5h11.8c.6 0 1.1.5 1.1 1.1V9"/><path d="M3 9v5.4c0 .6.5 1.1 1.1 1.1h11.8c.6 0 1.1-.5 1.1-1.1V9"/></svg></span>Pending <span id="pending-count"></span></button>
      <button class="rail-item" data-view="registry"><span class="ic"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="7" r="3"/><path d="M4 17c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/></svg></span>People</button>
      <button class="rail-item" data-view="work"><span class="ic"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5.5" width="12" height="10.5" rx="1.3"/><path d="M7.5 5.5V4.3c0-.6.5-1.1 1.1-1.1h2.8c.6 0 1.1.5 1.1 1.1v1.2"/><path d="M4 9.5h12"/></svg></span>Work</button>
      <button class="rail-item" data-view="notes"><span class="ic"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3.5h7.5L16 7v9.5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"/><path d="M12.2 3.5V7H16"/><path d="M6.6 10.5h6.3M6.6 13.2h6.3"/></svg></span>Notes</button>
      <button class="rail-item" data-view="meetings"><span class="ic"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="13" height="11.5" rx="1.3"/><path d="M3.5 8h13"/><path d="M7 3v3M13 3v3"/></svg></span>Meetings</button>
    </nav>
    <div id="subpanel-container" class="hidden"></div>
    <main>
```

Note: no `Observations` button — per the confirmed decision, that view stays in the code (`#view-observations`, `renderObservationsView()`) but is unreachable via nav in this round.

- [ ] **Step 3: Update `switchTab()` to target `.rail-item` and refresh the sub-panel**

Replace (lines 1900-1907):
```js
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t =>
    t.classList.toggle('active', t.dataset.view === name)
  );
  ['today','pending','registry','observations','work','notes','meetings'].forEach(v => {
    el(`view-${v}`).classList.toggle('hidden', v !== name);
  });
}
```
with:
```js
function switchTab(name) {
  document.querySelectorAll('.rail-item').forEach(t =>
    t.classList.toggle('active', t.dataset.view === name)
  );
  ['today','pending','registry','observations','work','notes','meetings'].forEach(v => {
    el(`view-${v}`).classList.toggle('hidden', v !== name);
  });
  renderSubpanel(name);
}

function renderSubpanel(name) {
  const container = el('subpanel-container');
  if (name === 'registry' && typeof renderPeopleSubpanel === 'function') {
    container.classList.remove('hidden');
    renderPeopleSubpanel(container);
  } else if (name === 'work' && typeof renderWorkSubpanel === 'function') {
    container.classList.remove('hidden');
    renderWorkSubpanel(container);
  } else {
    container.classList.add('hidden');
    container.innerHTML = '';
  }
}
```

The `typeof ... === 'function'` guards mean this task is fully functional and testable on its own — clicking People or Work will correctly leave the sub-panel hidden until Tasks 3/4 define those two functions, matching the reference file's own build-order comment (`// Task 2 (people) / Task 3 (work) fill this in`).

- [ ] **Step 4: Rename the `.tab` selector in `setupTabs()`**

Replace (lines 3122-3135):
```js
function setupTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const view = tab.dataset.view;
      switchTab(view);
      if (view === 'today') renderTodayView();
      if (view === 'registry') renderRegistryView();
      if (view === 'observations') renderObservationsView();
      if (view === 'work') renderWorkView();
      if (view === 'notes') renderNotesView();
      if (view === 'meetings') renderMeetingsView();
    });
  });
}
```
with:
```js
function setupTabs() {
  document.querySelectorAll('.rail-item').forEach(tab => {
    tab.addEventListener('click', () => {
      const view = tab.dataset.view;
      switchTab(view);
      if (view === 'today') renderTodayView();
      if (view === 'registry') renderRegistryView();
      if (view === 'observations') renderObservationsView();
      if (view === 'work') renderWorkView();
      if (view === 'notes') renderNotesView();
      if (view === 'meetings') renderMeetingsView();
    });
  });
}
```

(The `observations` branch is now unreachable dead code since no `.rail-item` has `data-view="observations"` — left in place deliberately so restoring the button later is a one-line change, not a rebuild.)

- [ ] **Step 5: Verify no remaining `.tab` references outside intentional leftovers**

Run:
```bash
grep -n "querySelectorAll('\.tab')\|querySelector('\.tab')\|class=\"tab" tools/registry_ui.html
```
Expected: no output.

- [ ] **Step 6: Manual verification in browser**

Reload the app.

Check via `read_page` and a screenshot:
- A ~176px-wide rail renders on the left with 6 icon+label rows: Today, Pending, People, Work, Notes, Meetings (no Observations).
- "Today" is active by default (forest-tinted background).
- Click each of the 6 items in turn — the correct `#view-*` panel shows/hides exactly as before, and the clicked rail item becomes active.
- The `pending-count` span still populates with a count once Pending is loaded.
- Clicking People or Work does not throw a JS error (`read_console_messages`) — the empty `#subpanel-container` just stays hidden since Tasks 3/4 haven't run yet.

- [ ] **Step 7: Commit**

```bash
git add tools/registry_ui.html
git commit -m "Registry UI: replace top tab bar with icon rail nav"
```

---

### Task 3: People sub-panel (type filter)

**Files:**
- Modify: `tools/registry_ui.html` — insert new code immediately before `function renderRegistryView(filter = '')` (currently line 1770)
- Modify: `tools/registry_ui.html:1770-1780` (`renderRegistryView` body)

**Interfaces:**
- Consumes: `renderSubpanel(name)` from Task 2, which already calls `renderPeopleSubpanel(container)` via the `typeof` guard — no further change needed to Task 2's code.
- Produces: `registryNavState.typeFilter` (string, one of `'all'|'lead'|'customer'|'partner'|'internal'|'unknown'`) — read by `renderRegistryView`, nothing later depends on it beyond this task.

- [ ] **Step 1: Add `registryNavState`, the filter list, and `renderPeopleSubpanel()`**

Insert immediately above `function renderRegistryView(filter = '') {` (line 1770):

```js
// ── People sub-panel ─────────────────────────────────────────────────────────
const registryNavState = { typeFilter: 'all' };

const REGISTRY_TYPE_FILTERS = [
  { value: 'all',      label: 'All People' },
  { value: 'lead',     label: 'Leads' },
  { value: 'customer', label: 'Customers' },
  { value: 'partner',  label: 'Partners' },
  { value: 'internal', label: 'Internal' },
  { value: 'unknown',  label: 'Unknown' },
];

function renderPeopleSubpanel(container) {
  container.innerHTML = `
    <div class="subpanel-label">People</div>
    ${REGISTRY_TYPE_FILTERS.map(f => `
      <button class="sub-item${f.value === registryNavState.typeFilter ? ' active' : ''}" data-filter="${f.value}">${esc(f.label)}</button>
    `).join('')}`;
  container.querySelectorAll('.sub-item').forEach(btn => {
    btn.addEventListener('click', () => {
      registryNavState.typeFilter = btn.dataset.filter;
      renderPeopleSubpanel(container);
      const currentSearch = el('registry-search')?.value ?? '';
      renderRegistryView(currentSearch);
    });
  });
}

```

- [ ] **Step 2: Thread the type filter into `renderRegistryView` alongside the existing text search**

Replace (lines 1770-1780):
```js
function renderRegistryView(filter = '') {
  const view = el('view-registry');
  const people = state.registry?.people ?? [];
  const q = filter.toLowerCase();
  const filtered = q
    ? people.filter(p =>
        p.canonical_name.toLowerCase().includes(q) ||
        (p.aliases ?? []).some(a => a.toLowerCase().includes(q)) ||
        (p.email ?? '').toLowerCase().includes(q)
      )
    : people;
```
with:
```js
function renderRegistryView(filter = '') {
  const view = el('view-registry');
  const byType = state.registry?.people ?? [];
  const people = registryNavState.typeFilter === 'all'
    ? byType
    : byType.filter(p => p.type === registryNavState.typeFilter);
  const q = filter.toLowerCase();
  const filtered = q
    ? people.filter(p =>
        p.canonical_name.toLowerCase().includes(q) ||
        (p.aliases ?? []).some(a => a.toLowerCase().includes(q)) ||
        (p.email ?? '').toLowerCase().includes(q)
      )
    : people;
```

Everything after this point in the function (building `view.innerHTML`, row click handlers, the search input's own `input` listener) is unchanged — it already reads from the `filtered`/`people` variables defined above, which now carry the type filter automatically.

- [ ] **Step 3: Manual verification in browser**

Reload the app.

Check:
- Click "People" in the rail — a sub-panel appears listing All People / Leads / Customers / Partners / Internal / Unknown, with "All People" active.
- The main list shows the same full people list as before this port (no regression from the default state).
- Click "Leads" — sub-panel highlights Leads, and the list narrows to only `type === 'lead'` people.
- Type into the search box while "Leads" is selected — results narrow further by both type and text (combined, not replaced).
- Click "All People" — full list returns.
- Click a person row to expand detail, edit and save it — confirm the existing edit/save flow (`openDetailEdit`, `PATCH /api/people/:id`) still works and the list re-renders with the same type/search filter active afterward.
- `read_console_messages` shows no new errors.

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "Registry UI: add People sub-panel type filter"
```

---

### Task 4: Work sub-panel (Projects / Standalone / Routines filter)

**Files:**
- Modify: `tools/registry_ui.html:2048` (`workState` definition)
- Modify: `tools/registry_ui.html` — insert new code immediately before `async function renderWorkView()` (currently line 2743)
- Modify: `tools/registry_ui.html:2773` (after `laterTasks` is computed — insert show-flags)
- Modify: `tools/registry_ui.html:2863-2889` (`view.innerHTML` assembly)
- Modify: `tools/registry_ui.html:2891-2913` (`Wire new project form` block)

**Interfaces:**
- Consumes: `renderSubpanel(name)` from Task 2, which already calls `renderWorkSubpanel(container)` via the `typeof` guard — no further change needed to Task 2's code.
- Produces: `workState.subFilter` (string, one of `'all'|'projects'|'standalone'|'routines'`) — read only within `renderWorkView`.

- [ ] **Step 1: Add `subFilter` to the existing `workState` object**

Replace (line 2048):
```js
const workState = { expanded: new Set(), editing: new Set(), laterExpanded: false, horizonShown: new Set(), routineEditing: new Set() };
```
with:
```js
const workState = { expanded: new Set(), editing: new Set(), laterExpanded: false, horizonShown: new Set(), routineEditing: new Set(), subFilter: 'all' };
```

- [ ] **Step 2: Add the filter list and `renderWorkSubpanel()`**

Insert immediately above `async function renderWorkView() {` (line 2743):

```js
// ── Work sub-panel ───────────────────────────────────────────────────────────
const WORK_SUBPANEL_FILTERS = [
  { value: 'all',        label: 'All Work' },
  { value: 'projects',   label: 'Projects' },
  { value: 'standalone', label: 'Standalone' },
  { value: 'routines',   label: 'Routines' },
];

function renderWorkSubpanel(container) {
  container.innerHTML = `
    <div class="subpanel-label">Work</div>
    ${WORK_SUBPANEL_FILTERS.map(f => `
      <button class="sub-item${f.value === workState.subFilter ? ' active' : ''}" data-filter="${f.value}">${esc(f.label)}</button>
    `).join('')}`;
  container.querySelectorAll('.sub-item').forEach(btn => {
    btn.addEventListener('click', () => {
      workState.subFilter = btn.dataset.filter;
      renderWorkSubpanel(container);
      renderWorkView();
    });
  });
}

```

- [ ] **Step 3: Compute show-flags right after `laterTasks` is derived**

Replace (line 2773, plus its exact preceding context to anchor uniquely):
```js
  const standaloneAll = sortTasks((allTasks || []).filter(t => !t.project_id));
  const standaloneTasks = standaloneAll.filter(t => !isBehindHorizon(t));
  const laterTasks = standaloneAll.filter(isBehindHorizon).sort((a, b) => (a.horizon < b.horizon ? -1 : 1));
```
with:
```js
  const standaloneAll = sortTasks((allTasks || []).filter(t => !t.project_id));
  const standaloneTasks = standaloneAll.filter(t => !isBehindHorizon(t));
  const laterTasks = standaloneAll.filter(isBehindHorizon).sort((a, b) => (a.horizon < b.horizon ? -1 : 1));

  const showProjects = workState.subFilter === 'all' || workState.subFilter === 'projects';
  const showStandalone = workState.subFilter === 'all' || workState.subFilter === 'standalone';
  const showRoutines = workState.subFilter === 'all' || workState.subFilter === 'routines';
```

- [ ] **Step 4: Make section inclusion in `view.innerHTML` conditional on the show-flags**

Replace (lines 2863-2889):
```js
  view.innerHTML = `
    <div class="work-section-header">
      <span class="work-section-label">Projects</span>
      <button class="btn-new-proj" id="new-proj-toggle">+ New Project</button>
    </div>
    <div class="new-proj-inline hidden" id="new-proj-inline">
      <input class="add-task-input" id="new-proj-name" placeholder="Project name…" style="flex:1" />
      <button class="btn-add-task" id="new-proj-submit">Create</button>
      <span class="new-proj-status" id="new-proj-status"></span>
    </div>
    <div id="work-proj-list">${projGroupsHtml}</div>
    <div class="standalone-section">
      <div class="work-section-header">
        <span class="work-section-label">Standalone</span>
      </div>
      <div id="standalone-tasks">${standaloneHtml}</div>
      ${renderAddTaskForm(null, people)}
      ${laterHtml}
    </div>
    <div class="routines-section">
      <div class="work-section-header">
        <span class="work-section-label">Routines</span>
        <button class="btn-new-proj" id="new-routine-toggle">+ New Routine</button>
      </div>
      ${newRoutineHtml}
      <div id="routines-list">${routineRowsHtml}</div>
    </div>`;
```
with:
```js
  const projectsSectionHtml = showProjects ? `
    <div class="work-section-header">
      <span class="work-section-label">Projects</span>
      <button class="btn-new-proj" id="new-proj-toggle">+ New Project</button>
    </div>
    <div class="new-proj-inline hidden" id="new-proj-inline">
      <input class="add-task-input" id="new-proj-name" placeholder="Project name…" style="flex:1" />
      <button class="btn-add-task" id="new-proj-submit">Create</button>
      <span class="new-proj-status" id="new-proj-status"></span>
    </div>
    <div id="work-proj-list">${projGroupsHtml}</div>` : '';

  const standaloneSectionHtml = showStandalone ? `
    <div class="standalone-section">
      <div class="work-section-header">
        <span class="work-section-label">Standalone</span>
      </div>
      <div id="standalone-tasks">${standaloneHtml}</div>
      ${renderAddTaskForm(null, people)}
      ${laterHtml}
    </div>` : '';

  const routinesSectionHtml = showRoutines ? `
    <div class="routines-section">
      <div class="work-section-header">
        <span class="work-section-label">Routines</span>
        <button class="btn-new-proj" id="new-routine-toggle">+ New Routine</button>
      </div>
      ${newRoutineHtml}
      <div id="routines-list">${routineRowsHtml}</div>
    </div>` : '';

  view.innerHTML = projectsSectionHtml + standaloneSectionHtml + routinesSectionHtml;
```

- [ ] **Step 5: Guard the "Wire new project form" block — it's the one place that isn't already null-safe**

Replace (lines 2891-2913):
```js
  // ── Wire new project form ───────────────────────────────────────────────
  el('new-proj-toggle').addEventListener('click', () => {
    el('new-proj-inline').classList.toggle('hidden');
    el('new-proj-name').focus();
  });
  const submitNewProject = async () => {
    const name = el('new-proj-name').value.trim();
    if (!name) { el('new-proj-name').focus(); return; }
    el('new-proj-submit').disabled = true;
    el('new-proj-status').textContent = 'Creating…';
    try {
      await fetchJSON(`${API}/api/projects`, {
        method: 'POST',
        body: JSON.stringify({ canonical_name: name, members: [] }),
      });
      await renderWorkView();
    } catch (err) {
      el('new-proj-status').textContent = 'Error: ' + err.message;
      el('new-proj-submit').disabled = false;
    }
  };
  el('new-proj-submit').addEventListener('click', submitNewProject);
  el('new-proj-name').addEventListener('keydown', e => { if (e.key === 'Enter') submitNewProject(); });
```
with:
```js
  // ── Wire new project form ───────────────────────────────────────────────
  if (showProjects) {
    el('new-proj-toggle').addEventListener('click', () => {
      el('new-proj-inline').classList.toggle('hidden');
      el('new-proj-name').focus();
    });
    const submitNewProject = async () => {
      const name = el('new-proj-name').value.trim();
      if (!name) { el('new-proj-name').focus(); return; }
      el('new-proj-submit').disabled = true;
      el('new-proj-status').textContent = 'Creating…';
      try {
        await fetchJSON(`${API}/api/projects`, {
          method: 'POST',
          body: JSON.stringify({ canonical_name: name, members: [] }),
        });
        await renderWorkView();
      } catch (err) {
        el('new-proj-status').textContent = 'Error: ' + err.message;
        el('new-proj-submit').disabled = false;
      }
    };
    el('new-proj-submit').addEventListener('click', submitNewProject);
    el('new-proj-name').addEventListener('keydown', e => { if (e.key === 'Enter') submitNewProject(); });
  }
```

Everything else in `renderWorkView` (the "Wire task interactions" loops, `wireRoutinesSection`, the Later-section toggle) already guards on `document.getElementById(...)` returning non-null before attaching listeners, so those need no changes — they silently no-op for sections that are hidden.

- [ ] **Step 6: Manual verification in browser**

Reload the app.

Check:
- Click "Work" in the rail — a sub-panel appears listing All Work / Projects / Standalone / Routines, with "All Work" active, and the main content looks identical to the pre-port Work tab (Projects, then Standalone, then Routines, in that order).
- Click "Projects" — only the Projects section (with its "+ New Project" control) shows; Standalone and Routines sections disappear; no console error.
- With "Projects" active, click "+ New Project", type a name, submit — confirm it still creates a project and re-renders with "Projects" still selected.
- Click "Standalone" — only the Standalone section (with its add-task form and Later section, if any later tasks exist) shows. Add a standalone task — confirm it still works.
- Click "Routines" — only the Routines section (with "+ New Routine") shows. Expand/edit a routine — confirm it still works.
- Click "All Work" — all three sections return together.
- `read_console_messages` shows no new errors across all of the above.

- [ ] **Step 7: Commit**

```bash
git add tools/registry_ui.html
git commit -m "Registry UI: add Work sub-panel section filter"
```

---

### Task 5: Full-port regression pass

**Files:**
- None (verification only — fix forward in the relevant task's file/line if something breaks).

**Interfaces:**
- Consumes: the fully ported app from Tasks 1-4.
- Produces: nothing — this is the final sign-off gate before considering the port complete.

- [ ] **Step 1: Start from a clean load**

Restart `tools/server.py`, hard-reload the app in the Browser pane, confirm the loading screen → app transition still works (`el('screen-loading')`/`el('app')` classList toggles from `init()` are untouched by this port).

- [ ] **Step 2: Walk every rail item**

Click through Today, Pending, People, Work, Notes, Meetings in sequence. For each, confirm the correct `#view-*` panel is the only one visible (`read_page` and check `.hidden` classes), and that the corresponding `render*View()` function ran (visible content matches what existed before the port — compare against a screenshot taken before Task 1 if one was saved, otherwise sanity-check against `data/people_registry.json`/`data/tasks.jsonl` contents directly).

- [ ] **Step 3: Confirm Observations is intentionally unreachable, not broken**

Run:
```bash
grep -n "renderObservationsView\|view-observations" tools/registry_ui.html
```
Expected: `renderObservationsView` function definition and the `#view-observations` div both still exist unchanged — only the removed rail button and the now-dead `if (view === 'observations')` dispatch branch in `setupTabs()` reflect the nav change.

- [ ] **Step 4: Re-run the full People and Work checklists from Tasks 3 and 4 together**

In particular, verify combined state doesn't fight itself: filter People to "Leads", switch to Work and filter to "Routines", switch back to People — confirm "Leads" is still selected (the persistence design call from Global Constraints) and the list is still correctly filtered.

- [ ] **Step 5: Take a final screenshot and report to Trent**

Use the Browser pane's screenshot tool to capture the rail + People (Leads filtered) view and the rail + Work (Projects filtered) view, and share both so Trent can do a final visual sign-off against the approved artifact preview.

- [ ] **Step 6: No commit for this task** — it's verification-only. If Step 2-4 surface a regression, fix it in the originating task's section of this file, re-run that task's manual verification, and amend that task's commit (or add a small follow-up commit) before moving on.
