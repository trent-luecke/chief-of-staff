# Registry Sidebar Nav + Airtable-Inspired Reskin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one self-contained, interactive HTML artifact that reproduces the People Registry with a rail+sub-panel sidebar (replacing the current top tab bar) and a new Airtable-inspired forest-accent theme, so Trent can react to it before anything is ported into the real `tools/registry_ui.html`.

**Architecture:** A single HTML file with inline `<style>`/`<script>` (same pattern as the two prior reskin-preview artifacts in this session). Vanilla JS state object (`{ activeSection, activeSubFilter }`) drives three render functions — `renderRail()`, `renderSubpanel()`, `renderMain()` — called from one `renderShell()` orchestrator on every click. Sample data (`PEOPLE_SAMPLE`, `WORK_DATA`) is hand-authored, shaped to match what `tools/registry_ui.html` actually stores (`type` badge field for people; Projects/Standalone/Routines groupings for work) — no live data binding.

**Tech Stack:** Plain HTML/CSS/JS, no build step, no dependencies. Verified with the `playwright-iso` MCP browser (file:// is blocked in both Claude Browser and Playwright, so verification serves the file over a local `python3 -m http.server`). Published via the `Artifact` tool.

## Global Constraints

- Deliverable is one interactive artifact only — do NOT touch `tools/registry_ui.html` or `tools/server.py` in this plan.
- No new functionality beyond nav/filter — every row, badge, and button that exists in the real registry must still be conceptually present; this is nav structure + theme only.
- Only **People** and **Work** get a sub-panel. Today, Pending, Notes, Meetings stay flat — clicking them fills main content directly, no sub-panel.
- Rail: icon + label, ~176px wide, always visible. Sub-panel (People/Work only): ~170px, sits flush against the rail.
- People sub-panel items: `All People` (default) / `Leads` / `Customers` / `Partners` / `Internal` / `Unknown` — filters by the person's `type` field.
- Work sub-panel items: `All Work` (default) / `Projects` / `Standalone` / `Routines` — matches `renderWorkView()`'s three real groupings in `tools/registry_ui.html`.
- Theme tokens (exact hex, from the approved spec):
  `--canvas:#fdfdfc; --ink:#181d26; --body:#333840; --muted:#767b85; --hairline:#e3e3e0; --surface-soft:#f7f6f3; --surface-strong:#ececea; --accent:#0a5c3d; --accent-soft:#e2f0ea;`
- Existing badge semantic colors are unchanged: Lead = blue, Customer = green, Partner = amber, Internal = gray, Unknown = red. The signature `--accent` (forest) is reserved for active-nav state, primary buttons, and focus rings only — never applied to badges.
- Type stays modest weight (no bold display headings); minimal shadow, color-block-first elevation.
- Rail icons must NOT reuse the wireframe placeholder glyphs (◷◔☺▤✎◫) — build a considered, consistent icon set (Task 1 specifies the exact SVGs to use).
- The previewer's own chrome (title, lead-in text, controls) must stay legible regardless of the artifact host's light/dark theme — carry forward the paired `--page-bg`/`--ink-chrome` token fix from the prior reskin round (background and text color must move together on one signal, never independently).
- The registry shell itself (`#stage`) uses the theme tokens above as fixed, explicit hex values — it does NOT follow the host's light/dark preference. (Matches how all 5 palettes in the very first reskin artifact were self-contained regardless of host theme — this mockup is demonstrating one fixed direction, not a re-run of the palette picker.)

---

## Task 1: Shell, Theme Tokens, Icon Set, and Flat-Section Rail Navigation

**Files:**
- Create: `/private/tmp/claude-501/-Users-trentluecke-dev-Claude-Projects-chief-of-staff/c76a2967-0676-4cf6-9961-5b53d3062e37/scratchpad/registry-sidebar-mockup.html`

**Interfaces:**
- Produces:
  - Global `STATE = { activeSection: 'people', activeSubFilter: 'all' }` — Task 2 and Task 3 read/write `STATE.activeSubFilter`.
  - `SECTIONS` array: `[{id, label, icon, hasChildren}]` for the 6 rail items — Task 2/3 look up `hasChildren` by id to decide whether to call their subpanel renderer.
  - `selectSection(id)` — click handler, sets `STATE.activeSection = id`, resets `STATE.activeSubFilter = 'all'`, calls `renderShell()`.
  - `renderShell()` — orchestrator: calls `renderRail()`, then `renderSubpanel()`, then `renderMain()`. Task 2/3 hook into `renderSubpanel()` and `renderMain()` via a `switch` on `STATE.activeSection`.
  - `esc(s)` — HTML-escaping helper, reused by Task 2/3 for all user-visible sample text.
  - DOM containers with fixed IDs: `#rail-list`, `#subpanel-container` (hidden via `.hidden` class when the active section has no children), `#main-content`.

- [ ] **Step 1: Write the full HTML shell with theme tokens, icon set, and rail (no People/Work content yet — placeholder panels for all 6 sections)**

Write this exact content to the file:

```html
<title>People Registry — Sidebar Preview</title>
<style>
  /* ── Previewer's own chrome: paired bg/ink so it's legible on any host theme ── */
  :root {
    --page-bg:#ffffff; --ink-chrome:#1c1c22; --ink-chrome-soft:#5b5b66;
  }
  @media (prefers-color-scheme:dark){
    :root { --page-bg:#0e0e13; --ink-chrome:#ececf2; --ink-chrome-soft:#a6a6b4; }
  }
  :root[data-theme="light"]{ --page-bg:#ffffff; --ink-chrome:#1c1c22; --ink-chrome-soft:#5b5b66; }
  :root[data-theme="dark"]{ --page-bg:#0e0e13; --ink-chrome:#ececf2; --ink-chrome-soft:#a6a6b4; }
  body { background:var(--page-bg); }

  *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }

  .wrap {
    max-width:1040px; margin:0 auto; padding:28px 22px 60px;
    font-family:-apple-system,system-ui,"Helvetica Neue",sans-serif;
    color:var(--ink-chrome);
  }
  .lead-in { margin-bottom:20px; }
  .lead-in h1 { font-size:22px; font-weight:700; letter-spacing:-.01em; margin-bottom:6px; text-wrap:balance; }
  .lead-in p { font-size:13.5px; line-height:1.55; color:var(--ink-chrome-soft); max-width:68ch; }

  .frame {
    border-radius:14px; overflow:hidden;
    border:1px solid rgba(128,128,140,.22);
    box-shadow:0 10px 40px rgba(0,0,0,.14);
  }
  .titlebar {
    display:flex; align-items:center; gap:8px;
    padding:9px 14px; background:rgba(128,128,140,.10);
    border-bottom:1px solid rgba(128,128,140,.18);
  }
  .dot { width:11px; height:11px; border-radius:50%; }
  .dot.r{background:#ff5f57;} .dot.y{background:#febc2e;} .dot.g{background:#28c840;}
  .titlebar span { margin-left:8px; font-size:11.5px; color:var(--ink-chrome-soft); font-family:ui-monospace,monospace; }

  /* ── The registry shell: fixed explicit palette, independent of host theme ── */
  #stage {
    --canvas:#fdfdfc; --ink:#181d26; --body-c:#333840; --muted:#767b85;
    --hairline:#e3e3e0; --surface-soft:#f7f6f3; --surface-strong:#ececea;
    --accent:#0a5c3d; --accent-soft:#e2f0ea; --accent-ink:#ffffff;
    --b-lead-bg:#e6eefc; --b-lead-fg:#1c5fc9;
    --b-customer-bg:#e3f3ea; --b-customer-fg:#0e7a4f;
    --b-partner-bg:#fcefdc; --b-partner-fg:#a9720d;
    --b-internal-bg:#eceded; --b-internal-fg:#68707a;
    --b-unknown-bg:#fbe4e1; --b-unknown-fg:#c23b2d;
    background:var(--canvas); color:var(--body-c);
    font-family:-apple-system,system-ui,"Helvetica Neue",sans-serif;
    font-size:13px; line-height:1.5;
    display:flex; min-height:560px;
  }

  #stage .rail {
    width:176px; flex-shrink:0; background:var(--surface-soft);
    border-right:1px solid var(--hairline); padding:14px 10px;
    display:flex; flex-direction:column; gap:2px;
  }
  #stage .rail-item {
    display:flex; align-items:center; gap:10px; padding:8px 10px;
    border-radius:7px; font-size:13px; color:var(--muted);
    cursor:pointer; border:none; background:none; font:inherit;
    width:100%; text-align:left;
  }
  #stage .rail-item:hover { background:var(--surface-strong); }
  #stage .rail-item.active { background:var(--accent-soft); color:var(--accent); font-weight:600; }
  #stage .rail-item .ic { width:18px; height:18px; flex-shrink:0; display:flex; align-items:center; justify-content:center; }
  #stage .rail-item .ic svg { width:16px; height:16px; }

  #stage #subpanel-container {
    width:170px; flex-shrink:0; background:var(--canvas);
    border-right:1px solid var(--hairline); padding:14px 12px;
  }
  #stage #subpanel-container.hidden { display:none; }
  #stage .subpanel-label {
    font-size:10.5px; letter-spacing:.08em; text-transform:uppercase;
    color:var(--muted); font-weight:600; margin-bottom:8px;
  }
  #stage .sub-item {
    display:block; width:100%; text-align:left; padding:6px 8px; margin-bottom:1px;
    border-radius:6px; font-size:13px; color:var(--body-c);
    cursor:pointer; border:none; background:none; font:inherit;
  }
  #stage .sub-item:hover { background:var(--surface-soft); }
  #stage .sub-item.active { background:var(--surface-strong); color:var(--ink); font-weight:600; }

  #stage #main-content { flex:1; padding:22px 26px; overflow:auto; }
  #stage #main-content h1 { font-size:22px; font-weight:500; color:var(--ink); margin-bottom:4px; letter-spacing:-.01em; }
  #stage #main-content .sub { font-size:13px; color:var(--muted); margin-bottom:16px; }
  #stage .placeholder-note { font-size:13px; color:var(--muted); padding:24px 0; }

  #stage .search-input {
    width:100%; background:var(--surface-soft); border:1px solid var(--hairline);
    color:var(--ink); padding:9px 12px; border-radius:8px; font-size:13px;
    font-family:inherit; outline:none; margin-bottom:14px;
  }
  #stage .search-input::placeholder { color:var(--muted); }

  #stage .row {
    display:flex; align-items:center; gap:10px; padding:11px 13px;
    border:1px solid var(--hairline); border-radius:9px; margin-bottom:7px;
    background:var(--canvas);
  }
  #stage .row .name { flex:1; font-size:13.5px; font-weight:500; color:var(--ink); }
  #stage .meta { font-size:11px; color:var(--muted); }

  #stage .badge {
    display:inline-block; font-size:10px; padding:2px 8px; border-radius:6px;
    text-transform:uppercase; letter-spacing:.05em; font-weight:700;
  }
  #stage .badge-lead     { background:var(--b-lead-bg);     color:var(--b-lead-fg); }
  #stage .badge-customer { background:var(--b-customer-bg); color:var(--b-customer-fg); }
  #stage .badge-partner  { background:var(--b-partner-bg);  color:var(--b-partner-fg); }
  #stage .badge-internal { background:var(--b-internal-bg); color:var(--b-internal-fg); }
  #stage .badge-unknown  { background:var(--b-unknown-bg);  color:var(--b-unknown-fg); }

  #stage .btn-primary {
    background:var(--accent); color:var(--accent-ink); border:none;
    padding:9px 18px; border-radius:8px; font-size:12.5px; font-weight:600;
    cursor:pointer; font-family:inherit; margin-top:8px;
  }

  .footnote { margin-top:18px; font-size:12px; line-height:1.6; color:var(--ink-chrome-soft); max-width:74ch; }
</style>

<div class="wrap">
  <div class="lead-in">
    <h1>People Registry — sidebar preview</h1>
    <p>Rail navigation replaces the top tab bar. People and Work expand into a sub-panel so you can see everything or drill into one slice; Today, Pending, Notes, and Meetings stay single-click, same as today. Nav structure and click behavior are real — the data underneath is representative sample content, not live.</p>
  </div>

  <div class="frame">
    <div class="titlebar">
      <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
      <span>registry — sidebar preview</span>
    </div>
    <div id="stage">
      <nav class="rail" id="rail-list"></nav>
      <div id="subpanel-container"></div>
      <div id="main-content"></div>
    </div>
  </div>

  <p class="footnote">
    This is a design-exploration artifact only — no add/edit/merge action is wired up, and none of this touches the real registry. If the direction lands, the next round ports it into <code>tools/registry_ui.html</code>.
  </p>
</div>

<script>
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const ICONS = {
  today: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="7.5"/><path d="M10 6v4l2.8 2.8"/></svg>',
  pending: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9h4.2l1.3 2.4h2.9L12.7 9H17"/><path d="M3 9V5.6C3 5 3.5 4.5 4.1 4.5h11.8c.6 0 1.1.5 1.1 1.1V9"/><path d="M3 9v5.4c0 .6.5 1.1 1.1 1.1h11.8c.6 0 1.1-.5 1.1-1.1V9"/></svg>',
  people: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="7" r="3"/><path d="M4 17c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/></svg>',
  work: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5.5" width="12" height="10.5" rx="1.3"/><path d="M7.5 5.5V4.3c0-.6.5-1.1 1.1-1.1h2.8c.6 0 1.1.5 1.1 1.1v1.2"/><path d="M4 9.5h12"/></svg>',
  notes: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3.5h7.5L16 7v9.5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"/><path d="M12.2 3.5V7H16"/><path d="M6.6 10.5h6.3M6.6 13.2h6.3"/></svg>',
  meetings: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="4.5" width="13" height="11.5" rx="1.3"/><path d="M3.5 8h13"/><path d="M7 3v3M13 3v3"/></svg>',
};

const SECTIONS = [
  { id:'today',    label:'Today',    icon:'today',    hasChildren:false },
  { id:'pending',  label:'Pending',  icon:'pending',  hasChildren:false },
  { id:'people',   label:'People',   icon:'people',   hasChildren:true  },
  { id:'work',     label:'Work',     icon:'work',     hasChildren:true  },
  { id:'notes',    label:'Notes',    icon:'notes',    hasChildren:false },
  { id:'meetings', label:'Meetings', icon:'meetings', hasChildren:false },
];

const STATE = { activeSection:'people', activeSubFilter:'all' };

function selectSection(id) {
  STATE.activeSection = id;
  STATE.activeSubFilter = 'all';
  renderShell();
}

function selectSubFilter(value) {
  STATE.activeSubFilter = value;
  renderShell();
}

function renderRail() {
  const list = document.getElementById('rail-list');
  list.innerHTML = SECTIONS.map(s => `
    <button class="rail-item${s.id === STATE.activeSection ? ' active' : ''}" data-id="${s.id}">
      <span class="ic">${ICONS[s.icon]}</span>${esc(s.label)}
    </button>`).join('');
  list.querySelectorAll('.rail-item').forEach(btn => {
    btn.addEventListener('click', () => selectSection(btn.dataset.id));
  });
}

function renderSubpanel() {
  const container = document.getElementById('subpanel-container');
  const section = SECTIONS.find(s => s.id === STATE.activeSection);
  if (!section.hasChildren) {
    container.classList.add('hidden');
    container.innerHTML = '';
    return;
  }
  container.classList.remove('hidden');
  // Task 2 (people) / Task 3 (work) fill this in via renderPeopleSubpanel()/renderWorkSubpanel()
  if (section.id === 'people' && typeof renderPeopleSubpanel === 'function') renderPeopleSubpanel(container);
  else if (section.id === 'work' && typeof renderWorkSubpanel === 'function') renderWorkSubpanel(container);
}

function renderMain() {
  const main = document.getElementById('main-content');
  const id = STATE.activeSection;
  if (id === 'people' && typeof renderPeopleMain === 'function') { renderPeopleMain(main); return; }
  if (id === 'work' && typeof renderWorkMain === 'function') { renderWorkMain(main); return; }
  const labels = { today:'Today', pending:'Pending', notes:'Notes', meetings:'Meetings' };
  main.innerHTML = `
    <h1>${esc(labels[id])}</h1>
    <p class="placeholder-note">Flat section — same single-click behavior as today's tab bar. Not rebuilt here since this mockup is scoped to nav structure + theme, not feature parity.</p>`;
}

