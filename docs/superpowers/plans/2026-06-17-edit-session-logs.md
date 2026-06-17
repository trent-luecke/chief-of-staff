# Edit & Delete Saved Session Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Registry UI Meetings tab edit a saved session log's body and delete a session entirely.

**Architecture:** The Meetings store is event-sourced (`data/meetings.jsonl`). Add `update_session` and `delete_session` event types + writers in `lib/meetings.py`, expose PATCH/DELETE routes in `tools/server.py`, and add inline Edit/Delete affordances per session in `tools/registry_ui.html`. Mirrors the existing thread edit/delete pattern exactly.

**Tech Stack:** Python (Flask), vanilla JS (single HTML file), pytest.

## Global Constraints

- Edit applies to the session **body only**; `date` and `ts` are never changed by an edit (preserves reverse-chronological sort order).
- Unknown `session_id` on update/delete is a tolerated no-op during replay (same as `update_thread`).
- Server routes use the existing `_write_main`, `_meeting_exists`, `_meeting_doc_after_write` helpers and return `{ "meeting": <doc>, "push": <status> }`.
- No date editing, no edit-history rendering, no bulk operations (YAGNI).

---

### Task 1: Data layer — `update_session` / `delete_session` replay + writers

**Files:**
- Modify: `lib/meetings.py` (replay in `replay_meetings_content`, ~line 61; writers after `append_add_session`, ~line 143)
- Test: `tests/test_meetings_lib.py`

**Interfaces:**
- Consumes: `_FakeStore` (existing test helper), `replay_meetings_content`, `append_create`, `append_add_session`.
- Produces:
  - `append_update_session(storage, meeting_id: str, session_id: str, body: str) -> dict` — writes `{"event":"update_session","id":meeting_id,"ts":...,"session_id":session_id,"body":body}`.
  - `append_delete_session(storage, meeting_id: str, session_id: str) -> dict` — writes `{"event":"delete_session","id":meeting_id,"ts":...,"session_id":session_id}`.
  - Replay applies `update_session` (set `body`, set `edited_ts` from event `ts`) and `delete_session` (remove session).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_meetings_lib.py`:

```python
def test_replay_update_session_changes_body():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "original"},
        {"event": "update_session", "id": "x", "ts": "2026-06-02T09:00:00",
         "session_id": "s-1", "body": "edited"},
    ])
    sess = m.replay_meetings_content(c)["x"]["sessions"][0]
    assert sess["body"] == "edited"
    assert sess["date"] == "2026-06-01"   # date unchanged
    assert sess["edited_ts"] == "2026-06-02T09:00:00"


def test_replay_delete_session_removes_it():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "gone soon"},
        {"event": "delete_session", "id": "x", "ts": "2026-06-02T09:00:00", "session_id": "s-1"},
    ])
    assert m.replay_meetings_content(c)["x"]["sessions"] == []


def test_replay_update_unknown_session_is_noop():
    c = _content([
        {"event": "create_meeting", "id": "x", "ts": "2026-06-01T10:00:00"},
        {"event": "add_session", "id": "x", "ts": "2026-06-01T10:01:00",
         "session_id": "s-1", "date": "2026-06-01", "body": "kept"},
        {"event": "update_session", "id": "x", "ts": "2026-06-02T09:00:00",
         "session_id": "s-nope", "body": "ignored"},
        {"event": "delete_session", "id": "x", "ts": "2026-06-02T09:01:00", "session_id": "s-nope"},
    ])
    sessions = m.replay_meetings_content(c)["x"]["sessions"]
    assert [s["session_id"] for s in sessions] == ["s-1"]
    assert sessions[0]["body"] == "kept"


