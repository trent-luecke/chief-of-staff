# Registry UI: Sidebar Nav + Airtable-Inspired Reskin

**Status:** Approved — mockup phase
**Owner:** Trent Luecke
**Scope:** Design-exploration artifact only. Does NOT touch `tools/registry_ui.html` in this round.

## Problem

The People Registry's current top tab bar (`Today | Pending | People | Observations | Work | Notes | Meetings`) is flat and has no room to grow — a future 8th/9th section would just overflow the tab row. Separately, Trent finds the current dark, minimal theme fatiguing and wants something punchier and more "fun" to work in, without changing any interface behavior.

An earlier round (this same session) produced a top-tab reskin artifact with 5 alternate color palettes and 4 system-font options, purely as a CSS-variable swap. Trent reacted well to the exercise but wants to go one step further: restructure navigation into a sidebar (Airtable-like) that has room for nested "layers" under specific sections, and pair it with a genuinely new aesthetic direction rather than reskinning the existing dark theme.

## Non-Goals

- No changes to `tools/registry_ui.html`, `tools/server.py`, or any real data binding in this round. This spec covers a throwaway/reference **artifact mockup** only.
- No new functionality — every row, badge, button, and form that exists today must still exist; this is nav structure + visual theme only.
- Not scoping full nesting for every section — only People and Work get sub-panels (see below); everything else stays a flat click-through, identical in behavior to today's tabs.

## Reference Material

- `VoltAgent/awesome-design-md` GitHub repo → `design-md/airtable/DESIGN.md`. **Important caveat surfaced during this round:** this file documents Airtable's public **marketing/brand website** (hero bands, signature coral/forest cards, pricing pages) — it has no side-nav or app-shell spec. It's used here only for aesthetic DNA (palette restraint, type weight discipline, color-block-over-shadow elevation), not for layout, since it doesn't cover the product app.
- The real People/Work data shapes it must reflect: `type` field on people (`lead | customer | partner | internal | unknown`, existing badge classes), and `renderWorkView()`'s existing three groupings (Projects, Standalone tasks, Routines).

## Decisions (in order they were settled)

1. **Nesting concept:** "Layers" means real nested sub-sections (not just a flat list with room to grow) — an item can expand to reveal child views, evaluated via the visual companion against two lighter alternatives (grouped-header list, tabs-within-content).
2. **Which sections nest:** Only **People** and **Work**. Both need a parent view that still shows everything (all people; all work = projects + standalone + routines together) AND child views that filter down to one slice. This was explicit from Trent: *"I don't want to completely lose the wider visibility I have now... I could click into my projects sub-category if I only wanted to view those without the standalone tasks."*
3. **Aesthetic direction:** Airtable-inspired **fresh** direction, not a continuation of the 5 palettes from the earlier reskin artifact.
4. **Deliverable this round:** Another artifact mockup, not the real file. A follow-up round ports the approved direction into `tools/registry_ui.html`.
5. **Sidebar structure** (chosen over two alternatives via visual companion — inline expand/collapse tree, and flat-sidebar-with-content-header-tabs): **Icon rail + contextual sub-panel.** Clicking a section with children (People, Work) slides out a second narrow panel listing that section's views; sections without children (Today, Pending, Notes, Meetings) skip the sub-panel entirely and just fill the main content area, identical to today's tab behavior.
6. **Rail width/density:** Icon **+ label** on every row (~176px), not icon-only with tooltips — confirmed over the icon-only alternative because tooltip-guessing was judged worse than the modest width cost.
7. **Signature accent:** **Forest** (`#0a5c3d` / soft tint `#e2f0ea`), chosen live against two other options (Ink Indigo, Signature Rust) rendered in the actual rail+subpanel+content shell with real People rows and badges.
8. **Existing badge semantic colors** (lead/customer/partner/internal/unknown) are unchanged — they're a distinct functional color language from the one signature brand accent, which is reserved for active nav state, primary buttons, and focus rings only.