function renderShell() {
  renderRail();
  renderSubpanel();
  renderMain();
}

renderShell();
</script>
```

- [ ] **Step 2: Serve the file and verify the flat-section shell renders correctly**

Start a local server (file:// is blocked in both the Claude Browser and Playwright tools):

```bash
cd /private/tmp/claude-501/-Users-trentluecke-dev-Claude-Projects-chief-of-staff/c76a2967-0676-4cf6-9961-5b53d3062e37/scratchpad && python3 -m http.server 8793
```

Run in background. Then verify with the `playwright-iso` MCP browser (load its tools via `ToolSearch` with query `select:mcp__playwright-iso__browser_navigate,mcp__playwright-iso__browser_click,mcp__playwright-iso__browser_evaluate,mcp__playwright-iso__browser_take_screenshot` if not already loaded):

```
browser_navigate({ url: "http://localhost:8793/registry-sidebar-mockup.html" })
```

Then evaluate:

```js
() => {
  const items = document.querySelectorAll('#rail-list .rail-item');
  const active = document.querySelector('#rail-list .rail-item.active');
  return {
    railCount: items.length,
    activeLabel: active ? active.textContent.trim() : null,
    subpanelHidden: document.getElementById('subpanel-container').classList.contains('hidden'),
  };
}
```

Expected: `railCount: 6`, `activeLabel` contains `"People"` (default `STATE.activeSection`), `subpanelHidden: false` (People has children, so the subpanel container should be visible — even though Task 1 hasn't filled it with People-specific content yet, `renderSubpanel()` already un-hides it for sections with children).

Click "Today" and re-evaluate:

```
browser_click({ target: "button.rail-item:has-text('Today')" })
```

```js
() => {
  const active = document.querySelector('#rail-list .rail-item.active');
  return {
    activeLabel: active.textContent.trim(),
    subpanelHidden: document.getElementById('subpanel-container').classList.contains('hidden'),
    mainHeading: document.querySelector('#main-content h1').textContent.trim(),
  };
}
```

Expected: `activeLabel` contains `"Today"`, `subpanelHidden: true` (Today has no children), `mainHeading: "Today"`.

- [ ] **Step 3: Verify dark-host contrast safety for the previewer chrome**

```js
() => {
  document.documentElement.setAttribute('data-theme', 'dark');
  return {
    bodyBg: getComputedStyle(document.body).backgroundColor,
    h1Color: getComputedStyle(document.querySelector('.lead-in h1')).color,
  };
}
```

Expected: a dark `bodyBg` (e.g. `rgb(14, 14, 19)`) paired with a light `h1Color` (e.g. `rgb(236, 236, 242)`) — background and text must move together, never independently. Then reset:

```js
() => { document.documentElement.removeAttribute('data-theme'); }
```

- [ ] **Step 4: Commit is not applicable (scratchpad file, not a repo file) — no git action for this task.**

---

## Task 2: People Section — Sub-panel Filters + Sample Data

**Files:**
- Modify: `/private/tmp/claude-501/-Users-trentluecke-dev-Claude-Projects-chief-of-staff/c76a2967-0676-4cf6-9961-5b53d3062e37/scratchpad/registry-sidebar-mockup.html`

**Interfaces:**
- Consumes: `STATE.activeSubFilter` (from Task 1), `esc()` (from Task 1), `.badge-{type}` CSS classes (from Task 1's `#stage` styles).
- Produces:
  - `PEOPLE_SAMPLE` array of `{ name, type, lastSeen, aliasCount }` — not consumed by other tasks, but must stay consistent with Task 1's 5 badge classes (`lead`, `customer`, `partner`, `internal`, `unknown`).
  - `renderPeopleSubpanel(container)` — called by Task 1's `renderSubpanel()` when `STATE.activeSection === 'people'`.
  - `renderPeopleMain(main)` — called by Task 1's `renderMain()` when `STATE.activeSection === 'people'`.