def test_append_update_and_delete_session_writers():
    store = _FakeStore()
    m.append_create(store, "x")
    add = m.append_add_session(store, "x", "2026-06-12", "first draft")
    sid = add["session_id"]
    upd = m.append_update_session(store, "x", sid, "second draft")
    assert upd["event"] == "update_session"
    assert upd["session_id"] == sid
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["sessions"][0]["body"] == "second draft"
    dele = m.append_delete_session(store, "x", sid)
    assert dele["event"] == "delete_session"
    state = m.replay_meetings_content(store.read("meetings.jsonl"))
    assert state["x"]["sessions"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_meetings_lib.py -k "update_session or delete_session" -v`
Expected: FAIL — `AttributeError: module 'lib.meetings' has no attribute 'append_update_session'` and assertion failures on replay.

- [ ] **Step 3: Add replay handling**

In `lib/meetings.py`, inside `replay_meetings_content`, after the `add_session` block (ends ~line 67), add:

```python
        elif etype == "update_session":
            for s in mtg["sessions"]:
                if s["session_id"] == ev["session_id"]:
                    if "body" in ev:
                        s["body"] = ev["body"]
                    s["edited_ts"] = ev["ts"]
                    break
        elif etype == "delete_session":
            mtg["sessions"] = [s for s in mtg["sessions"] if s["session_id"] != ev["session_id"]]
```

- [ ] **Step 4: Add writers**

In `lib/meetings.py`, after `append_add_session` (~line 143), add:

```python
def append_update_session(storage, meeting_id: str, session_id: str, body: str) -> dict:
    ev = {"event": "update_session", "id": meeting_id, "ts": _ts(),
          "session_id": session_id, "body": body}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev


def append_delete_session(storage, meeting_id: str, session_id: str) -> dict:
    ev = {"event": "delete_session", "id": meeting_id, "ts": _ts(), "session_id": session_id}
    storage.append_line("meetings.jsonl", json.dumps(ev))
    return ev
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_meetings_lib.py -v`
Expected: PASS (all tests, including the new four and the pre-existing ones).

- [ ] **Step 6: Commit**

```bash
git add lib/meetings.py tests/test_meetings_lib.py
git commit -m "feat(meetings): add update_session/delete_session events + writers"
```

---

### Task 2: Server — PATCH & DELETE session routes

**Files:**
- Modify: `tools/server.py` (add two routes after `add_meeting_session`, which ends ~line 591)
- Test: manual curl check (no server test harness exists for these routes; the thread routes have none either, so we match the established convention and verify by hand)

**Interfaces:**
- Consumes: `meetings_lib.append_update_session`, `meetings_lib.append_delete_session`, `meetings_lib.replay_meetings_content`, `_write_main`, `_meeting_doc_after_write` (all existing).
- Produces:
  - `PATCH /api/meetings/<meeting_id>/sessions/<session_id>` (body required)
  - `DELETE /api/meetings/<meeting_id>/sessions/<session_id>`

- [ ] **Step 1: Add the two routes**

In `tools/server.py`, immediately after the `add_meeting_session` function (ends ~line 591, before `@app.route("/api/meetings/<meeting_id>/threads", methods=["POST"])`), add:

```python
@app.route("/api/meetings/<meeting_id>/sessions/<session_id>", methods=["PATCH"])
def patch_meeting_session(meeting_id: str, session_id: str):
    body = request.get_json(force=True)
    if not body or not body.get("body"):
        return jsonify({"error": "body is required"}), 400

    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        if not mtg or not any(s["session_id"] == session_id for s in mtg["sessions"]):
            return None
        meetings_lib.append_update_session(store, meeting_id, session_id, body["body"])
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: update session {session_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})


@app.route("/api/meetings/<meeting_id>/sessions/<session_id>", methods=["DELETE"])
def delete_meeting_session(meeting_id: str, session_id: str):
    def mutate(store):
        state = meetings_lib.replay_meetings_content(store.read("meetings.jsonl") or "")
        mtg = state.get(meeting_id)
        if not mtg or not any(s["session_id"] == session_id for s in mtg["sessions"]):
            return None
        meetings_lib.append_delete_session(store, meeting_id, session_id)
        return _meeting_doc_after_write(store, meeting_id)

    result, push, status = _write_main(mutate, f"data: delete session {session_id}")
    if status >= 500:
        return jsonify({"error": push.get("status", "write_failed"), "push": push}), status
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"meeting": result, "push": push})
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "import tools.server"`
Expected: no output, exit 0 (no syntax/route errors).

- [ ] **Step 3: Commit**

```bash
git add tools/server.py
git commit -m "feat(server): PATCH/DELETE routes for meeting session logs"
```

---

### Task 3: UI — inline Edit / Delete per session

**Files:**
- Modify: `tools/registry_ui.html` (session render ~lines 3285-3289; wiring in `wireMeetingDoc` ~line 3366)

**Interfaces:**
- Consumes: existing `patchMeeting(method, path, payload)`, `renderMeetingsView()`, `el()`, `esc()`.
- Produces: per-session DOM with `data-session-id`, `[data-session-edit]`, `[data-session-del]`, and an inline editor (`[data-session-save]`, `[data-session-cancel]`).

- [ ] **Step 1: Update the session render block**

In `tools/registry_ui.html`, replace the `sessionsHtml` block (currently ~lines 3285-3289):

```javascript
  const sessionsHtml = (m.sessions || []).map(s => `
    <div class="mtg-session">
      <div class="mtg-session-date">${esc(s.date)}</div>
      <div class="mtg-session-body">${esc(s.body)}</div>
    </div>`).join('') || '<div class="mtg-empty">No sessions logged.</div>';
