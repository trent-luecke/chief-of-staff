# Handoff: Split OS-Metric-Sync into its own git repo

**Date:** 2026-06-18
**For:** a fresh session to untangle the OS-Metric-Sync / monorepo git mess.
**Status:** investigation + plan needed; nothing here is started.
**This doc lives in `chief-of-staff/` on purpose** — chief-of-staff is the one repo NOT involved in the split, so editing it is safe while you rework the others.

---

## TL;DR

`OS-Metric-Sync` is **not a standalone git repo**. It's a subdirectory of a
**monorepo** at `/Users/trentluecke/dev/Claude-Projects` (`.git` at that root).
That monorepo's `origin` was pointed at `git@github.com:trent-luecke/os-metric-sync.git`
during a previous session, so **`os-metric-sync.git` on GitHub currently holds the
ENTIRE monorepo** (OS-Metric-Sync + ~10 other unrelated projects), not just the
dashboard. The Railway deploy works anyway because it deploys via `railway up`
(which uploads the `OS-Metric-Sync/` subdirectory directly, ignoring git).

**Goal:** make `OS-Metric-Sync` a clean standalone git repo whose `origin` is a
GitHub repo containing ONLY OS-Metric-Sync, with Railway deploying from it
properly — without losing the live engine, its data, or the other projects'
code. **Do the investigation first; confirm choices with Trent before any
destructive `git remote`/push/force operation.**

---

## Verified current state (run these to re-confirm — don't trust this doc blindly)

```bash
# Monorepo root + its (wrong) origin
git -C /Users/trentluecke/dev/Claude-Projects rev-parse --show-toplevel
git -C /Users/trentluecke/dev/Claude-Projects remote -v
git -C /Users/trentluecke/dev/Claude-Projects log --oneline -8
git -C /Users/trentluecke/dev/Claude-Projects ls-files | sed 's#/.*##' | sort -u   # all tracked top-level entries

# OS-Metric-Sync has NO own .git (it's a subdir of the monorepo)
ls -ld /Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync/.git   # -> No such file
git -C /Users/trentluecke/dev/Claude-Projects ls-files OS-Metric-Sync | wc -l   # ~36 tracked source files

# chief-of-staff is a SEPARATE nested repo (NOT part of the monorepo) — leave it alone
git -C /Users/trentluecke/dev/Claude-Projects/chief-of-staff remote -v
git -C /Users/trentluecke/dev/Claude-Projects ls-files chief-of-staff | wc -l   # -> 0 (monorepo doesn't track it)
```

As of this handoff:
- **Monorepo** `/Users/trentluecke/dev/Claude-Projects`: branch `main`, `origin =
  os-metric-sync.git`. Tracks: `OS-Metric-Sync/` (~36 files) **plus**
  `StoryBuildr/`, `CRM/`, `Cold-Email-Automation/`, `daily-sales-brief/`,
  `sales-prep-tool/`, `Sales-Content-Repurposer/`, `Avoma-Ingest-Chris/`,
  `files/`, `.github/`, etc. Its `main` HEAD is the OS-Metric-Sync demo-engine
  work (latest commit `198362b` at handoff time).
- **`os-metric-sync.git` (GitHub)** therefore contains the whole monorepo.
- **chief-of-staff** `/Users/trentluecke/dev/Claude-Projects/chief-of-staff`:
  its own `.git`, `origin = chief-of-staff.git`, **0 files tracked by the
  monorepo** → cleanly independent. **Do not touch it during the split.**
- **Important history note:** the monorepo's `origin` was
  **`git@github.com:trent-luecke/chief-of-staff.git`** at the very start of the
  prior session (before it was repointed to `os-metric-sync.git`). So the
  monorepo has been sharing a remote with a sub-project for a while — neither
  remote is "correct" for the monorepo. Decide with Trent what the monorepo's
  remote *should* be (its own repo, or none).

---

## How it deploys today (don't break this)

- **Railway project:** `os-dashboard` (CLI: `railway status`); service
  `os-dashboard` (id `88f140af-e192-4bef-8017-84ffe528c56b`); environment
  `production`. Public URL: `https://os-dashboard-production-aa99.up.railway.app`.
- **Deploy mechanism:** `railway up --ci` run **from inside
  `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync`** — it uploads that
  directory (with its `Dockerfile`) and builds. This is git-independent. GitHub
  push-to-deploy is NOT the active path (and is misconfigured given the repo
  holds the whole monorepo).
- **Build config:** `OS-Metric-Sync/railway.toml` → `[build] builder =
  "DOCKERFILE"`, `dockerfilePath = "Dockerfile"`; `[deploy] startCommand =
  "uvicorn dashboard.main:app --host 0.0.0.0 --port 8080"`, `healthcheckPath =
  "/health"`. Service var `PORT=8080`. (Railway runs startCommand WITHOUT a
  shell, so the port is a literal — do not reintroduce `$PORT`/`${PORT:-8080}`.)
- **Engine state lives on a Railway volume** (`DB_PATH` env points into
  `RAILWAY_VOLUME_MOUNT_PATH`; `dashboard.db` SQLite). **The volume persists
  across deploys and is independent of any git change** — splitting the repo
  will NOT lose the live demo/metrics data. Verify before/after via:
  `curl -s -u ":$DASHBOARD_PASSWORD" $URL/api/metrics/snapshot`.
- Secrets in Railway: `DASHBOARD_PASSWORD`, `GOOGLE_SERVICE_ACCOUNT_JSON`,
  `PORT`. (`railway variables --json` to list.)

---

## Why this needs fixing (what it cost us)

