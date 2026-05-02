# Chief of Staff Research Brief

Synthesized from five reference builds. Articles 3 and 5 were inaccessible (403/blocked), so this draws primarily from Donovan Li, Knowledge Work, and the Carbon & Code piece.

---

## Common Architecture Patterns

**Two-tier processing is the dominant pattern.** Every serious build separates urgency detection from deep analysis. Donovan Li runs lightweight rule-based pattern matching every 30 minutes (zero LLM cost) and only fires Claude once a day at 5 PM for full triage. This isn't optional polish — it's what makes the system economically viable and fast enough for real-time use.

**Batch at night, scan during the day.** The cadence that appears across multiple builds: hourly lightweight scan (rules/heuristics) → end-of-day deep batch (LLM) → morning synthesis (LLM). The morning brief is always a synthesis of work done the night before, not a live pull.

**Markdown files as the source of truth, not databases.** Both Leibovich (Adobe GM) and the Knowledge Work author converge on this: folders and markdown files, no database. This removes operational overhead, keeps files human-readable and editable, and makes the system inspectable without tooling. Donovan Li is the outlier — he went full database (25 tables, ClickHouse, Postgres) and explicitly calls out the complexity cost.

**macOS launchd over cron.** Donovan Li switched from cron to launchd. More reliable on Mac, handles sleep/wake correctly, better logging. Worth considering for a Mac-native build.

**Monolithic script is a dead end.** Donovan Li tried it, abandoned it. The failure modes: LLM gets called on spam (cost explosion), daily batches introduce latency, statelessness causes repetition, binary permission model causes trust problems. The fix is modular pipelines with separate concerns per stage.

---

## Best Ideas to Steal

**Separate urgency detection from analysis.** Run a fast, cheap scan (keyword matching, sender patterns, subject line heuristics) to flag truly urgent items. Only send those to Claude. This cuts LLM costs ~80% and enables real-time alerts without waiting for a batch.

**Graduated autonomy model.** Donovan Li's three trust levels are the right mental model for any action the system takes autonomously. Start with "always ask," graduate to "supervised," eventually reach "autonomous" based on measurable performance criteria. Even if you're not auto-sending emails, this framing applies to any system action.

**Memory with decay.** His three-layer memory system (observations → synthesized memories → retrieval) and the decay rates (0.02 for recently accessed, 0.05 normal, 0.08 abandoned, immune if pinned) prevent context pollution over time. Without decay, memory systems fill up with stale noise and the LLM starts hallucinating based on old context.

**550-token context sweet spot.** Empirically discovered: below 400 tokens loses context, above 700 shows diminishing returns. 550 is the target for memory retrieval injection. Good constraint to design around.

**Context > prompt engineering.** The Knowledge Work author's core finding: time spent improving what context the system has access to produces better results than time spent tweaking prompts. Architectural implication: invest in the data collection and structuring layer, not the prompt layer.

**People file auto-updated from signals.** From Leibovich and Carbon & Code: maintain a file of people you interact with (key contacts, relationship context, recent touchpoints) that auto-updates from calendar events and email signals. This is what makes the morning brief personally relevant rather than generic.

---

## Mistakes and Anti-Patterns

**Monolithic script.** Already covered — the failure modes are real. Modular pipelines win.

**Shared state between concurrent jobs.** Donovan Li's multi-tenant bugs: shared environment variables leaked data between users. Same class of bug applies to running multiple jobs that touch the same state files. Explicit locking or clear job sequencing required.

**No observability from day one.** He instrumented everything with Langfuse (LLM tracing) and Gatus (uptime). Flying blind on what the system is actually doing is how you get surprised by cost explosions and silent failures. Even a simple log file per run is better than nothing.

**Over-engineering the storage layer.** Databases add operational overhead, require migrations, and create a dependency on tooling to inspect state. Unless you have a specific reason (multi-tenant, complex queries, high volume), markdown + JSON files are the right default. You can always migrate later.

**Using vector embeddings for memory retrieval.** Counterintuitive: Donovan Li found FTS5 full-text search more reliable than vector embeddings in production for this use case. The emotional appeal of "semantic search" doesn't outperform keyword matching when your corpus is structured personal data with consistent vocabulary.

