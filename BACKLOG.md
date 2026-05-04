# Chief of Staff — Backlog

> **Core principle:** Context beats prompt engineering. The system is prompting Claude well — the gap is in what it knows.

---

## ✅ Shipped (breadcrumb trail)

| Item | Shipped | What it did |
|------|---------|-------------|
| Q1 Memory Token Budget | 2026-04-20 | Reduced retrieval budget 1500→550 tokens; empirically derived sweet spot |
| Q2 Brief Signal-to-Noise | 2026-04-20 | Removed empty sections, capped projects at 7, cut open-loop metadata |
| P0 Cloud Hosting | 2026-04-19 | Moved from macOS launchd to GitHub Actions; OAuth2 refresh token via Secret |
| P1 People Intelligence | 2026-04-18 | `data/people/` store with machine-written Activity sections; per-contact Claude enrichment |
| P2 Pipeline Data Source | 2026-04-19 | Notion pipeline seeded into `data/pipeline_cache.json` via MCP; flare-up routing |
| P3 Cross-Day Memory | 2026-04-19 | `observations.jsonl` → `memory_synthesizer` → 90-day TTL `.md` files → retriever |
| P4 Two-Way Interface | 2026-04-20 | Telegram bot via Cloudflare Worker + GitHub Actions; JARVIS personality |
| P5 Weekly Synthesis | 2026-04-20 | Sunday Claude narrative with 7-day patterns, carry-forwards, cost summary |
| P7 Gmail Draft Push | 2026-04-22 | Absorbed into P9 `create_email_draft` tool |
| P8 Project Intelligence | 2026-04-22 | Absorbed into P9 `create_project` tool |
| P9 Tool Use & Action Execution | 2026-04-22 | Native Anthropic tool use loop; 12 tools (read + write); no more JSON parsing |
| P10 Outbound Email Tracking | 2026-04-22 | Sent-mail scan; `direction` field on pipeline activity records |
| P12 Observability | 2026-04-20 | All 8 Claude call sites log to `data/logs/run_log.jsonl` with token counts + cost |
| P13 Graduated Memory Decay | 2026-04-23 | Abandoned memories (60d+) shortened to 14-day TTL; pinned memories immune |
| P14 Phase 1 — Vector Ingest | 2026-04-30 | Pinecone serverless index; Voyage AI embeddings; `observations` + `memories` namespaces |
| P14 Phase 2 — Semantic Retrieval | 2026-04-30 | Pinecone replaces recency-based retriever; query built from calendar + email + leads |

---

## Open — Single-User Improvements

### P11 — Meeting Transcript Integration
**Highest remaining capability gap.** System knows meetings happened (calendar) but has zero signal for what came out of them.

- Choose a transcript provider: Fireflies, Granola, or Fathom (all offer webhooks or email delivery)
- Ingest summary into `data/memory/observations.jsonl` as a structured observation post-meeting
- Memory synthesizer already picks these up — gap is purely the ingestion path

---

### P14 Phase 3 — Semantic Telegram Queries
Replace the `_load_local_context` memory dump in `query.py` with a Pinecone query seeded from the user's actual query text. Currently the tool loop gets the full context dump regardless of what was asked; semantic retrieval would surface only what's relevant to the query.

---

### P14 Phase 4 — Proactive Pattern Detection
Alert on emerging patterns without being asked: "3 stale leads this week, new pattern" or "you've had 4 back-to-back no-shows this month." Requires the weekly synthesizer to compare against prior weeks' observations and flag anomalies, not just summarize.

---

### Notion Write Access
Update pipeline lead fields (status, last_contacted, notes) from Telegram. Blocked on Notion API key with workspace admin access. Low urgency — pipeline reads are sufficient for now.

---

## Open — Team Scale

These items are sourced from a Hermes Agent architecture review (2026-05-03). Hermes is a mature open-source agent runtime (130K stars, MIT) with strong multi-user and multi-platform delivery patterns. The chief-of-staff already has better context depth than Hermes; what it lacks is everything needed to run for 6+ people.

---

### T1 — Multi-Channel Delivery *(short-term, low effort)*
The brief is email-only. For team use, "Slack DM it to me at 7 AM" is dramatically better DX. The system already reads Slack — it doesn't write to it.

