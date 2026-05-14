# P3 — Cross-Day Memory Design

**Date:** 2026-04-19  
**Status:** Approved, pending implementation

---

## Problem

The system resets each morning. It knows today's calendar, inbox, and issues — but accumulates nothing. The same problem surfacing every Monday for three weeks is treated as new each time. Decisions made via email or Slack disappear. Priority drift goes unnoticed.

**Two jobs this solves:**
1. **Pattern recognition** — recurring issues, stuck deals, blockers that keep resurfacing
2. **Continuity of context** — decisions in-flight, conversations that were open, priority drift across days

---

## Architecture

Three new modules, minimal changes to existing files.

```
Daily Run
  ├── [existing] collect data → generate brief → send
  ├── [new] memory_observer: append structured observations to observations.jsonl
  └── [new, async after send] memory_synthesizer: read observations → Claude → update memory files

Brief Generation (pre-Claude call)
  └── [new] memory_retriever: read non-expired memory files → inject ## Cross-Day Memory into prompt
```

**New files:**
- `processors/memory_observer.py` — structured signal capture, no Claude call
- `processors/memory_synthesizer.py` — synthesis with decay, one Claude call per run async
- `processors/memory_retriever.py` — reads memory files, returns context string for brief prompt
- `data/memory/observations.jsonl` — append-only observation log
- `data/memory/{topic}.md` — synthesized memory files (human + machine sections)
- `data/memory/decisions.md` — manual decision log (human-written, observer reads)
- `data/memory/archive/` — expired memory files (never deleted, just moved)

**Existing files touched:**
- `main.py` — call observer after send, call retriever before prompt build, trigger synthesizer async
- `processors/brief.py` — add `## Cross-Day Memory` section to prompt; render cold-start banner from retriever status (not a Claude-generated field)
- `config.json` — add `memory` config block

---

## Layer 1: Observation Capture

`memory_observer.py` runs after the brief sends. It extracts structured signals from data already collected during the run — no additional API calls.

**Schema (`observations.jsonl` — one JSON line per observation):**
```json
{"date": "2026-04-19", "type": "email_loop", "entity": "thread:RE: Contract Renewal", "content": "Thread open 5 days, no reply", "source": "state"}
{"date": "2026-04-19", "type": "pipeline_stale", "entity": "apex", "content": "Apex stale 18 days, last status: In-Trial", "source": "pipeline"}
{"date": "2026-04-19", "type": "top_priority", "entity": "apex", "content": "Appeared in top 3: 'Follow up on Apex contract renewal'", "source": "brief"}
{"date": "2026-04-19", "type": "issue_pattern", "entity": "payment-processing", "content": "Payment issue raised in #support (age: 3 days)", "source": "issues"}
{"date": "2026-04-19", "type": "decision", "entity": "apex", "content": "Pausing outreach until May fiscal year start", "source": "manual"}
{"date": "2026-04-19", "type": "decision_candidate", "entity": "riverside-gym", "content": "Not pursuing Riverside lead — inferred from Apr 18 Slack DM to Ken", "source": "slack", "confirmed": false}
```

**Six observation types:**

| Type | Written by | Source | Captured when |
|------|-----------|---------|---------------|
| `email_loop` | observer | state diff | thread still-open ≥ 2 days |
| `pipeline_stale` | observer | pipeline leads | `stale=True` or `days_since_contact > 7` |
| `top_priority` | observer | brief output | item appears in `top_3_priorities` |
| `issue_pattern` | observer | issues.json | any open issue, with age |
| `decision` | observer | `data/memory/decisions.md` | new line (by date) in decisions.md |
| `decision_candidate` | synthesizer | email/Slack snippets stored in observations | inferred by Claude during async synthesis |

**Rich content for synthesis:** the observer also stores a `context` field on `email_loop` and `issue_pattern` observations (thread snippet, Slack message text) so the synthesizer can infer decision candidates without re-fetching APIs async:
```json
{"date": "2026-04-19", "type": "email_loop", "entity": "thread:RE: Contract Renewal", "content": "Thread open 5 days, no reply", "source": "state", "context": "Latest message: 'Let's reconnect after our fiscal year kicks off in May'"}
```

**`data/memory/decisions.md` format:**
```
2026-04-19: Pausing Apex outreach until May fiscal year start
2026-04-15: Not pursuing Riverside gym lead — wrong market segment
```
Plain text, one line per decision. Observer reads on each run, emits new lines (by date) as `decision` observations.

**Key constraint:** observations.jsonl is append-only and never modified by synthesis. It is the source of truth.

---

## Layer 2: Synthesis

`memory_synthesizer.py` runs **async after the brief sends** — no latency impact on morning run.

**Process:**
1. Read all observations from last 30 days (configurable: `memory.observation_lookback_days`)
2. Group by `entity` to identify topics
3. Call Claude once with grouped observations: identify patterns, decisions, continuity items, and `decision_candidates` inferred from email/Slack snippets passed in context
4. Create or update `data/memory/{topic}.md` — human section untouched, `## Synthesized Memory` rewritten
5. Apply decay: extend `expires` on active topics, archive expired files

