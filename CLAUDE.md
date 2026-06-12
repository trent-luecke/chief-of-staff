# Chief of Staff

AI morning brief + Telegram assistant for Trent Luecke (trent@teambuildr.com), VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches).

## Do Not Read

These directories contain runtime artifacts, scraped data, or archived planning docs. Do not open or scan them for orientation:

- `docs/archive/` — completed implementation plans and design specs (historical only)
- `logs/` — daily run logs (gitignored, not tracked)
- `market-intel/data/` — scraped competitor/trend articles (gitignored, not tracked)
- `data/memory/` — machine-written synthesized memory files (runtime state)
- `data/people/` — machine-written contact files (runtime state, human-curated header sections)

## What This Is

Two main capabilities:

1. **Daily Brief** — runs at 7am CDT via GitHub Actions. Pulls calendar, Gmail, Slack DMs, Notion pipeline cache, and local quick-capture notes → generates a brief with Claude → emails it to Trent.
2. **Telegram Bot** — Cloudflare Worker receives messages → dispatches to GitHub Actions → Claude tool-use loop (12 tools) → replies via Telegram. JARVIS personality.

## Completed Phases

| Phase | What it is |
|-------|-----------|
| P0 — Cloud Hosting | GitHub Actions scheduler; OAuth2 refresh token via Secret |
| P1 — People Intelligence | `data/people/` contact store; machine-written Activity sections |
| P2 — Pipeline Data | Notion pipeline cache in `data/pipeline_cache.json` via MCP sync |
| P3 — Cross-Day Memory | `observations.jsonl` → synthesizer → 90-day TTL `.md` files → retriever |
| P4 — Two-Way Interface | Telegram bot via Cloudflare Worker + GitHub Actions |
| P5 — Weekly Synthesis | Sunday Claude narrative; 7-day patterns, carry-forwards, cost summary |
| P9 — Tool Use | Native tool-use loop; 12 read/write tools; replaced intent classifier |
| P10 — Outbound Email Tracking | Sent-mail scan; `direction` field on pipeline activity records |
| P11 — Meeting Transcripts | Avoma API; Claude analysis per call; extracts features/gaps/objections/signals |
| P12 — Observability | All Claude call sites log to `data/logs/run_log.jsonl` with token counts + cost |
| P13 — Graduated Memory Decay | Abandoned memories (60d+) get 14-day TTL; pinned memories immune |
| P14 — Vector Memory Layer | Pinecone serverless index; Voyage AI embeddings; semantic retrieval for brief + Telegram |

## Key Entry Points

- `main.py` — daily brief orchestrator
- `ask.py` — Telegram query handler (called by `ask.yml` Actions workflow)
- `nudger.py` — meeting nudge sender
- `watcher.py` — pipeline/inbox watcher
- `weekly_synthesis.py` — Sunday synthesis runner
- `check_replies.py` — reply feedback collector
- `reply_collector.py` — post-nudge reply handler

## Key Files

- `config.json` — all runtime config (no credentials)
- `data/meeting_index.json` — user-managed meeting configs (3 entries); hand-edit to add meetings
- `data/projects.md` — active projects list (human-curated)
- `data/recurring.json` — recurring context config
- `data/captures.md` — quick-capture inbox
- `data/people/*.md` — contact files (human header + machine Activity section)
- `data/memory/decisions.md` — durable decisions store (Wanderer-facing)
- `processors/query_tools.py` — all 12 tool schemas and executors for the Telegram tool loop
- `cloudflare/telegram-bridge.js` — Cloudflare Worker webhook handler
- `market-intel/market_intel.py` — competitor/trend scraper (runs separately)
- `scripts/wanderer.py` — autonomous Pinecone explorer (runs separately)

## Auth

Google APIs use OAuth2 refresh token — no service account. Credentials in `credentials/google_oauth.json` (gitignored). GitHub Secret: `GOOGLE_OAUTH_JSON`. To re-authorize: `python scripts/authorize.py`.