```

with:

```javascript
  const sessionsHtml = (m.sessions || []).map(s => `
    <div class="mtg-session" data-session-id="${esc(s.session_id)}">
      <div class="mtg-session-date">
        ${esc(s.date)}
        <button class="mtg-row-btn" data-session-edit title="Edit">✎</button>
        <button class="mtg-row-btn" data-session-del title="Delete">✕</button>
      </div>
      <div class="mtg-session-body">${esc(s.body)}</div>
    </div>`).join('') || '<div class="mtg-empty">No sessions logged.</div>';
```

- [ ] **Step 2: Add the session edit/delete wiring**

In `tools/registry_ui.html`, inside `wireMeetingDoc`, immediately after the `el('mtg-session-save')` click handler (ends ~line 3370, before the closing `}` of `wireMeetingDoc`), add:

```javascript
  doc.querySelectorAll('.mtg-session').forEach(row => {
    const sid = row.dataset.sessionId;
    if (!sid) return;
    const bodyDiv = row.querySelector('.mtg-session-body');
    const editBtn = row.querySelector('[data-session-edit]');
    const delBtn = row.querySelector('[data-session-del]');
    if (editBtn) editBtn.addEventListener('click', () => {
      const current = bodyDiv.textContent;
      bodyDiv.innerHTML = `
        <textarea class="mtg-add-input" data-session-input rows="3"></textarea>
        <button class="mtg-row-btn" data-session-save style="border:1px solid var(--border);padding:4px 10px;margin-top:4px">Save</button>
        <button class="mtg-row-btn" data-session-cancel style="padding:4px 10px;margin-top:4px">Cancel</button>`;
      const input = bodyDiv.querySelector('[data-session-input]');
      input.value = current;
      input.focus();
      bodyDiv.querySelector('[data-session-cancel]').addEventListener('click', () => renderMeetingsView());
      bodyDiv.querySelector('[data-session-save]').addEventListener('click', async () => {
        const body = input.value.trim();
        if (!body) return;
        if (await patchMeeting('PATCH', `/sessions/${sid}`, { body })) renderMeetingsView();
      });
    });
    if (delBtn) delBtn.addEventListener('click', async () => {
      if (!confirm('Delete this session log?')) return;
      if (await patchMeeting('DELETE', `/sessions/${sid}`, {})) renderMeetingsView();
    });
  });
```

- [ ] **Step 3: Manual verification in the browser**

Launch the Registry UI (`registry-ui` skill or `python3 tools/server.py`), open the Meetings tab, select a meeting with at least one session.
- Click ✎ on a session → textarea appears pre-filled → edit text → Save → body updates, date unchanged.
- Click ✎ → Cancel → original body restored, no change.
- Click ✕ → confirm → session disappears.
Expected: all three behave as described; no console errors.

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(ui): inline edit/delete for meeting session logs"
```

---

## Self-Review

**Spec coverage:**
- Edit body only → Task 1 replay (`update_session` sets body only) + Task 2 PATCH + Task 3 editor. ✓
- Delete session → Task 1 (`delete_session`) + Task 2 DELETE + Task 3 ✕ button. ✓
- Date fixed on edit → Task 1 test asserts `date` unchanged; editor doesn't touch date. ✓
- Unknown id tolerated → Task 1 `test_replay_update_unknown_session_is_noop`. ✓
- Failure modes (empty body 400, offline handling) → Task 2 400 guard; Task 3 reuses `patchMeeting` alert. ✓

**Placeholder scan:** No TBD/TODO; all code shown verbatim. ✓

**Type consistency:** `append_update_session(storage, meeting_id, session_id, body)` and `append_delete_session(storage, meeting_id, session_id)` used identically in Tasks 1 and 2. Event field names (`session_id`, `body`, `edited_ts`) consistent across replay, writers, and tests. UI `data-session-id` / `data-session-edit` / `data-session-del` consistent between render and wiring. ✓
