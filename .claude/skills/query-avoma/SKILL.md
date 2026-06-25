---
name: query-avoma
description: Use when Trent asks to find, look up, pull, check, or search his Avoma meetings, calls, recordings, or transcripts — by title, attendee, or date (e.g. "find the Mark Fisher call from yesterday", "pull the transcript for X", "what calls did I have on 6/24"). For quick ad-hoc lookups, NOT the full meeting-analysis pipeline.
---

# Query Avoma

Quick, read-only access to Trent's Avoma meetings and transcripts. Use the helper
script as the access point — do **not** hand-roll API calls or run the heavy
analysis pipeline (`collectors/avoma.py` / `scripts/avoma_*.py`) unless the user
explicitly wants features/gaps/objections/signals extraction.

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