## Data Persistence

`data/` is committed back to repo at end of each GitHub Actions run. `.gitignore` ignores `data/*` by default and explicitly un-ignores the tracked files below (see the `!data/...` allow-list).

Tracked in git:
- `data/people/` — contact files
- `data/projects.md`, `data/recurring.json`, `data/meeting_index.json` — user config
- `data/memory/decisions.md` — durable decisions
- `data/captures.md` — quick-capture inbox
- Registry entity stores (read/written by the Registry UI, see below): `data/tasks.jsonl`, `data/projects_registry.json`, `data/notes.jsonl`, `data/notes_tags.json`, `data/people_registry.json` (+ `people_resolution.json`, `people_unresolved.json`, `onboarding_cache.json`). `tasks.jsonl` uses a `merge=union` driver (`.gitattributes`) so concurrent appends never conflict.

Gitignored (machine-written state):
- `data/memory/*.md` (except `decisions.md`)
- `data/state/`, `data/drafts/`, `data/logs/`

## Registry UI (main-anchored data layer)

`tools/server.py` (Flask) + `tools/registry_ui.html` serve the People / Work UI (tasks, projects, people, notes, tags). It treats **`origin/main` as the single source of truth**: reads come from an in-memory snapshot of `git show origin/main:<file>`; every create/edit/delete is written to `origin/main` via a throwaway git worktree (`lib/git_sync.py` + `lib/main_storage.py`) — it never mutates the working tree. Offline → HTTP 503 + UI banner; a failed push → HTTP 502 (no phantom success). Launch via the `registry-ui` skill or `python3 tools/server.py` (port 8787). Because the UI commits straight to `origin/main`, the registry data files on `main` are authoritative — don't hand-commit divergent working-tree copies.

### Pushing `main` is routine, not a deploy

`origin/main` is a **live shared datastore**, not a release target. No GitHub Actions workflow triggers on `push` — every workflow is `schedule:` or `workflow_dispatch:`/`repository_dispatch:`, and each reads `origin/main` at run time. So pushing `main` deploys nothing, emails nothing, and sends no Telegram message; it is the normal sync path.

The risky state is the opposite: **unpushed local commits**. While code or data sits unpushed, (a) scheduled jobs (7am brief, nudges, syncs) run against stale code, and (b) the Registry UI keeps committing data to `origin/main`, so the branches drift apart in both directions and you accumulate `Merge branch 'main'` noise.

Therefore:
- **Do not gate `git push origin main` behind an "outward-facing, confirm first" check.** Push feature work promptly; never end a session with local `main` ahead of `origin/main`.
- Accumulate work on **feature branches**, not on local `main`. Integrate via PR merged on GitHub (server-side merge against the latest `origin/main`, so local `main` is never "ahead"), or merge locally and `git push` in the same motion.
- The bot moves `origin/main` under you — `git config pull.rebase true` and rebase feature branches onto fresh `origin/main` before merging to avoid merge commits.

## Vector Memory (Pinecone + Voyage AI)

Pinecone serverless index `chief-of-staff`, two namespaces: `observations` (raw signals) and `memories` (synthesized `.md` files). Embeddings via Voyage AI `voyage-3-lite` (512 dims). Ingest is non-fatal. Retrieval mode controlled by `config.json` → `vector.retrieval_mode`: `"auto"` (Pinecone + file fallback), `"semantic"`, or `"file"`.

GitHub Secrets required: `PINECONE_API_KEY`, `VOYAGE_API_KEY`

## Notion Pipeline

Synced manually via Claude Code MCP — ask Claude to re-sync pipeline cache from Notion. Result goes to `data/pipeline_cache.json`. Brief warns if cache is >7 days old.

## Running Locally

```bash
python main.py --no-email   # generate without sending
python main.py              # generate and send
```

Requires `.env` with: `GOOGLE_OAUTH_JSON`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`
