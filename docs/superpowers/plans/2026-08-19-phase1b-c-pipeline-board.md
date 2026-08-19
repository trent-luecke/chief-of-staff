# Phase 1b (c) — Pipeline Kanban Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Depends on Plan a** (`build_deals` + the extended fold) being merged. Independent of Plan b, but both touch `tools/server.py` and `tools/registry_ui.html`, so execute **after** Plan b to avoid merge churn.

**Goal:** Give Trent a visual pipeline he can look at — a Kanban board (columns = deal stage, cards = deals) in a new "Pipeline" tab of the Registry UI — as the light replacement for the Notion pipeline database. It is a pure *rendering of the fold*: no new data model, no hand-editable rows.

**Architecture:** This is design §3.9 (the pipeline view, task t-a43140) brought forward into Phase 1b. The board reads the folded deals — the same `build_deals(...)` output that already drives the projection and the review queue. The server computes the full deal list in `rebuild_snapshot` (so it's fresh after every write) and serves it from `GET /api/deals`. The UI adds a `Pipeline` rail tab that renders deals bucketed by `Deal.stage`. **Read-only for stage:** stage is derived from events (demo/trial/sale), never hand-set — so there is no drag-to-change-stage. A card that needs review shows a badge linking to the Today tab's review queue (Plan b). This preserves the event-sourced source of truth: the board mirrors reality, it does not become a second, mutable store.

**Tech Stack:** Python 3 / Flask (`tools/server.py`), vanilla JS + HTML (`tools/registry_ui.html`), `pytest`, manual browser verification.

## Global Constraints

- **The board is a view, not a store.** It renders `build_deals(...)` output. Nothing on this board mutates deal state directly; stage changes only ever happen by new events flowing through the fold. Do not add a "set stage" or drag-to-move control.
- **Freshness via snapshot.** The deal list is computed in `rebuild_snapshot` (bootstrap / refresh / post-write), identical to Plan b's `deals_review`. Never freeze it into a file.
- **Stage vocabulary is fixed and future-ready:** columns are `demoed → in_trial → won → lost`, shown in that order, **including empty columns** (In Trial / Won are empty until the trial/sale normalizers land — that's honest, not a bug).
- **Escape all interpolated data** with `esc(...)`. Reuse `fetchJSON` for the GET.
- **Server tests:** `python -m pytest tests/test_server_deals.py -q` green. **Full suite:** `python -m pytest -q` green.

---

## File Structure

- `tools/server.py` — **modify.** Add `SNAPSHOT.deals` (a board-shaped list), compute it in `rebuild_snapshot`, add it to `/api/bootstrap`, add `GET /api/deals`.
- `tools/registry_ui.html` — **modify.** Add the `Pipeline` rail button, the `view-pipeline` container, router wiring, `renderPipelineView()`, and Kanban CSS.
- `tests/test_server_deals.py` — **modify** (created in Plan b). Add board-shape tests. If executing Plan c standalone, create it with the `_client` helper from Plan b Task 1.

---

## Task 1: Serve the full deal list — `GET /api/deals`

**Files:**
- Modify: `tools/server.py`
- Test: `tests/test_server_deals.py`

**Interfaces:**
- Consumes: `build_deals`, `load_events`, `load_crosswalk` (already imported in Plan b; if executing standalone, add the imports from Plan b Task 1 Step 3).
- Produces: `SNAPSHOT.deals` = a list of board rows; `GET /api/deals` returns `{"deals": [...], "stages": ["demoed","in_trial","won","lost"]}`. Each row: `{deal_key, account_name, rep, stage, outcome, demo_date, last_event_at, deal_value, contact_emails, needs_review, review_kind}`.

- [ ] **Step 1: Write the failing test**

```python
def test_get_deals_returns_board_rows(monkeypatch):
    ev = {"event_id": "e1", "email": "jane@acme.com", "email_raw": "", "kind": "demo",
          "timestamp": "2026-08-17T00:00:00Z", "account_name": "", "rep": "Luke Martin",
          "source": "avoma",
          "payload": {"avoma_uuid": "u1", "contact_emails": ["jane@acme.com"],
                      "ambiguous_reason": None}}
    srv, c = _client(monkeypatch, json.dumps(ev) + "\n")
    r = c.get("/api/deals")
    assert r.status_code == 200
    body = r.get_json()
    assert body["stages"] == ["demoed", "in_trial", "won", "lost"]
    row = body["deals"][0]
    assert row["deal_key"] == "jane@acme.com"
    assert row["stage"] == "demoed"
    assert row["rep"] == "Luke Martin"
    assert row["needs_review"] is False


def test_get_deals_marks_review_and_lost(monkeypatch):
    demo = {"event_id": "e1", "email": "x@acme.com", "email_raw": "", "kind": "demo",
            "timestamp": "2026-06-01T00:00:00Z", "account_name": "", "rep": "Luke",
            "source": "avoma",
            "payload": {"avoma_uuid": "u1", "contact_emails": ["x@acme.com"], "ambiguous_reason": None}}
    srv, c = _client(monkeypatch, json.dumps(demo) + "\n")  # aged → stale_check
    row = c.get("/api/deals").get_json()["deals"][0]
    assert row["needs_review"] is True
    assert row["review_kind"] == "stale_check"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_server_deals.py -k get_deals -v`
Expected: FAIL (`404`).

- [ ] **Step 3: Implement**

In `tools/server.py` add a field to `_Snapshot.__init__`:

```python
        self.deals = []
```

Add the stage constant and shaper near `_compute_deals_review` (added in Plan b):

```python
_DEAL_STAGES = ["demoed", "in_trial", "won", "lost"]


def _compute_deals_board(store) -> list:
    today = datetime.now(timezone.utc).date().isoformat()
    deals = build_deals(load_events(store), load_crosswalk(store), today,
                        stale_days=_DEAL_STALE_DAYS)
    rows = []
    for key in sorted(deals):
        d = deals[key]
        rows.append({
            "deal_key": d.email,
            "account_name": d.account_name,
            "rep": d.rep,
            "stage": d.stage or "demoed",
            "outcome": d.outcome,
            "demo_date": d.demo_date,
            "last_event_at": d.last_event_at,
            "deal_value": d.deal_value,
            "contact_emails": list(d.contact_emails),
            "needs_review": bool(d.review.get("needs")),
            "review_kind": d.review.get("kind", ""),
        })
    return rows
```

In `rebuild_snapshot`, after the `SNAPSHOT.deals_review = ...` line (Plan b), add:

```python
    SNAPSHOT.deals = _compute_deals_board(store)
```

Add `"deals": SNAPSHOT.deals,` to the `/api/bootstrap` payload, and add the route near `get_deals_review`:

```python
@app.route("/api/deals", methods=["GET"])
def get_deals():
    return jsonify({"deals": SNAPSHOT.deals, "stages": _DEAL_STAGES})
```

*(If executing Plan c without Plan b: also add the `lib.deal_events` / `lib.deal_fold` / `lib.deal_crosswalk` imports and the `_DEAL_STALE_DAYS = 45` constant from Plan b Task 1 Step 3.)*

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_server_deals.py -k get_deals -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/server.py tests/test_server_deals.py
git commit -m "feat(server): GET /api/deals board rows from snapshot"
```

---

## Task 2: Add the Pipeline tab (rail button, container, router)

**Files:**
- Modify: `tools/registry_ui.html`
- Test: manual (verified in Task 3).

**Interfaces:**
- Produces: a `Pipeline` rail item, a `#view-pipeline` container, and router wiring that calls `renderPipelineView()` on tab switch.

- [ ] **Step 1: Add the rail button** — after the Meetings `rail-item` button (around line 1080 in `tools/registry_ui.html`), add:

```html
      <button class="rail-item" data-view="pipeline"><span class="ic"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="3.5" height="12" rx="1"/><rect x="8.25" y="4" width="3.5" height="8" rx="1"/><rect x="13.5" y="4" width="3.5" height="5" rx="1"/></svg></span>Pipeline</button>
```

- [ ] **Step 2: Add the view container** — after `<div id="view-meetings" ...>` (around line 1090), add:

```html
      <div id="view-pipeline" class="view hidden"></div>
```

- [ ] **Step 3: Register the view in `switchTab`** — add `'pipeline'` to the array (around line 1990):

```javascript
  ['today','pending','registry','observations','work','notes','meetings','pipeline'].forEach(v => {
    el(`view-${v}`).classList.toggle('hidden', v !== name);
  });
```

- [ ] **Step 4: Dispatch render on tab click** — in `setupTabs` (around line 3268), add after the `meetings` line:

```javascript
      if (view === 'pipeline') renderPipelineView();
```

- [ ] **Step 5: Commit** (with Task 3 — the tab is inert without the renderer, so commit them together). Skip a standalone commit here.

---

## Task 3: Render the Kanban board

**Files:**
- Modify: `tools/registry_ui.html`
- Test: manual browser verification.

**Interfaces:**
- Consumes: `GET /api/deals`.
- Produces: `renderPipelineView()` — a column-per-stage board of deal cards.

- [ ] **Step 1: Add CSS** — near the other view styles in `tools/registry_ui.html` (e.g. after the Today-tab block), add:

```css
    #view-pipeline { max-width: 1400px; }
    .pipe-board { display:flex; gap:12px; align-items:flex-start; overflow-x:auto; padding-bottom:8px; }
    .pipe-col { flex:1 1 0; min-width:220px; background:var(--panel,#161616); border:1px solid var(--border,#2a2a2a); border-radius:10px; padding:8px; }
    .pipe-col h4 { margin:4px 6px 8px; display:flex; justify-content:space-between; font-size:13px; text-transform:capitalize; }
    .pipe-col h4 .pipe-count { opacity:.6; }
    .pipe-card { background:var(--bg,#0e0e0e); border:1px solid var(--border,#2a2a2a); border-radius:8px; padding:8px 10px; margin-bottom:8px; }
    .pipe-card .pc-acct { font-weight:600; font-size:13px; }
    .pipe-card .pc-meta { font-size:12px; opacity:.7; margin-top:2px; }
    .pipe-badge { display:inline-block; font-size:11px; padding:1px 6px; border-radius:10px; background:#5a3b00; color:#ffcf87; margin-top:6px; cursor:pointer; }
    .pipe-col-empty { font-size:12px; opacity:.5; padding:6px; }
```

- [ ] **Step 2: Implement `renderPipelineView()`** — add near `renderTodayView` in `tools/registry_ui.html`:

```javascript
async function renderPipelineView() {
  const view = el('view-pipeline');
  view.innerHTML = '<div class="muted" style="padding:20px">Loading…</div>';
  let data;
  try {
    data = await fetchJSON(`${API}/api/deals`);
  } catch {
    view.innerHTML = `<div class="empty-state"><h3>Server Offline</h3><p>Run: python tools/server.py</p></div>`;
    return;
  }
  const stages = data.stages || [];
  const deals = data.deals || [];
  const byStage = Object.fromEntries(stages.map(s => [s, []]));
  deals.forEach(d => { (byStage[d.stage] || (byStage[d.stage] = [])).push(d); });

  const stageLabel = { demoed: 'Demoed', in_trial: 'In Trial', won: 'Won', lost: 'Lost' };
  const fmt = iso => iso ? new Date(iso).toLocaleDateString() : '—';

  const cols = stages.map(s => {
    const cards = (byStage[s] || []).map(d => `
      <div class="pipe-card">
        <div class="pc-acct">${esc(d.account_name || d.deal_key)}</div>
        <div class="pc-meta">${esc(d.rep || 'unassigned')} · last ${esc(fmt(d.last_event_at))}</div>
        ${d.deal_value ? `<div class="pc-meta">$${esc(d.deal_value)}</div>` : ''}
        ${d.needs_review ? `<span class="pipe-badge" data-goto-review="1">${d.review_kind === 'ambiguous' ? 'needs identity' : 'needs 45-day check'}</span>` : ''}
      </div>`).join('');
    return `<div class="pipe-col">
      <h4><span>${esc(stageLabel[s] || s)}</span><span class="pipe-count">${(byStage[s] || []).length}</span></h4>
      ${cards || '<div class="pipe-col-empty">No deals</div>'}
    </div>`;
  }).join('');

  view.innerHTML = `
    <div class="today-header">
      <h2>Pipeline</h2>
      <button id="pipe-refresh" class="btn">Refresh</button>
      <span class="muted" style="margin-left:8px">${deals.length} deal${deals.length === 1 ? '' : 's'}</span>
    </div>
    <div class="pipe-board">${cols}</div>`;

  el('pipe-refresh').addEventListener('click', async () => { await refreshFromMain(); renderPipelineView(); });
  view.querySelectorAll('[data-goto-review]').forEach(b =>
    b.addEventListener('click', () => { switchTab('today'); renderTodayView(); }));
}
```

- [ ] **Step 3: Manual browser verification**

```bash
python3 tools/server.py
```

Against `http://localhost:8787`:
1. Click the **Pipeline** rail tab. Expect four columns — Demoed / In Trial / Won / Lost — with the real `jcook.tpa@gmail.com` deal as a card under **Demoed** (In Trial and Won empty).
2. The card shows the rep and last-contacted date; because that deal is `free_email`, it shows a **needs identity** badge.
3. Click the badge → the app switches to the Today tab and the review queue is visible.
4. `read_console_messages` → no errors.

Expected: four-column board renders, the demo deal appears under Demoed with a review badge, the badge jumps to the review queue, no console errors.

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(ui): pipeline kanban board tab (read-only, folded from events)"
```

---

## Self-Review

- **Goal coverage:** new Pipeline tab (Task 2) rendering a stage-column Kanban (Task 3) from `GET /api/deals` (Task 1) — the visual pipeline replacing the Notion database view.
- **Event-sourcing preserved:** the board is read-only for stage; no control mutates deal state; stage changes only via events through the fold. Documented in Global Constraints and enforced by having no write path on this surface.
- **Freshness:** `SNAPSHOT.deals` recomputed in `rebuild_snapshot`, consistent with Plan b's `deals_review`.
- **Future-ready:** In Trial / Won columns render empty now and fill in automatically once the trial/sale normalizers (follow-on) start emitting those events — no board change needed.
- **Type consistency:** board row fields (`deal_key`, `stage`, `needs_review`, `review_kind`, `rep`, `last_event_at`, `deal_value`) are produced once in `_compute_deals_board` (Task 1) and consumed unchanged in `renderPipelineView` (Task 3); stage list `["demoed","in_trial","won","lost"]` defined once as `_DEAL_STAGES`.
- **Placeholder scan:** none — every step carries real code and exact commands.