- Add `outputs/slack_sender.py` with per-user channel/DM target
- Per-user config block in `config.json`: `delivery: {email: true, slack_dm: "@username"}`
- Hermes' gateway pattern is the right model: each platform is an isolated adapter, not a conditional branch in `sender.py`

---

### T2 — Tool Registry Refactor *(short-term, medium effort)*
`processors/query_tools.py` is monolithic — 12 tools defined in one file. Hermes uses self-registering tools (each tool is its own file, auto-discovered at import). Worth adopting before the tool count grows further, and essential if team members will add their own custom tools without touching core files.

- Each tool: its own file in `processors/tools/`
- File exports: `schema`, `handler`, optional `check_fn` and `requires_env`
- Registry discovers at import; `ask.py` just calls `registry.get_tools()`

---

### T3 — Approval Gates for Write Tools *(short-term, low effort)*
Write tools (create_email_draft, add_capture, update_project_next_action) currently execute immediately on Claude's decision. For a team product — especially email draft creation on behalf of someone — a confirmation step before execution matters.

- `"confirm_writes": true` config flag (default `false` for backward compat)
- Write tools return a pending confirmation with a preview; user sends "confirm" to execute
- Hermes implements this cleanly with an approval queue pattern

---

### M1 — Per-User Config and Data Isolation *(medium-term, foundational)*
**The hardest prerequisite for team use.** The entire system today assumes one identity: one OAuth token set, one `data/` directory, one email address. Nothing else on this list works at team scale without this.

**What's needed:**
- Namespace `data/` by user: `data/users/{user_id}/people/`, `data/users/{user_id}/memory/`, etc.
- Per-user `config.json` (delivery prefs, role/context, which signal sources are active)
- Per-user OAuth tokens (Google Calendar, Gmail, Slack) — currently one set, hardcoded via GitHub Secret

**Architecture decision: hosted service (decided 2026-05-03).** One deployment, multi-tenant, Google OAuth per user. Trent manages the infra; team members log in via a web UI. The untracked `web_app/` directory is the starting point.

---

### M2 — Web Onboarding + Config UI *(medium-term, depends on M1)*
A simple FastAPI app where each team member:
1. Logs in via Google OAuth (gets their own Calendar + Gmail access)
2. Sets delivery preference (email, Slack DM, etc.)
3. Customizes signal sources (pipeline view depth, calendar lookback, etc.)
4. Views brief history

Without this, "the team can use it" means "6 people edit JSON files." The `web_app/` directory is already seeded.

---

### L1 — Shared vs. Personal Context Layers *(long-term)*
The most powerful version of this for a sales/ops team has two layers:
- **Personal:** My calendar, my email, my 1:1 notes
- **Shared:** Company pipeline stage changes, team announcements, shared deals, company-wide bugs

Right now everything is personal. A shared context layer (pipeline status, new bugs, company metrics visible to all team members) would make this useful for coordination, not just individual productivity.

---

### L2 — Role-Based Signals and Skill Customization *(long-term)*
Trent's brief needs pipeline-heavy context. An engineer's brief needs bug tracker context. A coach-facing CSM needs onboarding context. Hermes' skill system (users teach the agent new capabilities via conversation) is the right model for making this extensible without changing core code.

---

### L3 — Voice / Mobile-First Delivery *(long-term)*
Hermes has free TTS (Edge TTS, no API key) and Faster-Whisper for STT baked in. For a team primarily on phones, a 90-second audio brief is more realistic than reading an email. Not urgent, but the right long-term delivery format for mobile users.

---

---

## Recommended Roadmap to Team-Wide Use

The sequencing below is driven by dependencies, not just priority. Each phase has to be solid before the next one is worth building.

---

### Phase 0 — Finish the Single-User Experience
*Before scaling to a team, the core product should be as good as it can get for one person.*

1. **P11 — Meeting Transcript Integration** — biggest remaining context gap. Whatever the team uses (Fireflies, Granola, Fathom), get a webhook ingesting into `observations.jsonl` before anyone else onboards. They'll expect this.
2. **P14 Phase 3 — Semantic Telegram Queries** — rounds out the two-way interface. Right now the query loop dumps full context regardless of what was asked; this makes it actually responsive.