During the prior session, because `OS-Metric-Sync` git commands actually operate
on the monorepo, a subagent's broad `git add -A` swept **368 unrelated files**
(StoryBuildr, etc.) into a single "fix" commit. It was caught and reset, and
from then on every commit used **specific-path `git add`** only. This is a
standing hazard: any `git add -A`/`git add .`/`git commit -a` from within
`OS-Metric-Sync` pollutes the monorepo. Until the split, **only ever
`git add <exact paths>`.**

---

## Desired end state

1. `OS-Metric-Sync/` is its **own git repo** (`OS-Metric-Sync/.git` exists),
   `origin` → a GitHub repo containing **only** OS-Metric-Sync.
2. Railway deploys from that clean repo (either keep `railway up`, or wire proper
   GitHub push-to-deploy now that the repo == the app).
3. The **monorepo's `origin` is corrected** (its own repo, or removed) so it no
   longer points at `os-metric-sync.git` (or `chief-of-staff.git`).
4. Live engine + volume data intact; the other projects' code intact; chief-of-staff
   untouched.

---

## Key decisions to make WITH TRENT before acting

1. **History:** does OS-Metric-Sync's new standalone repo need its **commit
   history preserved**, or is a clean `git init` + single "import" commit fine?
   - Preserve → use `git filter-repo --subdirectory-filter OS-Metric-Sync`
     (or `git subtree split`) on a CLONE of the monorepo to extract just that
     subtree with history, then push to the clean repo.
   - Clean slate → `git init` in `OS-Metric-Sync/`, commit current files, push.
     Simpler; loses the granular per-feature history (the design/plan docs in
     `OS-Metric-Sync/docs/superpowers/` capture the intent regardless).
2. **What becomes of `os-metric-sync.git`?** It currently holds the whole
   monorepo. Options: (a) hard-reset/force-push it to contain only the extracted
   OS-Metric-Sync (destructive to its current contents — confirm nothing else
   depends on it), or (b) create a NEW GitHub repo for the clean OS-Metric-Sync
   and repoint Railway + the new local repo to it, leaving `os-metric-sync.git`
   to be repurposed/deleted.
3. **What is the monorepo for, and what should ITS remote be?** Does Trent want
   `Claude-Projects` to remain a monorepo of all these side projects with its own
   backup remote, or should each project become standalone over time? At minimum,
   stop it from pointing at `os-metric-sync.git`.
4. **Railway re-link:** if a new GitHub repo is used, decide whether to keep
   `railway up` (works today, manual) or connect Railway's GitHub integration to
   the new repo for push-to-deploy. If GitHub deploy: the Dockerfile is at the
   repo root once OS-Metric-Sync is standalone, so `railway.toml`'s
   `dockerfilePath = "Dockerfile"` is already correct.

---

## Suggested approach (investigate → confirm → execute)

1. **Re-confirm state** with the commands above. Don't trust this doc's snapshot.
2. **Snapshot safety:** note the live `demos_mtd`/snapshot now
   (`curl .../api/metrics/snapshot`) so you can confirm the volume data is
   unchanged after any repo work.
3. **Get Trent's answers** to the 4 decisions above (esp. history + what happens
   to `os-metric-sync.git` + the monorepo's intended remote).
4. **Extract** (on a CLONE, never the working tree): if preserving history,
   `git clone` the monorepo to a temp dir, `git filter-repo
   --subdirectory-filter OS-Metric-Sync`, verify the result is OS-Metric-Sync-only.
5. **Create/clean the target GitHub repo**, push the extracted repo.
6. **Replace the working copy:** make `/Users/trentluecke/dev/Claude-Projects/OS-Metric-Sync`
   a real clone of the new repo (or `git init` there if clean-slate). Verify
   `git -C OS-Metric-Sync rev-parse --show-toplevel` now returns the
   OS-Metric-Sync dir (not the monorepo).
7. **Fix the monorepo remote** (decision #3).
8. **Re-deploy + verify:** `railway up` from the new standalone repo; confirm
   `/health` 200 and the snapshot data matches step 2 (volume intact).
9. **Verify chief-of-staff is unaffected** (its `origin`, its scheduled
   workflows that call the engine: `METRICS_BASE_URL` still
   `https://os-dashboard-production-aa99.up.railway.app`).

---

## Cross-repo dependencies to keep working

- **chief-of-staff → engine:** the daily brief + nightly `avoma_sync` call the
  engine at `METRICS_BASE_URL` (GitHub secret, = the Railway URL) with
  `METRICS_PASSWORD` (= engine `DASHBOARD_PASSWORD`). As long as the **Railway
  URL doesn't change**, the split is invisible to chief-of-staff. If you migrate
  Railway in a way that changes the URL, update the `METRICS_BASE_URL` GitHub
  secret in chief-of-staff.
- The engine endpoints chief-of-staff depends on: `POST /api/sync-all`,
  `GET /api/metrics/snapshot`, `POST /api/demos/ingest`.

## Context: what was just built (so you know the engine is "done", just mis-repo'd)

Two recently-shipped features live in `OS-Metric-Sync` + `chief-of-staff`
(specs/plans under each repo's `docs/superpowers/`):
- **Metric-sync overseer** (`2026-06-16-...`): engine = canonical metric store;
  chief-of-staff consumes `/api/metrics/snapshot`.
- **Avoma demo detection** (`2026-06-17-...`): chief-of-staff detects OS demos
  from Avoma transcripts → `POST /api/demos/ingest`; engine has an editable
  Demos table. Backfill already populated current-month demos.

Don't redo these — they're merged and live. This handoff is **only** about the
git/repo structure, not the application.