**Building the interface before the pipeline.** Tess Posner (Carbon & Code) focuses heavily on the dashboard/interface. The risk is spending time on what's visible rather than what's valuable. The brief pipeline should work perfectly via email before any UI work starts.

---

## Tools and Libraries

| Tool | Purpose | Notes |
|------|---------|-------|
| Python | Core runtime | Universal choice across all builds |
| macOS launchd | Job scheduling | Preferred over cron for Mac; handles sleep/wake |
| Claude Haiku | Classification, urgency detection | Cheap, fast, good enough for structured tasks |
| Claude Sonnet | Deep analysis, brief generation | More expensive, use only where quality matters |
| Jinja2 | HTML email/dashboard templating | Standard choice |
| FTS5 (SQLite) | Memory retrieval | Beats vector search for structured personal data |
| Langfuse | LLM tracing/observability | Free tier sufficient for personal use |
| `caffeinate` | Keep Mac awake for overnight jobs | Simple, built-in macOS utility |
| `gws` CLI | Gmail + Calendar reads | Already in your stack, confirmed working |

---

## How They Handle State/Memory Between Runs

**The winning pattern is a three-layer stack:**

1. **Raw observations** — structured logs written at every integration point. Zero cost (no LLM). Append-only. Example: "Email from john@example.com at 2:14 PM, subject: contract renewal, thread_id: abc123."

2. **Synthesized memories** — LLM batch that runs nightly, reads the day's observations, and writes durable summaries. Applies decay to old memories. This is the "what the system knows" layer.

3. **Retrieval** — FTS5 search over synthesized memories, injected into context at brief generation time with a hard token cap (~550 tokens).

**For your use case,** the simpler version is: daily JSON state snapshot that captures open thread IDs + active project state. Diff yesterday's snapshot against today's live data to detect changes. This is already your design and it's the right call for v1.

---

## How They Handle the Auto-Resolve Problem

This is the hardest problem and none of the builds fully solve it elegantly. Approaches found:

**State diffing (your current approach).** Snapshot the IDs of open items at the end of each run. On the next run, compare against live data. If an email thread disappears from "unread/starred," it resolved. If a Notion item changes status, it resolved. Simple, reliable, zero additional API calls.

**Behavioral signal detection.** Donovan Li infers resolution from behavioral signals: "if I sent a reply to this thread, the loop is closed." This requires monitoring the Sent folder, not just the inbox. More accurate than pure ID diffing but adds complexity.

**Graduated confidence with hard overrides.** For auto-actions (not just detection), he tracks edit rate, send rate, and confidence score before graduating a workflow to autonomous. The hard override — "VIP and family contacts are hardcoded into NEVER_AUTO_SEND" — is the pattern worth stealing: define the things the system should never do autonomously before you build the autonomy layer.

**The gap nobody solves well:** calendar events. Knowing a meeting "happened" is easy (it passes). Knowing what came out of it — action items, follow-ups — requires either meeting transcript integration (Earmark, Fireflies, etc.) or manual capture. This is where the Zapier/Apple Shortcut quick capture flow fits: it's the escape hatch for things the system can't detect automatically.

---

## Relevance to Your Build

**Your current architecture is sound.** The gws CLI + Python + daily state snapshot + Claude for brief generation is exactly the pattern the best builds converge on. You're not missing anything structural.

**The watcher is the biggest open question.** Hourly urgency scanning during business hours is the right call, but "what counts as urgent" needs a definition sharp enough to run as code before Claude sees it. The Doney Li pattern (rule-based Tier 1, LLM Tier 2) is the right model.

**The dashboard is the least important thing to build first.** Get the brief and watcher running perfectly. The dashboard is valuable but it's a UI layer on top of data that the pipeline already has.

**The quick capture mechanism is a weak link.** Zapier + Apple Shortcut works but has the 1-second Code step timeout constraint. The question is whether that matters — if Zapier is just routing a webhook payload to Notion and Claude classification happens asynchronously, the timeout may not be an issue. Worth clarifying before replacing the stack.
