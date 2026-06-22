# Registry UI Action Feedback Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every mutating action in the Registry UI a visible "Saving → Saved" arc (corner toast + per-element spinner), and stop failed writes from silently looking successful.

**Architecture:** A small feedback layer (`toast`, `dismissToast`, `setBusy`, `withArc`) is added once to `tools/registry_ui.html`, then wired into the two helpers that all HTTP mutations already pass through — `fetchJSON` (tasks/projects/notes) and `patchMeeting` (meetings). Call sites gain optional labels, a per-element busy class, and — critically — only re-render on success. The older File-System-Access person-registry path (`writeJSON`) keeps its existing button feedback but routes errors/success through the same toast for consistency.

**Tech Stack:** Single self-contained HTML file — vanilla JS + CSS, no build step, no framework, no external libraries. CSS custom properties already defined in `:root` (`--success`, `--danger`, `--accent`, `--muted`, `--surface2`, `--border`, `--text`).

## Global Constraints

- **One file only:** all changes live in `tools/registry_ui.html`. No new files, no dependencies.
- **No external assets:** spinner and toast are pure CSS/DOM (CSP/offline-safe).
- **Toast position:** bottom-right (fixed). Per-element spinner stays in.
- **Failed write = no re-render:** on any mutation failure, show an error toast AND leave the view unchanged (do not call `onChanged()` / `renderWorkView()` / `renderMeetingsView()`). This is a hard requirement.
- **Reuse existing CSS vars** for color; do not introduce new hex colors except the error toast text tint `#fecaca`.
- **No automated JS test harness exists** for this HTML file. Verification is manual against the running UI (port 8787). Each task's verification steps are concrete and observable; a Playwright MCP browser session may be used to drive them, but manual confirmation is acceptable.

### Running the UI for verification

```bash
python3 tools/server.py   # serves UI on http://localhost:8787 ; reads/writes origin/main
```

Open `http://localhost:8787`. Requires network access to `origin/main`. To exercise the **error path**, stop the server (or disconnect network) after the page loads, then attempt a write — the server returns 503 / the fetch fails and the UI's offline mode engages.

---

## File Structure

All edits in `tools/registry_ui.html`:

- **CSS** (`<style>` block, after `:root` at line 22): toast host, toast variants, `.busy` spinner, `@keyframes spin`.
- **JS feedback primitives** (new block immediately above `fetchJSON`, ~line 1867): `toast`, `dismissToast`, `setBusy`, `withArc`.
- **`fetchJSON`** (line 1867): drive the arc for non-GET requests; re-throw on failure.
- **`wireTaskInteractions`** (lines 2077-2125): done/delete/due/owner — busy + labels + success-only re-render.
- **`wireAddTaskForm`** (lines 2160-2185): drop redundant alert.
- **Work view project handlers** (lines 2326-2337, 2505-2518, 2547-2554): success-only re-render + labels.
- **`patchMeeting`** + meeting handlers (lines 3318-3403): reuse arc, keep null contract, add labels.
- **New-meeting modal** (lines 3455-3471): replace alert with arc.
- **Person-registry handlers** (lines 1341-1349, 1592-1608, 1658-1674): alert → error toast + success toast.

---

## Task 1: Feedback primitives (toast, busy, arc)

The foundation. Adds CSS and four JS functions. Nothing is wired to real actions yet — this task is verified in isolation via the browser console.

**Files:**
- Modify: `tools/registry_ui.html` — CSS after line 22; JS block before line 1867.

**Interfaces:**
- Produces:
  - `toast(msg: string, kind?: 'success'|'error'|'pending', opts?: {ttl?: number}) → HTMLElement` — renders a bottom-right toast; auto-dismisses after `opts.ttl` ms (default 2000 success / 5000 error; `ttl: 0` = no auto-dismiss). Returns the toast element.
  - `dismissToast(t: HTMLElement) → void` — fades out and removes a toast.
  - `setBusy(el: HTMLElement, on?: boolean) → void` — toggles `.busy` (dim + spinner) and `aria-busy`. No-op if `el` is null.
  - `withArc(promise: Promise, label?: string) → Promise` — shows "Saving…" after a 250ms delay, morphs to `✓ <label||'Saved'>` on resolve or an error toast on reject; re-throws on reject. Returns the resolved value.

