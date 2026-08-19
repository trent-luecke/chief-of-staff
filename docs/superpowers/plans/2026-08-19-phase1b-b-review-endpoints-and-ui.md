# Phase 1b (b) — Review Endpoints + Today-Tab UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Depends on Plan a** (`2026-08-19-phase1b-a-deal-fold-and-read-model.md`) being merged: this plan calls `build_deals`, `build_deals_to_review`, `load_events`, and the `status`/`manual` event contracts it defines.

**Goal:** Surface the two review queues in the Registry UI's Today tab, and turn Trent's decisions into `status`/`manual` DealEvents written back to `origin/main`, so a resolved flag clears on the next fold.

**Architecture:** The Registry server (`tools/server.py`) reads `origin/main` as the single source of truth via a `SNAPSHOT` rebuilt on bootstrap, on refresh, and after every write. This plan computes the review queues *inside* `rebuild_snapshot` (folding the live event log) and serves them from `GET /api/deals/review`. Two write endpoints — `POST /api/deals/status` and `POST /api/deals/review` — append DealEvents through the existing `_write_main` path (commit to `origin/main` via a throwaway worktree, exactly like `/api/tasks`). Because `_write_main` rebuilds the snapshot on success, a decision recomputes the queues immediately — the acted-on deal drops off without waiting for the 7am cron. The email brief gets a read-only count + "open Today" link only.

**Tech Stack:** Python 3 / Flask (`tools/server.py`), vanilla JS + HTML (`tools/registry_ui.html`), `pytest` for the server, manual browser verification for the UI.

## Global Constraints