**Memory file format:**
```markdown
---
topic: apex-account
created: 2026-04-01
last_updated: 2026-04-19
expires: 2026-07-18
activity_last_seen: 2026-04-19
pinned: false
suppress: false
---

<!-- Human-written — never modified by synthesis -->
Key contact is Sarah Chen (VP Finance). Goes dark during fiscal Q1.

## Synthesized Memory

**Pattern:** Apex has appeared in top 3 priorities 4 times in 2 weeks without resolution. Contract renewal thread open 8 days.

**Decision:** Pausing outreach until May fiscal year start — noted 2026-04-15.

**Watch:** Deal stagnant since demo on 2026-04-08. Risk of going cold.

_Last synthesized: 2026-04-19_
```

**Decay model:**
- Default TTL: 90 days from `last_updated` (configurable: `memory.default_ttl_days`)
- Any new observation matching the topic resets `activity_last_seen` and extends `expires` by 30 days (configurable: `memory.activity_extension_days`)
- `pinned: true` disables expiry entirely
- Expired files are moved to `data/memory/archive/`, never deleted

**Override flags (frontmatter):**

| Flag | Effect |
|------|--------|
| `pinned: true` | Disables decay — lives until flag removed |
| `expires: 2026-05-01` | Hard expiry, ignores activity extension |
| `suppress: true` | Memory preserved but never injected into brief |

**Known limitation:** override requires manually editing a memory file. Rejecting a memory from the brief itself requires P4's two-way interface. For P3, `suppress: true` is the escape hatch.

---

## Layer 3: Decision Candidates (P3/P4 Bridge)

During synthesis, Claude scans email thread snippets and Slack DM content passed in context to infer decisions. These are written as `decision_candidate` observations (`confirmed: false`) and surfaced in the brief under `## Decision Candidates`.

**Brief section:**
```
Decision Candidates (unconfirmed — add to data/memory/decisions.md to persist)
• "Not pursuing Riverside lead" — inferred from Apr 18 Slack DM to Ken
• "Demo moving to Thursday" — inferred from Apr 19 email thread with Apex
```

**P4 hook:** the `confirmed` field on `decision_candidate` observations is the stub for P4's approval flow. P4 wires up a reply channel so you can confirm/reject from the brief itself, writing confirmed decisions to `decisions.md` automatically. No rearchitecting of memory required.

---

## Layer 4: Retrieval

`memory_retriever.py` runs before the Claude brief call, alongside people context injection.

- Reads all non-suppressed, non-expired `data/memory/*.md` files
- Returns a formatted `## Cross-Day Memory` context string
- Token budget: if total memory context exceeds 1500 tokens, truncates oldest/lowest-activity memories first; pinned memories are never truncated

**Injected into brief prompt:**
```
## Cross-Day Memory

**apex-account** (last updated: 2026-04-17)
Pattern: Appeared in top 3 priorities 4x in 2 weeks, no resolution. Contract renewal thread open 8 days.
Decision: Pausing outreach until May fiscal year start.
Watch: Deal stagnant since demo Apr 8 — risk of going cold.

**payment-processing-issues** (last updated: 2026-04-16)
Pattern: Support fires recurring ~every 2 weeks. Last 3 instances traced to failed webhook retries.

Decision Candidates (unconfirmed):
• "Not pursuing Riverside lead" — inferred from Apr 18 Slack DM to Ken
```

---

## Cold-Start Behavior

Memories are empty on day 1. They populate after the first synthesis run (day 2 morning). The brief should surface this rather than silently injecting nothing.

**How it works:** `memory_retriever.py` determines cold-start status before the Claude call and returns it alongside the memory context string. It is injected into the brief prompt as a system note and rendered as a banner in the brief HTML template — it is not generated by Claude.

| Run | Message |
|-----|---------|
| Day 1 | `"Memory building — context improves with each run (day 1 of 3)"` |
| Day 2 | `"Memory building — patterns will emerge after a few more runs (day 2 of 3)"` |
| Day 3+ | No message shown; memory is operational |

Threshold is configurable: `memory.cold_start_days` (default: 3).

---

## Config Changes

```json
"memory": {
  "enabled": true,
  "dir": "data/memory",
  "observations_file": "data/memory/observations.jsonl",
  "decisions_file": "data/memory/decisions.md",
  "archive_dir": "data/memory/archive",
  "observation_lookback_days": 30,
  "default_ttl_days": 90,
  "activity_extension_days": 30,
  "cold_start_days": 3,
  "retrieval_token_budget": 1500
}
```

---

## Data Flow Summary

```
Run N (today):
  collect() → generate_brief() → send()
           ↓
  observe(email_threads, pipeline, brief_output, issues, decisions_file)
           → append to observations.jsonl
           ↓ (async)
  synthesize(observations[-30d], email_snippets, slack_dms)
           → write/update data/memory/{topic}.md
           → move expired files to archive/

Run N+1 (tomorrow):
  retrieve_memories() → ## Cross-Day Memory context
           ↓
  generate_brief(... + memory_context)
```

---

## What This Does Not Do

- **No brief-to-memory feedback loop for approvals** — that's P4. Decision candidates surface in the brief but require manual confirmation for P3.
- **No semantic search** — retrieval is read-all-active-files, not vector search. Token budget handles scale for now. If memory files multiply significantly (50+), a future iteration can add topic-based filtering.
- **No outbound email tracking** — still a P4 gap flagged in P2.