- [ ] **Step 1: Add the CSS**

Insert immediately after the closing `}` of the `:root` block (after line 22, before `*, *::before…`):

```css
    /* ── Action feedback: toast + busy ─────────────────────────────────── */
    @keyframes spin { to { transform: rotate(360deg); } }
    #toast-host {
      position: fixed; bottom: 16px; right: 16px;
      display: flex; flex-direction: column; gap: 8px;
      z-index: 9999; pointer-events: none;
    }
    .toast {
      pointer-events: auto;
      min-width: 150px; max-width: 320px;
      padding: 10px 14px; border-radius: 8px;
      font-size: 13px; line-height: 1.3; color: var(--text);
      background: var(--surface2); border: 1px solid var(--border);
      box-shadow: 0 4px 16px rgba(0,0,0,.4);
      opacity: 0; transform: translateY(8px);
      transition: opacity .18s ease, transform .18s ease;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
    .toast-success { border-color: var(--success); }
    .toast-error   { border-color: var(--danger); color: #fecaca; }
    .toast-pending { border-color: var(--muted); color: var(--muted); }
    .busy { opacity: .55; pointer-events: none; position: relative; }
    .busy::after {
      content: ''; position: absolute; top: 50%; left: 50%;
      width: 12px; height: 12px; margin: -6px 0 0 -6px;
      border: 2px solid var(--muted); border-top-color: var(--accent);
      border-radius: 50%; animation: spin .6s linear infinite;
    }
```

- [ ] **Step 2: Add the JS primitives**

Insert directly above `async function fetchJSON(url, opts = {}) {` (line 1867):

```javascript
// ── Action feedback: toast + busy + arc ───────────────────────────────────────
let _toastSeq = 0;
function toast(msg, kind = 'success', opts = {}) {
  let host = document.getElementById('toast-host');
  if (!host) {
    host = document.createElement('div');
    host.id = 'toast-host';
    document.body.appendChild(host);
  }
  const t = document.createElement('div');
  t.className = `toast toast-${kind}`;
  t.dataset.toastId = ++_toastSeq;
  t.textContent = msg;
  host.appendChild(t);
  requestAnimationFrame(() => t.classList.add('show'));
  const ttl = opts.ttl != null ? opts.ttl : (kind === 'error' ? 5000 : 2000);
  if (ttl > 0) setTimeout(() => dismissToast(t), ttl);
  return t;
}

function dismissToast(t) {
  if (!t || !t.parentNode) return;
  t.classList.remove('show');
  let removed = false;
  const kill = () => { if (!removed) { removed = true; t.remove(); } };
  t.addEventListener('transitionend', kill, { once: true });
  setTimeout(kill, 400); // fallback if transitionend never fires
}

function setBusy(el, on = true) {
  if (!el) return;
  el.classList.toggle('busy', on);
  if (on) el.setAttribute('aria-busy', 'true');
  else el.removeAttribute('aria-busy');
}

// Drives the Saving→Saved arc around an in-flight promise.
// Re-throws on failure so callers can skip their re-render.
async function withArc(promise, label) {
  let pending = null;
  const timer = setTimeout(() => { pending = toast('Saving…', 'pending', { ttl: 0 }); }, 250);
  try {
    const result = await promise;
    clearTimeout(timer);
    const msg = '✓ ' + (label || 'Saved');
    if (pending) {
      pending.className = 'toast toast-success show';
      pending.textContent = msg;
      setTimeout(() => dismissToast(pending), 2000);
    } else {
      toast(msg, 'success');
    }
    return result;
  } catch (err) {
    clearTimeout(timer);
    if (pending) dismissToast(pending);
    const detail = err && err.message ? ': ' + err.message : '';
    toast((label || 'Action') + ' failed' + detail, 'error');
    throw err;
  }
}
```