## Layout Spec

```
┌────────────┬──────────────┬─────────────────────────────┐
│ Rail 176px │ Sub-panel    │ Main content                 │
│            │ ~170px       │                               │
│ ◷ Today    │ (People only)│                               │
│ ◔ Pending  │ PEOPLE       │  <h1>All People</h1>          │
│ ☺ People ← │  All People ←│  <sub>126 people · ...</sub> │
│ ▤ Work     │  Leads       │  [search]                    │
│ ✎ Notes    │  Customers   │  rows...                     │
│ ◫ Meetings │  Partners    │                               │
│            │  Internal    │                               │
└────────────┴──────────────┴─────────────────────────────┘
```

- Rail is always visible, full height, ~176px, `surface-soft` background.
- Sub-panel only renders when the active rail item is People or Work. Width ~170px, sits flush against the rail, `canvas` background (slightly lighter than the rail to read as a distinct layer).
- Rail item active state and sub-panel item active state both use the signature-forest soft tint as background + forest text — one consistent "you are here" language across both levels.
- Sections without children (Today, Pending, Notes, Meetings) render main content directly against the rail, no sub-panel gap.
- Rail icons: the glyphs shown above (◷◔☺▤✎◫) are wireframe placeholders from the brainstorming stage, not a specified icon set — the artifact build should pick a considered, consistent glyph/icon language rather than reusing these literally.

### People sub-panel items
`All People` (default) → `Leads` → `Customers` → `Partners` → `Internal` → `Unknown` — each filters the existing registry list by the `type` badge field. "All People" is the unfiltered view exactly as it renders today.

### Work sub-panel items
`All Work` (default — today's full view: Projects + Standalone + Routines together) → `Projects` → `Standalone` → `Routines` — isolates one of `renderWorkView()`'s three existing groupings.

## Aesthetic Spec

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#fdfdfc` | Page background |
| `--ink` | `#181d26` | Headings, active nav text |
| `--body` | `#333840` | Running text |
| `--muted` | `#767b85` | Meta text, inactive nav labels |
| `--hairline` | `#e3e3e0` | Borders, dividers |
| `--surface-soft` | `#f7f6f3` | Rail background, search input fill |
| `--surface-strong` | `#ececea` | Active sub-panel item background |
| `--accent` (signature forest) | `#0a5c3d` | Active rail state, primary buttons, focus rings |
| `--accent-soft` | `#e2f0ea` | Active-state tint background |

Type stays at modest weight throughout — no bold display headings (Airtable's own documented principle: emphasis comes from size/color contrast, not boldness). Elevation is color-block-first: minimal shadow, depth communicated through the rail/sub-panel/content surface-tone steps rather than drop shadows.

Existing badge colors (unchanged):
- Lead: blue · Customer: green · Partner: amber · Internal: gray · Unknown: red

## Deliverable

One interactive HTML artifact (published via the Artifact tool) reproducing:
- The rail + sub-panel + content shell as specified above, fully clickable (rail items switch main content; People/Work sub-panel items filter within that section)
- Real-shaped sample data (people with the 5 type badges; work items across Projects/Standalone/Routines)
- The forest-accent Airtable-inspired theme applied throughout, both light and dark OS-theme-safe (carry forward the dark/light contrast-safety fix from the previous reskin round — background and ink must always move together on one signal)

Out of scope for the artifact: real data binding, actual add/edit/merge functionality (buttons can be visually present but need not be wired), server communication.

## Follow-Up (explicitly deferred, not part of this spec)

- Porting the approved shell + theme into `tools/registry_ui.html` (real DOM structure change: replacing the `.tabs` nav with the rail, adding sub-panel rendering logic, wiring the People/Work filters to existing `renderRegistryView`/`renderWorkView` data)
- Deciding whether Observations, Notes, or Meetings ever gain their own sub-panels later — explicitly not decided now, rail is built so this is possible later without a rebuild
