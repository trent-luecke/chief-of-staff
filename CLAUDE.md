# Chief of Staff

AI morning brief system for Trent Luecke (trent@teambuildr.com), VP of Sales at TeamBuildr OS (B2B SaaS for strength and conditioning coaches).

## What This Is

Runs daily at 7am CDT via GitHub Actions. Pulls calendar, Gmail, Slack DMs, Notion pipeline cache, and local quick-capture notes → generates a brief with Claude → emails it to Trent.

## Current State (as of 2026-04-19)

- **P0 (Cloud Hosting)** — complete. Runs in GitHub Actions, no local machine required.
- **P1 (People Intelligence)** — complete. `data/people/` contact store with machine-written Activity sections.
- **P2 (Pipeline Data)** — complete. Notion pipeline in `data/pipeline_cache.json` via MCP sync.
- **P3 (Cross-Day Memory)** — complete. `processors/memory_observer.py`, `memory_synthesizer.py`, `memory_retriever.py`. Observations appended to `data/memory/observations.jsonl`, synthesized into `data/memory/*.md` with YAML frontmatter and 90-day TTL, injected into brief prompt (550-token budget). PR #3.
- **P14 (Vector Memory Layer)** — complete. Pinecone serverless index (`chief-of-staff`) with two namespaces: `observations` and `memories`. `processors/vector_ingest.py` embeds new observations and updated memory files after each daily run via Voyage AI (`voyage-3-lite`, 512 dims). Non-fatal — Pinecone errors don't block the brief. State tracked in `data/vector_ingest_state.json`. GitHub Secrets required: `PINECONE_API_KEY`, `VOYAGE_API_KEY`.
- **P4 (Two-Way Interface)** — next up. See `BACKLOG.md` for spec.

## Auth

Google APIs use OAuth2 refresh token — **no service account, no domain-wide delegation** (Trent doesn't have Workspace Admin access). Credentials stored in `credentials/google_oauth.json` (gitignored). GitHub Secret: `GOOGLE_OAUTH_JSON`. To re-authorize: `python scripts/authorize.py`.

## Key Files

- `main.py` — orchestrator
- `lib/google_auth.py` — `build_gmail_service(user_email)`, `build_calendar_service(user_email)`
- `collectors/` — calendar, gmail, slack, pipeline, gym_scout, local_data
- `processors/brief.py` — Claude call, returns `BriefContent`
- `outputs/sender.py` — `send_brief_email(gmail_service, to, subject, html)`
- `config.json` — all runtime config (no credentials)
- `data/` — persisted state, committed back to repo by Actions after each run

## Data Persistence

`data/` is committed back to the repo at the end of each GitHub Actions run. `data/state/` is tracked (un-ignored). `data/drafts/` is gitignored.

## Vector Memory (Pinecone + Voyage AI)

Observations and synthesized memory files are embedded into a Pinecone serverless index (`chief-of-staff`) after each run. Two namespaces: `observations` (raw signals, one vector per JSONL line) and `memories` (synthesized `.md` files, one vector per file). Embeddings generated via Voyage AI (`voyage-3-lite`, 512 dims).

Ingest is non-fatal — if Pinecone or Voyage is unreachable, the system continues with file-based memory. Ingest state tracked in `data/vector_ingest_state.json` (committed to repo on each Actions run).

Phase 1 (current): ingest only. Phase 2: semantic retrieval replaces recency-based memory retriever. Phase 3: semantic Telegram queries.

GitHub Secrets required: `PINECONE_API_KEY`, `VOYAGE_API_KEY`

## Notion Pipeline

Synced manually via Claude Code MCP — ask Claude Code to re-sync pipeline cache from Notion. Result goes to `data/pipeline_cache.json`. Brief warns if cache is >7 days old.

## Running Locally

```bash
python main.py --no-email   # generate without sending
python main.py              # generate and send
```

Requires `GOOGLE_OAUTH_JSON`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN` in `.env`.
