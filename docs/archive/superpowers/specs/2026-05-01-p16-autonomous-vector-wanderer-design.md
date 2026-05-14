# P16 — Autonomous Vector Wanderer

**Date:** 2026-05-01
**Status:** Design approved, pending implementation
**Prerequisite:** P15 — KPI Logging & Raw Data Vector Layer

## Purpose

A nightly autonomous agent that gets unsupervised time with the Pinecone vector DB and surfaces interesting patterns via Telegram. Claude drives its own exploration using tools — it decides what to query, in what order, and when it's satisfied. Findings that have cross-day significance are written back as memory files, which flow into the next morning's brief through the existing retriever.

The wanderer is completely isolated from the morning brief pipeline. Nothing in `main.py` or the brief workflow is modified.

---

## Architecture

```
.github/workflows/wanderer.yml   (new — runs nightly at 11pm CDT)
  └── scripts/wanderer.py        (new — standalone, not imported by anything)
        ├── data/memory/         (read: load last 5 wanderer memories as context seed)
        ├── Pinecone             (read: all 3 namespaces via tool-use loop)
        ├── Telegram Bot API     (write: send finding message)
        └── data/memory/         (write: optional wanderer memory file)
```

The wanderer's only connection to the brief is the shared `data/memory/` directory. Findings Claude writes there surface in tomorrow's brief when semantically relevant — no explicit coupling, no brief code changes.

### Files

**New:**
- `scripts/wanderer.py`
- `.github/workflows/wanderer.yml`

**Modified:** None. `memory_retriever.py`, `main.py`, and all brief processors are untouched.

---

## The Tool-Use Loop

### Tools

Claude receives two tools:

**`query_semantic(query: str, namespace: str, top_k: int = 10)`**
Embeds `query` via Voyage AI (`voyage-3-lite`, `input_type="query"`), queries the specified Pinecone namespace, returns top-k matches. Each match includes: `id`, `score`, `metadata` (full), `content_preview`.

Valid namespaces: `observations`, `memories`, `raw_data`.

**`filter_records(namespace: str, filters: dict, top_k: int = 20)`**
Direct Pinecone metadata filter query — no embedding. Returns same shape as above. Useful for structured lookups: all High-priority open bugs, all cancellations by reason, all stale leads.

`filters` uses Pinecone's native filter syntax — the runner passes the dict directly to Pinecone's `filter=` parameter. Claude is given this syntax in the tool description. Examples:
- `{"priority_level": {"$eq": "High"}}` — exact match
- `{"status": {"$in": ["In progress", "Not started"]}}` — set membership
- `{"stale": {"$eq": true}}` — boolean
- `{"days_open": {"$gt": 7}}` — numeric comparison

Filterable metadata fields per namespace:
- `raw_data` leads: `status`, `priority`, `stale` (bool), `source`
- `raw_data` bugs: `status`, `priority_level`, `technical_areas` (list), `days_open`
- `raw_data` cancellations: `reason`, `base_plan`, `customer_returned`
- `raw_data` sales: `sale_type`, `salesperson`
- `observations`: `type`, `date`, `entity`

### Loop execution

```
System prompt → Claude call
  Claude uses tool → runner executes → result appended to conversation → Claude call
  Claude uses tool → runner executes → result appended → Claude call
  ...
  Claude stops calling tools → parse final response
  OR
  20 tool calls hit → inject "You've reached your query limit. Write your final response now." → one final Claude call
```

Claude is instructed to aim to conclude within ~15 queries. The hard stop at 20 prevents runaway cost on a bad night.

**Model:** `claude-sonnet-4-6`. Balances analytical capability with cost for a nightly agentic loop. Haiku would be too shallow for pattern synthesis across namespaces; Opus is unnecessary for this task.

### System prompt seeds

1. **Namespace schema** — what each namespace contains and what metadata fields are filterable, so Claude knows what it can query and filter on without guessing.
2. **Today's date** — so Claude can reason about staleness, MTD trends, days-open counts.
3. **Last 5 wanderer memories** — topic + full content of the most recent `source: wanderer` memory files from `data/memory/`, sorted by `last_updated` descending. Injected with the instruction: *"These are your recent findings. Revisit them only if there's meaningfully new data since you last looked. Otherwise, explore elsewhere."*
4. **Tool budget** — *"Aim to conclude within ~15 queries. You have a hard limit of 20."*

---

## Final Response Format

Claude is instructed to end its exploration with a JSON block:

```json
{
  "telegram": "🔍 Wanderer — 2026-05-01\n\n[finding, ≤1500 chars]",
  "memory": {
    "topic": "cancellation-reason-clustering",
    "content": "3 of the last 4 cancellations cite Business Changes — all Base Plan clients at $150–180/mo...",
    "expires": "2026-05-15"
  }
}
```

`memory` is optional. Claude includes it only when the finding has cross-day significance worth carrying into future briefs. If the finding is ephemeral (e.g., today's KPI snapshot is normal), Claude omits `memory`.

**Fallback**: If the final response can't be parsed as JSON, the runner sends the raw text as the Telegram message and skips the memory write.

---

## Memory Write-Back

When Claude includes a `memory` field, the runner writes to `data/memory/`:

**Filename:** `wanderer_{topic_slug}_{date}.md`
Example: `wanderer_cancellation-reason-clustering_2026-05-01.md`

Date in the filename means a new finding on the same topic creates a new file rather than overwriting the previous one — history is preserved, and the brief retriever handles deduplication by relevance ranking.

**File format:**
```markdown
---
topic: Cancellation Reason Clustering
source: wanderer
last_updated: 2026-05-01
expires: 2026-05-15
pinned: false
suppress: false
---

[content from Claude's memory.content field]
```

**TTL:** 14 days default. Wanderer findings are time-sensitive signals — long enough to persist across two weeks of briefs if still relevant, short enough to auto-expire without manual cleanup. Claude may specify a different `expires` date in its response if warranted.

**Anti-rut mechanism:** The `source: wanderer` tag lets the runner cheaply load previous wanderer memories at startup (scan `data/memory/` by frontmatter, no Pinecone query). The "explore elsewhere" instruction in the system prompt discourages Claude from writing the same finding twice. If Claude writes the same topic on consecutive nights, both files exist — the brief retriever sees both but ranks by relevance, and the instruction nudges Claude away from it on night three.

---

## Telegram Delivery

Single message per run, ≤1500 characters. Claude is responsible for keeping its output within the limit and being editorial — surface the single most interesting finding, not everything it looked at.

Example format:
```
🔍 Wanderer — 2026-05-01

Noticed: 3 of the last 4 cancellations cite "Business Changes" — all Base Plan clients at $150–180/mo. Months paid ranges 2–18 so tenure isn't the pattern. Worth cross-referencing demo notes for those accounts to see if a product gap is common.

Pipeline: Tyler Landeck (ALA) now 49 days since contact, still In-Trial. Only High-priority stale lead at the moment.
```

If the Telegram send fails, the error is logged and skipped — the memory write still happens if there was one.

---

## GitHub Actions Workflow

**File:** `.github/workflows/wanderer.yml`
**Schedule:** 11pm CDT nightly (`0 4 * * *` UTC, Apr–Oct)

```yaml
name: Nightly Wanderer

on:
  schedule:
    - cron: "0 4 * * *"
  workflow_dispatch:

jobs:
  run-wanderer:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    env:
      TZ: America/Chicago

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run wanderer
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
          VOYAGE_API_KEY: ${{ secrets.VOYAGE_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python scripts/wanderer.py

      - name: Persist data
        run: |
          git config user.name "chief-of-staff[bot]"
          git config user.email "noreply@github.com"
          git add data/
          git diff --cached --quiet && exit 0
          git commit -m "chore: wanderer data update $(date +%Y-%m-%d)"
          git pull --rebase
          git push
```

**Secrets required** (all already in repo):
`ANTHROPIC_API_KEY`, `PINECONE_API_KEY`, `VOYAGE_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

No new secrets required.

---

## Error Handling

| Failure | Behavior |
|---|---|
| Pinecone/Voyage unreachable | Tool call returns error string to Claude; Claude can try another query or wrap up |
| Uncaught exception in wanderer | Job exits 0, logged — brief pipeline unaffected |
| JSON parse failure on final response | Send raw text as Telegram message; skip memory write |
| Telegram send failure | Log and skip; memory write still happens |
| Concurrent push conflict (brief + wanderer) | `git pull --rebase` handles it — same pattern as brief.yml |
| Hard stop at 20 tool calls | Runner injects wrap-up message; Claude writes final response with what it has |

---

## Out of Scope

- Two-way Telegram exchange / drill-in capability (P17)
- Brief pipeline awareness of the wanderer (implicit via shared `data/memory/` is sufficient)
- Writing new `observations.jsonl` entries (wanderer writes only to `data/memory/`)
- Notion write access or any data mutation outside `data/memory/`