- **Deal identity travels in the POST body, not the URL.** The deal key is an email or `unresolved:<uuid>` — colons and `@` are awkward and ambiguous in a path. Routes are `POST /api/deals/status` and `POST /api/deals/review`; both take `{"deal_key": "..."}` in the JSON body. (Resolves the handoff's open question; the fold re-derives the key on the next fold, so this is merge-safe.)
- **Every write goes through `_write_main(mutate, msg_fn)`** and returns its `(result, push, status)`; on `status >= 500` return the error JSON, never a phantom success. Copy the `/api/tasks` POST handler's shape exactly.
- **Human decisions are DealEvents**, appended via `append_events(store, [ev])` to `data/deal_events.jsonl` (already in the `.gitignore` un-ignore allow-list, already `merge=union` in `.gitattributes`, already in `avoma_sync.yml`'s commit-back). No new persistence wiring.
- **The interactive queue must be fresh.** It is computed in `rebuild_snapshot` and re-served after each write — never frozen into `brief_today.json`. The brief file carries only a read-only summary.
- **Never render an auto-Lost.** Queue B's only outcome-changing action is the explicit **Lost** button.
- **UI writes use `fetchJSON(url, {method:'POST', body, label})`** — it already drives the offline guard + toast arc. Escape all interpolated data with `esc(...)`.
- **Server tests:** `python -m pytest tests/test_server_deals.py -q` green. **Existing suite:** `python -m pytest -q` stays green.

---

## File Structure

- `tools/server.py` — **modify.** Add `SNAPSHOT.deals_review`, compute it in `rebuild_snapshot`, add it to `/api/bootstrap`, add `GET /api/deals/review`, `POST /api/deals/status`, `POST /api/deals/review`.
- `tools/registry_ui.html` — **modify.** Fetch and render the review block under Meetings in `renderTodayView`; add card markup, action handlers, and the on-hold date picker; add minimal CSS under the existing `/* ── Today tab ── */` block.
- `processors/today_brief.py` — **modify.** Add a read-only `deals_to_review` summary (counts) to the brief dict via `build_deals_to_review`.
- `tests/test_server_deals.py` — **create.** Endpoint tests with a fake `_write_main`/store.
- `tests/test_today_brief.py` — **modify (or create if absent).** Assert the brief carries the review summary.

---

## Task 1: Compute the review queues in the snapshot + `GET /api/deals/review`

**Files:**
- Modify: `tools/server.py`
- Test: `tests/test_server_deals.py` (create)

**Interfaces:**
- Consumes: `build_deals`, `build_deals_to_review` (`lib.deal_fold`); `load_events` (`lib.deal_events`); `load_crosswalk` (`lib.deal_crosswalk`).
- Produces: `SNAPSHOT.deals_review` (the `build_deals_to_review` dict); `GET /api/deals/review` returns it; `/api/bootstrap` includes `deals_review`.

- [ ] **Step 1: Write the failing test** (Flask test client; monkeypatch the git-backed read so no network/git is needed)

```python
# tests/test_server_deals.py
import json
import importlib


def _client(monkeypatch, events_jsonl):
    import tools.server as srv
    importlib.reload(srv)

    def fake_show_main(path):
        if path.endswith("deal_events.jsonl"):
            return events_jsonl
        return None  # everything else empty

    monkeypatch.setattr(srv.git_sync, "show_main", fake_show_main)
    monkeypatch.setattr(srv.git_sync, "fetch_main", lambda: True)
    srv.rebuild_snapshot(known_online=True)
    srv.app.config["TESTING"] = True
    return srv, srv.app.test_client()


def test_get_deals_review_returns_two_queues(monkeypatch):
    ev = {"event_id": "e1", "email": "jane@acme.com", "email_raw": "", "kind": "demo",
          "timestamp": "2026-08-17T00:00:00Z", "account_name": "", "rep": "Luke Martin",
          "source": "avoma",
          "payload": {"avoma_uuid": "u1", "contact_emails": ["jane@acme.com"],
                      "ambiguous_reason": "free_email"}}
    srv, c = _client(monkeypatch, json.dumps(ev) + "\n")
    r = c.get("/api/deals/review")
    assert r.status_code == 200
    body = r.get_json()
    assert body["counts"]["identity"] == 1
    assert body["identity"][0]["deal_key"] == "jane@acme.com"


def test_bootstrap_includes_deals_review(monkeypatch):
    srv, c = _client(monkeypatch, "")
    body = c.get("/api/bootstrap").get_json()
    assert "deals_review" in body
    assert body["deals_review"]["counts"]["total"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_server_deals.py -v`
Expected: FAIL (`404` on `/api/deals/review`; `deals_review` missing from bootstrap).

- [ ] **Step 3: Implement**

In `tools/server.py`, add imports near the other `lib.*` imports:

```python
from lib.deal_events import load_events, append_events, DealEvent, make_event_id
from lib.deal_fold import build_deals, build_deals_to_review
from lib.deal_crosswalk import load_crosswalk
```

Add a field to `_Snapshot.__init__`:

```python
        self.deals_review = {"identity": [], "stale": [], "counts": {"identity": 0, "stale": 0, "total": 0}}
```

Add a helper above `rebuild_snapshot`:

```python
_DEAL_STALE_DAYS = 45  # matches config.json → deals.stale_days


def _compute_deals_review(store) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    deals = build_deals(load_events(store), load_crosswalk(store), today,
                        stale_days=_DEAL_STALE_DAYS)
    return build_deals_to_review(deals)
```

In `rebuild_snapshot`, after `SNAPSHOT.brief = ...`, add:

```python
    SNAPSHOT.deals_review = _compute_deals_review(store)
```

Add `"deals_review": SNAPSHOT.deals_review,` to the `/api/bootstrap` JSON payload, and add the route (place it near `get_brief_today`):

```python
@app.route("/api/deals/review", methods=["GET"])
def get_deals_review():
    return jsonify(SNAPSHOT.deals_review)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_server_deals.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/server.py tests/test_server_deals.py
git commit -m "feat(server): compute + serve deal review queues from snapshot"
```

---

## Task 2: `POST /api/deals/status` — Lost / On-hold / Still-active

**Files:**
- Modify: `tools/server.py`
- Test: `tests/test_server_deals.py`

**Interfaces:**
- Consumes: body `{"deal_key": str, "status": "lost"|"hold"|"active", "lost_reason"?: str, "check_back"?: "YYYY-MM-DD"}`.
- Produces: appends a `status` DealEvent to `deal_events.jsonl` on `origin/main`; returns `{"event": {...}, "push": {...}}`, 201.

- [ ] **Step 1: Write the failing test** (fake `_write_main` so no real git; assert the event that would be appended)

```python
def test_post_status_lost_appends_status_event(monkeypatch):
    srv, c = _client(monkeypatch, "")
    captured = {}

    def fake_write_main(mutate, msg_fn):
        store = srv._read_store()
        result = mutate(store)
        captured["dirty"] = store.dirty()
        return result, {"status": "ok"}, 200

    monkeypatch.setattr(srv, "_write_main", fake_write_main)
    r = c.post("/api/deals/status", json={"deal_key": "x@acme.com", "status": "lost",
                                          "lost_reason": "budget"})
    assert r.status_code == 201
    line = captured["dirty"]["data/deal_events.jsonl"].strip().splitlines()[-1]
    ev = json.loads(line)
    assert ev["kind"] == "status" and ev["email"] == "x@acme.com"
    assert ev["payload"] == {"status": "lost", "lost_reason": "budget"}


def test_post_status_hold_requires_check_back(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/status", json={"deal_key": "x@acme.com", "status": "hold"})
    assert r.status_code == 400


def test_post_status_rejects_unknown_status(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/status", json={"deal_key": "x@acme.com", "status": "won"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_server_deals.py -k post_status -v`
Expected: FAIL (`404`).

- [ ] **Step 3: Implement**

Add a shared appender helper and the route in `tools/server.py`:

```python
def _append_deal_event(store, kind: str, deal_key: str, payload: dict):
    ts = datetime.now(timezone.utc).isoformat()
    ev = DealEvent(
        event_id=make_event_id(kind, f"{deal_key}|{ts}", deal_key),
        email=deal_key, email_raw="", kind=kind, timestamp=ts,
        account_name="", rep="", source="ui", payload=payload,
    )
    append_events(store, [ev])
    return ev


@app.route("/api/deals/status", methods=["POST"])
def post_deal_status():
    body = request.get_json(force=True) or {}
    deal_key = body.get("deal_key")
    status = body.get("status")
    if not deal_key or status not in ("lost", "hold", "active"):
        return jsonify({"error": "deal_key and status in {lost,hold,active} required"}), 400
    payload = {"status": status}
    if status == "lost":
        if body.get("lost_reason"):
            payload["lost_reason"] = body["lost_reason"]
    elif status == "hold":
        if not body.get("check_back"):
            return jsonify({"error": "hold requires check_back (YYYY-MM-DD)"}), 400
        payload["check_back"] = body["check_back"]

    def mutate(store):
        return _append_deal_event(store, "status", deal_key, payload)

    ev, push, http = _write_main(mutate, lambda e: f"data: deal status {status} {deal_key}")
    if http >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), http
    import dataclasses
    return jsonify({"event": dataclasses.asdict(ev), "push": push}), 201
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_server_deals.py -k post_status -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/server.py tests/test_server_deals.py
git commit -m "feat(server): POST /api/deals/status (lost/hold/active)"
```

---

## Task 3: `POST /api/deals/review` — identity resolution (manual events)

**Files:**
- Modify: `tools/server.py`
- Test: `tests/test_server_deals.py`

**Interfaces:**
- Consumes: body `{"deal_key": str, "action": "confirm"|"choose_primary"|"merge"|"split"|"not_a_deal", "primary_email"?: str, "merge_with"?: str, "groups"?: [[str,...],...]}`.
- Produces: appends a `manual` DealEvent; returns `{"event", "push"}`, 201.

- [ ] **Step 1: Write the failing tests**

```python
def test_post_review_confirm_appends_manual_event(monkeypatch):
    srv, c = _client(monkeypatch, "")
    captured = {}

    def fake_write_main(mutate, msg_fn):
        store = srv._read_store()
        result = mutate(store)
        captured["dirty"] = store.dirty()
        return result, {"status": "ok"}, 200

    monkeypatch.setattr(srv, "_write_main", fake_write_main)
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "confirm"})
    assert r.status_code == 201
    ev = json.loads(captured["dirty"]["data/deal_events.jsonl"].strip().splitlines()[-1])
    assert ev["kind"] == "manual" and ev["payload"]["action"] == "confirm"


def test_post_review_choose_primary_requires_email(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": "info@acme.com", "action": "choose_primary"})
    assert r.status_code == 400


def test_post_review_merge_carries_merge_with(monkeypatch):
    srv, c = _client(monkeypatch, "")
    captured = {}
    monkeypatch.setattr(srv, "_write_main",
                        lambda mutate, msg_fn: (mutate(srv._read_store()), {"status": "ok"}, 200))
    # capture via a second call path: re-run mutate to inspect
    r = c.post("/api/deals/review", json={"deal_key": "b@beta.com", "action": "merge",
                                          "merge_with": "a@acme.com"})
    assert r.status_code == 201
    assert r.get_json()["event"]["payload"]["merge_with"] == "a@acme.com"


def test_post_review_rejects_unknown_action(monkeypatch):
    srv, c = _client(monkeypatch, "")
    r = c.post("/api/deals/review", json={"deal_key": "x@acme.com", "action": "frobnicate"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_server_deals.py -k post_review -v`
Expected: FAIL (`404`).

- [ ] **Step 3: Implement**

```python
@app.route("/api/deals/review", methods=["POST"])
def post_deal_review():
    body = request.get_json(force=True) or {}
    deal_key = body.get("deal_key")
    action = body.get("action")
    if not deal_key or action not in ("confirm", "choose_primary", "merge", "split", "not_a_deal"):
        return jsonify({"error": "deal_key and a valid action required"}), 400
    payload = {"action": action}
    if action == "choose_primary":
        if not body.get("primary_email"):
            return jsonify({"error": "choose_primary requires primary_email"}), 400
        payload["primary_email"] = body["primary_email"]
    elif action == "merge":
        if not body.get("merge_with"):
            return jsonify({"error": "merge requires merge_with"}), 400
        payload["merge_with"] = body["merge_with"]
    elif action == "split":
        groups = body.get("groups")
        if not groups or not isinstance(groups, list):
            return jsonify({"error": "split requires groups: [[email,...],...]"}), 400
        payload["groups"] = groups

    def mutate(store):
        return _append_deal_event(store, "manual", deal_key, payload)

    ev, push, http = _write_main(mutate, lambda e: f"data: deal review {action} {deal_key}")
    if http >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), http
    import dataclasses
    return jsonify({"event": dataclasses.asdict(ev), "push": push}), 201
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_server_deals.py -k post_review -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/server.py tests/test_server_deals.py
git commit -m "feat(server): POST /api/deals/review (identity resolution)"
```

---

## Task 4: Render the review block in the Today tab

**Files:**
- Modify: `tools/registry_ui.html`
- Test: manual browser verification (steps below).

**Interfaces:**
- Consumes: `GET /api/deals/review`, `POST /api/deals/status`, `POST /api/deals/review`.
- Produces: a "Deals to review" section rendered **under Meetings** with Queue A (identity) and Queue B (45-day) cards and working actions.

- [ ] **Step 1: Add CSS** under the existing `/* ── Today tab ── */` block (near line 968 in `tools/registry_ui.html`):

```css
    .deal-review-card { border:1px solid var(--border,#2a2a2a); border-radius:8px; padding:10px 12px; margin:8px 0; }
    .deal-review-card .drc-head { display:flex; gap:8px; align-items:baseline; flex-wrap:wrap; }
    .deal-review-card .drc-acct { font-weight:600; }
    .deal-review-reason { font-size:12px; opacity:.7; }
    .deal-review-actions { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
    .deal-review-actions .btn { padding:3px 10px; font-size:12px; }
    .deal-review-hold { display:none; gap:6px; margin-top:6px; align-items:center; }
    .deal-review-hold.open { display:flex; }
```

- [ ] **Step 2: Fetch the queues alongside the brief** — in `renderTodayView`, change the fetch to also load the review queues. Replace the `try { brief = ... }` block with:

```javascript
  let brief, review;
  try {
    [brief, review] = await Promise.all([
      fetchJSON(`${API}/api/brief_today`),
      fetchJSON(`${API}/api/deals/review`),
    ]);
  } catch {
    view.innerHTML = `<div class="empty-state"><h3>Server Offline</h3><p>Run: python tools/server.py</p></div>`;
    return;
  }
```

- [ ] **Step 3: Build the review HTML** — add before the `view.innerHTML = ...` assignment:

```javascript
  const reasonText = {
    multi_domain: 'attendees span multiple companies',
    no_email: 'no usable prospect email',
    generic_inbox: 'only a generic inbox (info@/sales@)',
    free_email: 'personal email — no company name',
    account_conflict: 'matched an existing deal on a different account',
  };
  const idCards = (review?.identity || []).map(d => `
    <div class="deal-review-card" data-key="${esc(d.deal_key)}">
      <div class="drc-head">
        <span class="drc-acct">${esc(d.account_name || d.deal_key)}</span>
        <span class="deal-review-reason">${esc(reasonText[d.reason] || d.reason)}</span>
      </div>
      <div class="muted" style="font-size:12px">${esc((d.contact_emails||[]).join(', '))}</div>
      <div class="deal-review-actions">
        <button class="btn" data-act="confirm">Confirm</button>
        <button class="btn" data-act="not_a_deal">Not a deal</button>
      </div>
    </div>`).join('');
  const staleCards = (review?.stale || []).map(d => `
    <div class="deal-review-card" data-key="${esc(d.deal_key)}">
      <div class="drc-head">
        <span class="drc-acct">${esc(d.account_name || d.deal_key)}</span>
        <span class="deal-review-reason">no movement in 45 days${d.rep ? ' · ' + esc(d.rep) : ''}</span>
      </div>
      <div class="deal-review-actions">
        <button class="btn" data-act="lost">Lost</button>
        <button class="btn" data-act="active">Still active</button>
        <button class="btn" data-act="hold-toggle">On hold…</button>
      </div>
      <div class="deal-review-hold">
        <input type="date" class="drc-date">
        <button class="btn" data-act="hold-save">Save</button>
      </div>
    </div>`).join('');
  const reviewCount = (review?.counts?.total) || 0;
  const reviewHtml = reviewCount
    ? `<section><h3>Deals to review (${reviewCount})</h3>
         ${idCards ? `<h4 class="muted">Identity (${review.counts.identity})</h4>${idCards}` : ''}
         ${staleCards ? `<h4 class="muted">45-day check (${review.counts.stale})</h4>${staleCards}` : ''}
       </section>`
    : '';
```

- [ ] **Step 4: Insert the block under Meetings** — in the `view.innerHTML` template, add `${reviewHtml}` immediately after the Meetings `<section>` and before the Needs `<section>`:

```javascript
    <section><h3>Meetings</h3>${meetingsHtml}</section>
    ${reviewHtml}
    <section><h3>Needs you today</h3><ul class="today-needs">${needsHtml}</ul></section>
```

- [ ] **Step 5: Wire the action handlers** — after the existing `el('today-refresh')...` handler at the end of `renderTodayView`, add:

```javascript
  async function postDeal(url, payload, label) {
    try {
      await fetchJSON(`${API}${url}`, { method: 'POST', body: JSON.stringify(payload), label });
      await renderTodayView();  // re-fold clears the resolved flag
    } catch (e) { /* fetchJSON already toasted */ }
  }
  view.querySelectorAll('.deal-review-card').forEach(card => {
    const key = card.dataset.key;
    card.querySelectorAll('[data-act]').forEach(btn => btn.addEventListener('click', () => {
      const act = btn.dataset.act;
      if (act === 'confirm') return postDeal('/api/deals/review', { deal_key: key, action: 'confirm' }, 'Deal confirmed');
      if (act === 'not_a_deal') return postDeal('/api/deals/review', { deal_key: key, action: 'not_a_deal' }, 'Marked not a deal');
      if (act === 'lost') return postDeal('/api/deals/status', { deal_key: key, status: 'lost' }, 'Marked lost');
      if (act === 'active') return postDeal('/api/deals/status', { deal_key: key, status: 'active' }, 'Marked active');
      if (act === 'hold-toggle') return card.querySelector('.deal-review-hold').classList.toggle('open');
      if (act === 'hold-save') {
        const date = card.querySelector('.drc-date').value;
        if (!date) return toast('Pick a check-back date', 'error');
        return postDeal('/api/deals/status', { deal_key: key, status: 'hold', check_back: date }, 'On hold');
      }
    }));
  });
```

- [ ] **Step 6: Manual browser verification**

Start the server and drive the Today tab in the browser preview:

```bash
python3 tools/server.py
```

Then, using the browser preview against `http://localhost:8787`:
1. Confirm a "Deals to review" section renders under Meetings with the real `jcook.tpa@gmail.com` free-email deal in the Identity queue.
2. Click **Confirm** on it → toast fires, and after the re-render the card is gone (flag cleared on the next fold).
3. Read `read_console_messages` — no errors.

Expected: the card disappears after Confirm (proving the resolved flag clears on re-fold), no console errors.

- [ ] **Step 7: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(ui): deals-to-review block in Today tab with quick actions"
```

---

## Task 5: Read-only review summary in the email brief

**Files:**
- Modify: `processors/today_brief.py`
- Test: `tests/test_today_brief.py`

**Interfaces:**
- Consumes: `build_deals`, `build_deals_to_review`, `load_events`, `load_crosswalk` (folded from the passed `storage`).
- Produces: `build_today_brief(...)` return dict gains `"deals_to_review": {"counts": {...}}` — counts only (the email can't carry working buttons; the UI is the actionable surface).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_today_brief.py  (add; create the file if it does not exist)
from processors.today_brief import build_today_brief
from lib.storage import LocalStorage


def test_brief_carries_deal_review_counts(tmp_path):
    store = LocalStorage(str(tmp_path))
    store.append_line("deal_events.jsonl",
        '{"event_id":"e1","email":"x@acme.com","email_raw":"","kind":"demo",'
        '"timestamp":"2026-06-01T00:00:00Z","account_name":"","rep":"Luke",'
        '"source":"avoma","payload":{"avoma_uuid":"u1","contact_emails":["x@acme.com"],'
        '"ambiguous_reason":null}}')  # aged → stale_check
    brief = build_today_brief([], [], ["teambuildr.com"], "2026-08-18",
                              "2026-08-18T12:00:00Z", config={}, storage=store)
    assert brief["deals_to_review"]["counts"]["stale"] == 1
    assert brief["deals_to_review"]["counts"]["total"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_today_brief.py::test_brief_carries_deal_review_counts -v`
Expected: FAIL (`KeyError: 'deals_to_review'`).

- [ ] **Step 3: Implement**

In `processors/today_brief.py`, add imports at the top:

```python
from lib.deal_events import load_events
from lib.deal_crosswalk import load_crosswalk
from lib.deal_fold import build_deals, build_deals_to_review
```

Add a helper above `build_today_brief`:

```python
def _deal_review_summary(storage, today: str, stale_days: int = 45) -> dict:
    if storage is None:
        return {"counts": {"identity": 0, "stale": 0, "total": 0}}
    deals = build_deals(load_events(storage), load_crosswalk(storage), today, stale_days=stale_days)
    review = build_deals_to_review(deals)
    return {"counts": review["counts"]}  # email is read-only: counts + "open Today" link
```

In `build_today_brief`, add the key to the returned dict:

```python
    return {
        "date": today,
        "generated_at": generated_at,
        "meetings": meetings,
        "needs_today": needs_items,
        "deals_to_review": _deal_review_summary(storage, today),
        "what_moved": [],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_today_brief.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (no regressions across brief/server/deal suites).

- [ ] **Step 6: Commit**

```bash
git add processors/today_brief.py tests/test_today_brief.py
git commit -m "feat(brief): read-only deal-review count in Today brief"
```

---

## Self-Review

- **Spec coverage (§3.10 mechanics):** `POST /api/deals/status` (lost/hold/active) → Task 2; `POST /api/deals/review` (identity) → Task 3; `_write_main` append pattern → Tasks 2–3; `registry_ui.html` block + quick actions + on-hold date picker → Task 4; email read-only summary + "open Today" link → Task 5; idempotent clear-on-fold → Task 1 (snapshot recompute) + Task 4 Step 6 (verified in browser).
- **Deal identity open question:** resolved — POST body `deal_key`, documented in Global Constraints.
- **Read-model performance open question:** folding on each `rebuild_snapshot` (bootstrap/refresh/post-write), not per GET — noted acceptable at current volume; a cached fold can come later.
- **Type consistency:** `deal_key`/`action`/`status`/`check_back`/`merge_with`/`groups`/`primary_email` field names match Plan a's payload contracts exactly; `build_deals_to_review` output shape consumed unchanged.
- **Placeholder scan:** none — every step carries real code and exact commands.