*Exit criteria: the daily brief and Telegram interface are sharp enough that you'd confidently hand them to someone else.*

---

### Phase 1 — Structural Cleanup Before Multi-User Complexity
*Easier to refactor internals while there's one user. Doing this after M1 means touching multi-user code while mid-migration.*

3. **T2 — Tool Registry Refactor** — move from monolithic `query_tools.py` to self-registering per-file tools. Non-negotiable before the tool count grows across roles and users. Also makes T3 much cleaner to implement.
4. **T3 — Approval Gates for Write Tools** — add the `confirm_writes` flag. Low effort now; much harder to retrofit after other users are executing write tools against their own email and data.

*Exit criteria: adding a new tool is a single new file. Write tools can be gated without touching the core loop.*

---

### Phase 2 — Multi-User Infrastructure (the hard one)
*This is the foundation everything else sits on. Don't start M2 until M1 is solid.*

5. **M1 — Per-User Config + Data Isolation** — namespace `data/` by user, per-user OAuth tokens, per-user config. The hosted architecture decision is made; this is what makes it real. Expect this to touch almost every file in the system.

*Exit criteria: you can run the brief for two different users (e.g., yourself + one other) from the same deployment without any state bleed.*

---

### Phase 3 — The Front Door
*Once the infra supports multiple users, give them a way to actually get in.*

6. **M2 — Web Onboarding + Config UI** — Google OAuth login, delivery preferences, signal source toggles, brief history. The `web_app/` directory is already seeded. This is what makes onboarding a link, not a GitHub tutorial.
7. **T1 — Multi-Channel Delivery** — add Slack DM delivery alongside email. Do this in Phase 3 (not earlier) because delivery targets are per-user config, which requires M1 to be in place.

*Exit criteria: a new team member can onboard without Trent touching any code or config files.*

---

### Phase 4 — Shared Team Context
*Individual briefs are live. Now make them useful for coordination.*

8. **L1 — Shared Context Layer** — company-wide signals (pipeline stage changes, new bugs, team-wide metrics) surfaced on top of each person's personal context. This is where the product shifts from "personal productivity tool" to "team coordination layer."

*Exit criteria: a pipeline deal moving to Closed-Won appears in the relevant team members' briefs without anyone manually adding it.*

---

### Phase 5 — Depth and Polish
*Nice-to-haves that compound on a healthy foundation.*

9. **L2 — Role-Based Signals + Skill Customization** — engineer's brief is bug-heavy, sales brief is pipeline-heavy, CS brief is onboarding-heavy. Without L1's shared layer, this is just per-user config tweaking. With it, it's genuinely differentiated context per role.
10. **P14 Phase 4 — Proactive Pattern Detection** — anomaly alerts ("3 stale leads this week, new pattern"). Requires enough history across multiple users to be meaningful.
11. **L3 — Voice / Mobile-First Delivery** — TTS audio brief for mobile users. Nice-to-have once delivery reliability is solid across channels.

---

**Summary:**

```
Phase 0: P11 → P14 Phase 3              (best single-user experience)
Phase 1: T2 → T3                        (clean internals before complexity)
Phase 2: M1                             (multi-user foundation)
Phase 3: M2 → T1                        (onboarding + delivery)
Phase 4: L1                             (team coordination value)
Phase 5: L2 → P14 Phase 4 → L3         (depth + polish)
```

---

## Status as of 2026-05-03

**Shipped:** Q1, Q2, P0–P5, P7–P10, P12–P14 (Phase 1–2)

**Open — single-user:**
1. P11 — Meeting transcript integration (highest remaining capability gap)
2. P14 Phase 3 — Semantic Telegram queries
3. P14 Phase 4 — Proactive pattern detection
4. Notion write access (blocked on API key)

**Open — team scale (new):**
1. T1 — Multi-channel delivery (Slack DM) — low effort, start here
2. T2 — Tool registry refactor — do before tool count grows
3. T3 — Approval gates for write tools — low effort
4. M1 — Per-user config + data isolation — foundational, hardest item
5. M2 — Web onboarding + config UI — depends on M1
6. L1 — Shared context layer (company-wide signals)
7. L2 — Role-based signals + skill customization
8. L3 — Voice / mobile-first delivery