- [ ] **Step 3: Verify in the browser console**

Start the server (`python3 tools/server.py`), open `http://localhost:8787`, open DevTools console, run:

```javascript
toast('Hello world');                              // bottom-right, fades in, gone in ~2s
toast('Something broke', 'error');                 // red border/text, lingers ~5s
await withArc(new Promise(r => setTimeout(r, 800)), 'Task completed');  // "Saving…" → "✓ Task completed"
await withArc(Promise.resolve(), 'Quick save');    // fast: no "Saving…" flash, straight to "✓ Quick save"
try { await withArc(Promise.reject(new Error('nope')), 'Delete'); } catch(e){}  // red "Delete failed: nope"
const b = document.querySelector('.task-row'); setBusy(b); setTimeout(()=>setBusy(b,false), 1500);  // row dims + spinner, then clears
```

Expected: each behaves as commented. The 800ms case shows the pending→success morph; the resolved case skips "Saving…".

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(registry-ui): add toast/busy/arc feedback primitives

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Drive the arc from `fetchJSON`

Wire the arc into the helper every task/project/note mutation flows through. After this, any non-GET `fetchJSON` shows the arc automatically and throws on failure (callers updated in Task 3).

**Files:**
- Modify: `tools/registry_ui.html:1867-1881` (the `fetchJSON` function).

**Interfaces:**
- Consumes: `withArc`, `toast` (Task 1); existing `state`, `applyOnlineState`.
- Produces: `fetchJSON(url, opts)` — GET unchanged; for non-GET it drives `withArc`, accepts an optional `opts.label` (string) for the success/error message, and **throws** on failure (offline, 503, or non-OK). `opts.label` is stripped before reaching `fetch`.

- [ ] **Step 1: Replace `fetchJSON`**

Replace the entire current function (lines 1867-1881) with:

```javascript
async function fetchJSON(url, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase();
  const { label, ...fetchOpts } = opts;

  const doFetch = async () => {
    const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...fetchOpts });
    if (res.status === 503) {
      if (typeof state !== 'undefined') { state.online = false; }
      applyOnlineState();
      throw new Error('offline: write rejected by server');
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };

  if (method === 'GET') return doFetch();

  // Mutating request: block when known-offline, otherwise drive the feedback arc.
  if (typeof state !== 'undefined' && state.online === false) {
    applyOnlineState();
    toast('Offline — change not saved', 'error');
    throw new Error('offline: editing disabled until main is reachable');
  }
  return withArc(doFetch(), label);
}
```

- [ ] **Step 2: Verify success + arc on a real action**