- [ ] **Step 1: Add the People sample data and render functions**

Using the Edit tool, find this exact anchor in the file (the last two lines of Task 1's script):

```
renderShell();
</script>
```

Replace it with:

```
const PEOPLE_SAMPLE = [
  { name:'Andrea Whitmore',  type:'customer', lastSeen:'2026-07-24', aliasCount:3 },
  { name:'Miles Rasmussen',  type:'lead',     lastSeen:'2026-07-21', aliasCount:2 },
  { name:'Baxter Pattison',  type:'lead',     lastSeen:'2026-07-01', aliasCount:4 },
  { name:'Quinn Delgado',    type:'internal', lastSeen:'2026-07-28', aliasCount:1 },
  { name:'Taylor Beckett',   type:'lead',     lastSeen:'2026-07-18', aliasCount:2 },
  { name:'Razer Athletics',  type:'partner',  lastSeen:'2026-07-15', aliasCount:5 },
  { name:'Nicole Hartley',   type:'internal', lastSeen:'2026-07-27', aliasCount:0 },
  { name:'Orca Fitness',     type:'customer', lastSeen:'2026-07-09', aliasCount:2 },
  { name:'FSP Strength',     type:'partner',  lastSeen:'2026-06-30', aliasCount:3 },
  { name:'J. Alvarez',       type:'unknown',  lastSeen:'2026-06-22', aliasCount:1 },
];

const PEOPLE_FILTERS = [
  { value:'all',      label:'All People' },
  { value:'lead',     label:'Leads' },
  { value:'customer', label:'Customers' },
  { value:'partner',  label:'Partners' },
  { value:'internal', label:'Internal' },
  { value:'unknown',  label:'Unknown' },
];

function renderPeopleSubpanel(container) {
  container.innerHTML = `
    <div class="subpanel-label">People</div>
    ${PEOPLE_FILTERS.map(f => `
      <button class="sub-item${f.value === STATE.activeSubFilter ? ' active' : ''}" data-filter="${f.value}">${esc(f.label)}</button>
    `).join('')}`;
  container.querySelectorAll('.sub-item').forEach(btn => {
    btn.addEventListener('click', () => selectSubFilter(btn.dataset.filter));
  });
}

function renderPeopleMain(main) {
  const filter = STATE.activeSubFilter;
  const filtered = filter === 'all' ? PEOPLE_SAMPLE : PEOPLE_SAMPLE.filter(p => p.type === filter);
  const filterLabel = PEOPLE_FILTERS.find(f => f.value === filter).label;
  main.innerHTML = `
    <h1>${esc(filterLabel)}</h1>
    <p class="sub">${filtered.length} ${filtered.length === 1 ? 'person' : 'people'}</p>
    <input class="search-input" placeholder="Search names, aliases, email&hellip;" />
    <div id="people-list"></div>
    <button class="btn-primary">+ Add Person</button>`;
  const list = main.querySelector('#people-list');
  list.innerHTML = filtered.length
    ? filtered.map(p => `
        <div class="row">
          <span class="name">${esc(p.name)}</span>
          <span class="badge badge-${p.type}">${esc(p.type)}</span>
          <span class="meta">${esc(p.lastSeen)}</span>
          <span class="meta">${p.aliasCount} alias${p.aliasCount === 1 ? '' : 'es'}</span>
        </div>`).join('')
    : '<p class="placeholder-note">No people match this filter.</p>';
}

renderShell();
</script>
```

- [ ] **Step 2: Verify People filtering end-to-end**

Reload the page (server from Task 1 is still running) and evaluate:

```js
() => {
  const rows = document.querySelectorAll('#people-list .row');
  const heading = document.querySelector('#main-content h1').textContent.trim();
  return { heading, rowCount: rows.length };
}
```

Expected: `heading: "All People"`, `rowCount: 10` (the full `PEOPLE_SAMPLE` length).

Click the "Leads" sub-panel item and re-evaluate:

```
browser_click({ target: "button.sub-item:has-text('Leads')" })
```

```js
() => {
  const rows = [...document.querySelectorAll('#people-list .row')];
  return {
    heading: document.querySelector('#main-content h1').textContent.trim(),
    rowCount: rows.length,
    allLeadBadges: rows.every(r => r.querySelector('.badge-lead')),
  };
}
```

Expected: `heading: "Leads"`, `rowCount: 3` (Miles, Baxter, Taylor), `allLeadBadges: true`.

Click "All People" to reset before moving to Task 3:

```
browser_click({ target: "button.sub-item:has-text('All People')" })
```

---

## Task 3: Work Section — Sub-panel Filters + Sample Data

**Files:**
- Modify: `/private/tmp/claude-501/-Users-trentluecke-dev-Claude-Projects-chief-of-staff/c76a2967-0676-4cf6-9961-5b53d3062e37/scratchpad/registry-sidebar-mockup.html`

**Interfaces:**
- Consumes: `STATE.activeSubFilter`, `esc()`, `selectSubFilter()` (all from Task 1).
- Produces:
  - `WORK_DATA` object `{ projects: [{id, name, tasks:[{id, text, done}]}], standalone: [{id, text, done}], routines: [{id, name, cadence}] }`.
  - `renderWorkSubpanel(container)` — called by Task 1's `renderSubpanel()` when `STATE.activeSection === 'work'`.
  - `renderWorkMain(main)` — called by Task 1's `renderMain()` when `STATE.activeSection === 'work'`.

- [ ] **Step 1: Add the Work sample data and render functions**

Using the Edit tool, find this exact anchor (the end of Task 2's script, now the last two lines):

```
renderShell();
</script>
```

Replace it with:

```
const WORK_DATA = {
  projects: [
    { id:'proj_1', name:'OS Workflow Builder pitch', tasks:[
      { id:'t1', text:'Send updated deck to Teofe', done:false },
      { id:'t2', text:'Confirm Nango pricing tier', done:false },
      { id:'t3', text:'Draft rollout phase doc', done:true },
    ]},
    { id:'proj_2', name:"Buyer's Story Program", tasks:[
      { id:'t4', text:'Schedule Andrea interview', done:false },
      { id:'t5', text:'Review Layer 2 QBR scope', done:false },
    ]},
  ],
  standalone: [
    { id:'t6', text:'Reply to Miles re: FSP pricing', done:false },
    { id:'t7', text:'Sync pipeline cache from Notion', done:false },
    { id:'t8', text:'Renew Avoma API key', done:true },
  ],
  routines: [
    { id:'r1', name:'Weekly pipeline review', cadence:'Every Monday' },
    { id:'r2', name:'Onboarding tracker sync', cadence:'Daily' },
  ],
};

const WORK_FILTERS = [
  { value:'all',        label:'All Work' },
  { value:'projects',   label:'Projects' },
  { value:'standalone', label:'Standalone' },
  { value:'routines',   label:'Routines' },
];

function renderWorkSubpanel(container) {
  container.innerHTML = `
    <div class="subpanel-label">Work</div>
    ${WORK_FILTERS.map(f => `
      <button class="sub-item${f.value === STATE.activeSubFilter ? ' active' : ''}" data-filter="${f.value}">${esc(f.label)}</button>
    `).join('')}`;
  container.querySelectorAll('.sub-item').forEach(btn => {
    btn.addEventListener('click', () => selectSubFilter(btn.dataset.filter));
  });
}

function taskRowHtml(t) {
  return `
    <div class="row">
      <span class="name" style="${t.done ? 'text-decoration:line-through;color:var(--muted)' : ''}">${esc(t.text)}</span>
      ${t.done ? '<span class="meta">done</span>' : ''}
    </div>`;
}

function renderWorkMain(main) {
  const filter = STATE.activeSubFilter;
  const filterLabel = WORK_FILTERS.find(f => f.value === filter).label;
  const showProjects = filter === 'all' || filter === 'projects';
  const showStandalone = filter === 'all' || filter === 'standalone';
  const showRoutines = filter === 'all' || filter === 'routines';

  let body = '';
  if (showProjects) {
    body += WORK_DATA.projects.map(p => `
      <div class="subpanel-label" style="margin-top:14px">${esc(p.name)}</div>
      ${p.tasks.map(taskRowHtml).join('')}`).join('');
  }
  if (showStandalone) {
    body += `<div class="subpanel-label" style="margin-top:14px">Standalone</div>${WORK_DATA.standalone.map(taskRowHtml).join('')}`;
  }
  if (showRoutines) {
    body += `<div class="subpanel-label" style="margin-top:14px">Routines</div>${WORK_DATA.routines.map(r => `
      <div class="row"><span class="name">${esc(r.name)}</span><span class="meta">${esc(r.cadence)}</span></div>`).join('')}`;
  }

  main.innerHTML = `
    <h1>${esc(filterLabel)}</h1>
    <p class="sub">${WORK_DATA.projects.length} projects &middot; ${WORK_DATA.standalone.length} standalone &middot; ${WORK_DATA.routines.length} routines</p>
    <div id="work-body">${body}</div>`;
}

renderShell();
</script>
```

- [ ] **Step 2: Verify Work filtering end-to-end**

Reload and evaluate:

```js
() => {
  document.querySelector("button.rail-item:has-text('Work')")?.click();
  return {
    heading: document.querySelector('#main-content h1').textContent.trim(),
    projectLabels: [...document.querySelectorAll('#work-body .subpanel-label')].map(e => e.textContent.trim()),
  };
}
```

(If `:has-text` isn't supported in a plain `querySelector`, use the `browser_click` tool instead: `browser_click({ target: "button.rail-item:has-text('Work')" })`, then evaluate separately.)

Expected after clicking Work (default filter `all`): `heading: "All Work"`, `projectLabels` contains `"OS Workflow Builder pitch"`, `"Buyer's Story Program"`, `"Standalone"`, and `"Routines"` — all four groups visible.

Click "Projects" sub-panel item:

```
browser_click({ target: "button.sub-item:has-text('Projects')" })
```

```js
() => ({
  heading: document.querySelector('#main-content h1').textContent.trim(),
  projectLabels: [...document.querySelectorAll('#work-body .subpanel-label')].map(e => e.textContent.trim()),
})
```

Expected: `heading: "Projects"`, `projectLabels` contains only the two project names — no `"Standalone"` or `"Routines"` entries.

---

## Task 4: Full Verification Pass, Encoding Safety, and Publish

**Files:**
- Modify: `/private/tmp/claude-501/-Users-trentluecke-dev-Claude-Projects-chief-of-staff/c76a2967-0676-4cf6-9961-5b53d3062e37/scratchpad/registry-sidebar-mockup.html` (only if verification finds an issue)

**Interfaces:**
- Consumes: the complete file produced by Tasks 1–3.
- Produces: a published Artifact URL to report back to Trent.

- [ ] **Step 1: Click through every rail item and confirm correct flat vs. nested behavior**

With the Task 1 server still running (`http://localhost:8793/registry-sidebar-mockup.html`), reload, then for each of the 6 rail items click it and evaluate:

```js
() => {
  const active = document.querySelector('#rail-list .rail-item.active');
  return {
    activeLabel: active.textContent.trim(),
    subpanelHidden: document.getElementById('subpanel-container').classList.contains('hidden'),
    mainHeading: document.querySelector('#main-content h1').textContent.trim(),
  };
}
```

Expected results per section:

| Rail item | `subpanelHidden` | `mainHeading` |
|---|---|---|
| Today | `true` | `"Today"` |
| Pending | `true` | `"Pending"` |
| People | `false` | `"All People"` (subFilter resets to `all` on section change) |
| Work | `false` | `"All Work"` |
| Notes | `true` | `"Notes"` |
| Meetings | `true` | `"Meetings"` |

If any row doesn't match, stop and fix `renderMain()` or `renderSubpanel()` in the file before continuing — do not proceed to publish with a failing check.

- [ ] **Step 2: Scan for encoding issues (mojibake)**

```js
() => {
  const text = document.getElementById('main-content').innerText + document.querySelector('.lead-in p').innerText;
  const badChars = (text.match(/â|Â|€/g) || []).length;
  return { badChars, textSample: text.slice(0, 120) };
}
```

Expected: `badChars: 0`. If any non-zero count appears, find the offending raw Unicode character (em dash, middot, ellipsis) in the source and replace it with its HTML entity (`&mdash;`, `&middot;`, `&hellip;`) or a `\u` escape inside `<script>` strings — do not leave raw multi-byte characters in the file.

- [ ] **Step 3: Verify dark-host contrast safety one more time on the finished file**

```js
() => {
  document.documentElement.setAttribute('data-theme', 'dark');
  const bodyBg = getComputedStyle(document.body).backgroundColor;
  const h1Color = getComputedStyle(document.querySelector('.lead-in h1')).color;
  const stageBg = getComputedStyle(document.getElementById('stage')).backgroundColor;
  document.documentElement.removeAttribute('data-theme');
  return { bodyBg, h1Color, stageBg };
}
```

Expected: `bodyBg` dark, `h1Color` light (previewer chrome follows host theme safely), `stageBg` is `rgb(253, 253, 252)` (`#fdfdfc`) regardless of host theme — the registry shell itself must NOT change with `data-theme`, since it's a fixed design direction, not another themeable palette.

- [ ] **Step 4: Take a full-page screenshot for the record**

```
browser_take_screenshot({ type: "png", scale: "css", fullPage: true, filename: "registry-sidebar-final.png" })
```

Read the resulting image and visually confirm: rail on the left with 6 labeled icon rows, People sub-panel visible with 6 filter options, main content showing the People list with correctly colored badges, previewer chrome (title + description) readable above the frame.

- [ ] **Step 5: Stop the local verification server**

```bash
pkill -f "http.server 8793"
```

- [ ] **Step 6: Publish via the Artifact tool**

Call the `Artifact` tool with:
- `file_path`: `/private/tmp/claude-501/-Users-trentluecke-dev-Claude-Projects-chief-of-staff/c76a2967-0676-4cf6-9961-5b53d3062e37/scratchpad/registry-sidebar-mockup.html`
- `description`: `"Sidebar nav + Airtable-inspired reskin preview for the People Registry — rail with People/Work sub-panels, forest accent theme."`
- `favicon`: `"🌲"` (distinct from the `🎨` favicon used on the first reskin artifact, since this is a different artifact about a different decision — the nav+theme direction, not the palette picker)

- [ ] **Step 7: Report the published URL and a short summary back to Trent**

Summarize: what changed structurally (rail replaces tabs; People/Work get sub-panels; others stay flat), the theme applied (forest accent, Airtable-inspired restraint), and that this is still mockup-only — real `tools/registry_ui.html` port is a follow-up round pending his reaction.

---

## Self-Review Notes

- **Spec coverage:** Layout spec (rail width, sub-panel width, which sections nest) → Task 1. People sub-panel items/filter → Task 2. Work sub-panel items/filter → Task 3. Aesthetic spec (exact tokens, badge colors unchanged, accent restraint) → Task 1's CSS. Dark/light chrome safety carried forward → Task 1 Step 3 and Task 4 Step 3. Icon set caveat (don't reuse wireframe glyphs) → Task 1's `ICONS` object uses considered SVGs, not the placeholder dingbats. Deliverable (published artifact, mockup-only, no real functionality) → Task 4.
- **Placeholder scan:** No TBD/TODO left in any step; every code block is complete, runnable content, not a description of content.
- **Type consistency:** `STATE.activeSubFilter` values are consistent across Task 2 (`all|lead|customer|partner|internal|unknown`) and Task 3 (`all|projects|standalone|routines`) — each section's own filter vocabulary, reset to `'all'` on every section change by Task 1's `selectSection()`. `renderPeopleSubpanel`/`renderPeopleMain` and `renderWorkSubpanel`/`renderWorkMain` names match exactly what Task 1's `renderSubpanel()`/`renderMain()` look up via `typeof ... === 'function'`.
