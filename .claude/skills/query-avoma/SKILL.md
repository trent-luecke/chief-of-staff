---
name: query-avoma
description: Use when Trent asks to find, look up, pull, check, or search his Avoma meetings, calls, recordings, or transcripts — by title, attendee, or date (e.g. "find the Mark Fisher call from yesterday", "pull the transcript for X", "what calls did I have on 6/24"). For quick ad-hoc lookups, NOT the full meeting-analysis pipeline.
---

# Query Avoma

Quick, read-only access to Trent's Avoma meetings and transcripts. Use the helper
script as the access point — do **not** hand-roll API calls or run the heavy
analysis pipeline (`collectors/avoma.py` / `scripts/avoma_*.py`) unless the user
explicitly wants features/gaps/objections/signals extraction.

## Pick the right tool FIRST (this is where searches go wrong)

There are three Avoma access paths. Most flaky results come from picking the
wrong one, not from bad query wording. Decide by the **shape of the question**:

| Question shape | Right tool | Why |
|---|---|---|
| **Enumeration / completeness / date-bounded** — "all demos last week", "every call with X", "how many", "which calls" | `query_avoma.py list` (below) | Live REST, returns **every** matching call, real `--from-date/--to-date`. The only path that can answer "all of X." |
| **Content / patterns** — "what did they say about pricing", "common objections", "themes across onboarding" | `search_transcripts` MCP tool | Semantic search over indexed calls. Set `scope` (`demos` default / `onboarding` / `all`). |
| **"Is this call in the search index?"** — before running a semantic search on a named person | `list_meetings` MCP tool | Fast metadata check on the **indexed** set only (not all of Avoma). |

**Two hard rules:**
- **Never answer an "all / every / count / last week" question with `search_transcripts`.** It's semantic top-12 with **no date filter** — it silently returns a plausible-looking *partial* set. Enumerate with `query_avoma.py list` first, then (if needed) pull content on the specific calls.
- **A question can be multi-source.** "Demos *tied to sales* last week" = enumerate demos (`query_avoma.py list`) **joined to** pipeline/revenue data (`data/pipeline_cache.json`, `lib/metrics_client`). Avoma only answers the "which calls happened" half.

## Do NOT reuse stale analysis snapshots

`data/state/transcript_scan/*.json` (e.g. `opus_analysis.json`,
`analysis_workflow-builder.json`, `analysis_integration.json`) are **frozen
outputs of past, narrowly-scoped investigations** (mostly the OS Workflow Builder
/ automation-JTBD work). They are **not** a general recap source.

Do not answer a fresh question from them. Pull live via `query_avoma.py` unless
Trent explicitly asks about *that specific prior analysis by name*. If one looks
tempting, that's the signal to stop and enumerate fresh instead.

## Access point

```bash
# Find a meeting (lists subject, start, uuid, attendees)
python3 .claude/skills/query-avoma/query_avoma.py list --date 2026-06-24
python3 .claude/skills/query-avoma/query_avoma.py list --date 2026-06-24 --title "Mark Fisher"
python3 .claude/skills/query-avoma/query_avoma.py list --date 2026-06-24 --attendee "Luke Martin"

# Pull a transcript once you have the uuid (speaker-labeled, timestamped)
python3 .claude/skills/query-avoma/query_avoma.py transcript --uuid <uuid>
```

For an explicit UTC window instead of a local day: `list --from-date 2026-06-24T00:00:00Z --to-date 2026-06-25T12:00:00Z`.

## Notes

- **Auth:** reads `AVOMA_API_KEY` from `.env` in the project root. No flags needed.
- **Timezone:** Avoma `start_at` is UTC; Trent is US Central. `--date` pads the
  UTC window on both ends so meetings near local midnight aren't missed. When the
  user says "yesterday/6/24", that's the Central day — the padding handles it.
- **Speakers** come back as `S0/S1/S2…` (anonymous IDs), not names. Map them
  yourself from the attendee list + conversational context; the transcript header
  prints the attendees to help.
- **Two meetings can share a start slot** — when filtering by title, confirm you
  grabbed the right one (the list output shows attendees to disambiguate).

## Underlying API (if the script can't cover it)

Base `https://api.avoma.com`, `Authorization: Bearer $AVOMA_API_KEY`:
- `GET /v1/meetings?from_date=&to_date=` — list (UTC ISO 8601)
- `GET /v1/meetings/{uuid}` — single meeting detail
- `GET /v1/transcriptions?meeting_uuid={uuid}` — transcript segments