Reload `http://localhost:8787`, go to the Work tab. Add a task via the "Add a task…" input and press Enter.
Expected: a `✓ Task added`/`✓ Saved` toast appears bottom-right (and `Saving…` first if the round-trip exceeds 250ms). The task list updates after. (The label says "Saved" until Task 3 adds the specific label — that's expected here.)

- [ ] **Step 3: Verify error path**

With the page loaded, stop the server (Ctrl-C in its terminal). Attempt another write (e.g. mark a task done).
Expected: a red error toast appears (e.g. `Action failed: HTTP …` or the offline message). No success toast.

- [ ] **Step 4: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(registry-ui): drive Saving→Saved arc from fetchJSON

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Work tab call sites — labels, busy, success-only re-render

Update task and project handlers so they label their action, mark the clicked element busy, and only re-render on success. This is where the phantom-success fix lands: the swallowing `.catch(() => {})` patterns are removed.

**Files:**
- Modify: `tools/registry_ui.html` — `wireTaskInteractions` (2077-2125), `wireAddTaskForm` submit (2160-2185), project edit save (2326-2338), project delete (2505-2518), standalone link-to-project owner change (2547-2554).

**Interfaces:**
- Consumes: `fetchJSON` (now arc-driven, throws on failure), `setBusy`.

- [ ] **Step 1: Rewrite the task interaction handler body**

Replace the body of `container.addEventListener('click', async e => { … })` in `wireTaskInteractions` (lines 2078-2123) with:

```javascript
    if (e.target.matches('.btn-done')) {
      const taskId = e.target.dataset.taskId;
      setBusy(e.target);
      try {
        await fetchJSON(`${API}/api/tasks/${encodeURIComponent(taskId)}/complete`, { method: 'POST', body: '{}', label: 'Task completed' });
        const row = document.getElementById(`task-row-${taskId}`);
        if (row) row.remove();
        if (!container.querySelector('.task-row')) onChanged();
      } catch (err) {
        setBusy(e.target, false);
      }
      return;
    }
    if (e.target.matches('.btn-delete-task')) {
      const taskId = e.target.dataset.taskId;
      const row = document.getElementById(`task-row-${taskId}`);
      const title = row?.querySelector('.task-title')?.textContent || taskId;
      if (!confirm(`Delete task "${title}"? This cannot be undone.`)) return;
      setBusy(e.target);
      try {
        await fetchJSON(`${API}/api/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE', label: 'Task deleted' });
        onChanged();
      } catch (err) {
        setBusy(e.target, false);
      }
      return;
    }
    if (e.target.matches('.due-chip') || e.target.matches('.due-ghost')) {
      const taskId = e.target.dataset.taskId;
      const cur = e.target.dataset.due || null;
      showDatePicker(e.target, cur, async iso => {
        if (iso !== cur) {
          try {
            await fetchJSON(`${API}/api/tasks/${encodeURIComponent(taskId)}`, {
              method: 'PATCH', body: JSON.stringify({ due_date: iso }), label: 'Task updated',
            });
            onChanged();
          } catch (err) { /* arc toasted; leave view unchanged */ }
        }
      });
      return;
    }
    if (e.target.matches('.owner-chip') || e.target.matches('.assign-ghost')) {
      const taskId = e.target.dataset.taskId;
      showOwnerDropdown(e.target, taskId, people, async newOwner => {
        try {
          await fetchJSON(`${API}/api/tasks/${encodeURIComponent(taskId)}`, {
            method: 'PATCH', body: JSON.stringify({ owner: newOwner }), label: 'Task updated',
          });
          onChanged();
        } catch (err) { /* arc toasted; leave view unchanged */ }
      });
    }
```

Note the behavior change: previously `onChanged()` ran unconditionally (even inside the `due`/`owner` callbacks where the catch swallowed errors). Now it runs only after a successful write.

- [ ] **Step 2: Drop the redundant alert in `wireAddTaskForm`**

In the `submit` function (lines 2160-2182), replace the `catch` block so the arc owns the error message. Change:

```javascript
    } catch (err) {
      alert('Failed to add task: ' + err.message);
    } finally {
      btn.disabled = false;
    }
```

to:

```javascript
    } catch (err) {
      /* arc toasted the failure */
    } finally {
      btn.disabled = false;
    }
```

And add the label to that call's options — change `body: JSON.stringify({` line's enclosing call (line 2165) so the options object includes `label: 'Task added'`:

```javascript
      await fetchJSON(`${API}/api/tasks`, {
        method: 'POST',
        label: 'Task added',
        body: JSON.stringify({
          title,
          source: 'ui',
          project_id: projectId || null,
          due_date: dueInput.dataset.isoDate || null,
          owner: ownerSel.value || null,
        }),
      });
```

- [ ] **Step 3: Project edit save — label + drop alert**

In the project edit save handler (lines 2330-2337), replace:

```javascript
      try {
        await fetchJSON(`${API}/api/projects/${encodeURIComponent(project.id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ canonical_name: name, status, members: draftMembers }),
        });
        workState.editing.delete(project.id);
        renderWorkView();
      } catch (err) { alert('Save failed: ' + err.message); }
```

with:

```javascript
      try {
        await fetchJSON(`${API}/api/projects/${encodeURIComponent(project.id)}`, {
          method: 'PATCH', label: 'Project updated',
          body: JSON.stringify({ canonical_name: name, status, members: draftMembers }),
        });
        workState.editing.delete(project.id);
        renderWorkView();
      } catch (err) { /* arc toasted; stay in edit mode */ }
```

- [ ] **Step 4: Project delete — busy + success-only re-render**

Replace lines 2514-2516:

```javascript
      btn.disabled = true;
      await fetchJSON(`${API}/api/projects/${encodeURIComponent(projId)}`, { method: 'DELETE' }).catch(() => {});
      renderWorkView();
```

with:

```javascript
      setBusy(btn);
      try {
        await fetchJSON(`${API}/api/projects/${encodeURIComponent(projId)}`, { method: 'DELETE', label: 'Project deleted' });
        renderWorkView();
      } catch (err) { setBusy(btn, false); }
```

- [ ] **Step 5: Standalone "link to project" — success-only re-render**

Replace lines 2549-2553:

```javascript
        if (!projId) return;
        await fetchJSON(`${API}/api/tasks/${encodeURIComponent(taskId)}`, {
          method: 'PATCH', body: JSON.stringify({ project_id: projId }),
        }).catch(() => {});
        renderWorkView();
```

with:

```javascript
        if (!projId) return;
        try {
          await fetchJSON(`${API}/api/tasks/${encodeURIComponent(taskId)}`, {
            method: 'PATCH', body: JSON.stringify({ project_id: projId }), label: 'Task updated',
          });
          renderWorkView();
        } catch (err) { /* arc toasted; leave view unchanged */ }
```

- [ ] **Step 6: Verify each Work-tab path (success)**

Reload the UI, Work tab. Confirm a toast with the right label and a brief busy spinner for each:
- Add a task → `✓ Task added`.
- Mark a task done → button spins → `✓ Task completed`, row removed.
- Set/change a due date → `✓ Task updated`.
- Assign/change an owner → `✓ Task updated`.
- Delete a task (confirm dialog) → `✓ Task deleted`.
- Delete a project (confirm dialog) → `✓ Project deleted`.
- Edit a project and save → `✓ Project updated`.
- Link a standalone task to a project → `✓ Task updated`.

- [ ] **Step 7: Verify failure leaves the view unchanged**

Stop the server. Click **Done** on a task.
Expected: red `Task completed failed: …` toast; the busy spinner clears; **the row stays in place** (no re-render, no phantom removal).

- [ ] **Step 8: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(registry-ui): label + busy + success-only re-render on Work tab

Removes phantom-success: failed task/project writes now surface an error
toast and leave the view unchanged instead of silently re-rendering.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Meetings tab — route `patchMeeting` and the new-meeting modal through the arc

`patchMeeting` callers use the pattern `if (await patchMeeting(...)) renderMeetingsView()`, which already skips the re-render when the call returns null. Keep that contract: drive the arc inside and return null on failure. The new-meeting modal uses a raw fetch + alert — convert it to the arc.

**Files:**
- Modify: `tools/registry_ui.html` — `patchMeeting` (3321-3329); agenda/thread/session call sites (3335-3402) add labels; new-meeting modal save (3455-3471).

**Interfaces:**
- Consumes: `withArc`, `toast` (Task 1).
- Produces: `patchMeeting(method, path, payload, label?)` — returns parsed JSON on success, `null` on failure (unchanged contract); drives the arc with the optional `label`.

- [ ] **Step 1: Rewrite `patchMeeting`**

Replace lines 3321-3329:

```javascript
  async function patchMeeting(method, path, payload) {
    const res = await fetch(`${API}/api/meetings/${m.id}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    if (!res.ok) { alert('Save failed (server offline or push error).'); return null; }
    return res.json();
  }
```

with:

```javascript
  async function patchMeeting(method, path, payload, label) {
    const doFetch = async () => {
      const res = await fetch(`${API}/api/meetings/${m.id}${path}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {}),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    };
    try { return await withArc(doFetch(), label); }
    catch (err) { return null; } // arc toasted; callers skip re-render on null
  }
```

- [ ] **Step 2: Add labels at the meeting call sites**

Add a 4th argument to each `patchMeeting(...)` call. Apply these exact edits:

- Agenda add (line 3338): `patchMeeting('PUT', '/agenda', { items })` → `patchMeeting('PUT', '/agenda', { items }, 'Agenda updated')`
- Agenda delete (line 3345): `patchMeeting('PUT', '/agenda', { items })` → `patchMeeting('PUT', '/agenda', { items }, 'Agenda updated')`
- Thread add (line 3351): `patchMeeting('POST', '/threads', { text: threadAdd.value.trim() })` → append `, 'Thread added'`
- Thread toggle (line 3358): `patchMeeting('PATCH', \`/threads/${tid}\`, { closed: toggle.checked })` → append `, 'Threads updated'`
- Thread promote (line 3362): `patchMeeting('POST', \`/threads/${tid}/promote\`, {})` → append `, 'Thread promoted'`
- Thread delete (line 3366): `patchMeeting('DELETE', \`/threads/${tid}\`, {})` → append `, 'Thread deleted'`
- Session save (line 3373): `patchMeeting('POST', '/sessions', { body })` → append `, 'Session saved'`
- Session edit save (line 3395): `patchMeeting('PATCH', \`/sessions/${sid}\`, { body })` → append `, 'Session saved'`
- Session delete (line 3400): `patchMeeting('DELETE', \`/sessions/${sid}\`, {})` → append `, 'Session deleted'`

(Each remains inside its existing `if (await patchMeeting(...)) renderMeetingsView();` — no other change.)

- [ ] **Step 3: Convert the new-meeting modal save**

Replace lines 3463-3470:

```javascript
    const res = await fetch(`${API}/api/meetings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!res.ok) { alert('Create failed (server offline or push error).'); return; }
    const data = await res.json();
    closeNewMeetingModal();
    meetingsState.selectedId = data.id;
    renderMeetingsView();
```

with:

```javascript
    let data;
    try {
      data = await withArc((async () => {
        const res = await fetch(`${API}/api/meetings`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })(), 'Meeting created');
    } catch (err) { return; } // arc toasted; keep modal open
    closeNewMeetingModal();
    meetingsState.selectedId = data.id;
    renderMeetingsView();
```

- [ ] **Step 4: Verify (success)**

Reload, Meetings tab, open a meeting doc:
- Add an agenda item (type + Enter) → `✓ Agenda updated`, item appears.
- Add/save a session log → `✓ Session saved`.
- Toggle/close a thread → `✓ Threads updated`.
- Create a new meeting via the modal → `✓ Meeting created`, modal closes, new meeting selected.

- [ ] **Step 5: Verify (failure)**

Stop the server. Add an agenda item.
Expected: red `Agenda updated failed: …` toast; the agenda does NOT change (re-render skipped because `patchMeeting` returned null).

- [ ] **Step 6: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(registry-ui): route meeting actions through the feedback arc

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: People Registry path — error/success toasts for consistency

The person-registry tab writes via the File-System-Access `writeJSON` (not `fetchJSON`), and already disables its save button + shows "Saving…". Bring its messaging in line: replace `alert(...)` with an error toast and add a success toast. Keep the existing button-state logic.

**Files:**
- Modify: `tools/registry_ui.html` — resolution-decisions save (1341-1349), merge confirm (1592-1608), person edit save (1658-1674).

**Interfaces:**
- Consumes: `toast` (Task 1).

- [ ] **Step 1: Resolution-decisions save**

Replace lines 1341-1349:

```javascript
  try {
    await writeJSON(state.dir, 'data/people_resolution_decisions.json', payload);
    status.classList.remove('hidden');
    setTimeout(() => status.classList.add('hidden'), 3000);
  } catch (e) {
    alert('Failed to save: ' + e.message);
  } finally {
    btn.disabled = decisionsArr.length === 0;
  }
```

with:

```javascript
  try {
    await writeJSON(state.dir, 'data/people_resolution_decisions.json', payload);
    status.classList.remove('hidden');
    setTimeout(() => status.classList.add('hidden'), 3000);
    toast('✓ Decisions saved', 'success');
  } catch (e) {
    toast('Save failed: ' + e.message, 'error');
  } finally {
    btn.disabled = decisionsArr.length === 0;
  }
```

- [ ] **Step 2: Merge confirm**

In the merge confirm handler (lines 1595-1607), replace the catch and add a success toast after the write. Change:

```javascript
    try {
      await writeJSON(state.dir, 'data/people_registry.json', state.registry);
    } catch (e) {
      alert('Failed to save: ' + e.message);
      btn.disabled = false;
      btn.textContent = 'Confirm Merge';
      return;
    }
```

to:

```javascript
    try {
      await writeJSON(state.dir, 'data/people_registry.json', state.registry);
      toast('✓ People merged', 'success');
    } catch (e) {
      toast('Merge failed: ' + e.message, 'error');
      btn.disabled = false;
      btn.textContent = 'Confirm Merge';
      return;
    }
```

- [ ] **Step 3: Person edit save**

In the edit save handler (lines 1661-1668), change:

```javascript
    try {
      await writeJSON(state.dir, 'data/people_registry.json', state.registry);
    } catch (e) {
      alert('Failed to save: ' + e.message);
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      return;
    }
```

to:

```javascript
    try {
      await writeJSON(state.dir, 'data/people_registry.json', state.registry);
      toast('✓ Person updated', 'success');
    } catch (e) {
      toast('Save failed: ' + e.message, 'error');
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      return;
    }
```

- [ ] **Step 4: Verify**

Note: this path needs the File-System-Access flow — click "Select Repo Folder" and grant access if the tab prompts. Then edit a person and save → `✓ Person updated` toast. (If your environment runs the registry over HTTP only and this tab is not exercised, confirm the code compiles/loads without console errors and move on — the success/error toasts are consistency polish, not the core complaint.)

- [ ] **Step 5: Commit**

```bash
git add tools/registry_ui.html
git commit -m "feat(registry-ui): toast feedback for person-registry writes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Reload the UI fresh; open the console and confirm **no errors** on load.
- [ ] Spot-check one action per surface (task, project, meeting agenda, person edit) shows the arc.
- [ ] Confirm the error path on at least one HTTP action (server stopped) shows a red toast and leaves the view unchanged.
- [ ] No leftover `alert(` calls remain for the actions touched above:

```bash
grep -n "alert('Save failed\|alert('Failed to save\|alert('Save failed (server\|alert('Create failed\|alert('Failed to add task" tools/registry_ui.html
```

Expected: no matches.

## Self-review notes (for the implementer)

- **Spec coverage:** toast (Task 1) · per-element busy (Task 1 + wired in Task 3) · centralized arc in `fetchJSON`+`patchMeeting` (Tasks 2, 4) · label map (Tasks 3, 4) · phantom-success fix / no-rerender-on-failure (Tasks 3, 4) · alert→toast (Tasks 3, 4, 5) · bottom-right position (Task 1 CSS). All covered.
- **Out of scope (do not add):** optimistic DOM updates, undo, re-render-strategy changes.
- **Line numbers** are from the current `tools/registry_ui.html`; if Task 1's insertions shift later lines, match on the quoted code rather than the number.
