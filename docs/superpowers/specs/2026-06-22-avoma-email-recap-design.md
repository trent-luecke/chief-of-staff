# Avoma Slack Output: Prospect-Facing Email Recap

**Date:** 2026-06-22
**Status:** Approved design — ready for implementation plan

## Problem

When an Avoma transcript is processed in the `avoma-trent` Slack channel, the bot
posts three parts to the thread:

1. `*Summary*` — a 2-3 sentence internal outcome summary
2. `*Action Items*`
3. A Notion payload to paste into the Claude Desktop app for pipeline updates

The `*Summary*` section is effectively useless: the real call summary is
re-generated later in Claude Desktop when running the pipeline update. What Trent
actually wants in that slot is a recap he can **paste into a follow-up email to the
prospect** — telling them what was discussed, which features were highlighted, any
price points covered, and a few open-ended questions to follow up on.

## Goal

Replace the Slack `*Summary*` section with a scannable, prospect-facing recap built
for pasting into a follow-up email — **without** disturbing the internal `summary`
field that feeds the Notion/Claude-Desktop pipeline payload.

## Decisions (locked)

- **Format:** structured/bulleted recap with four sections — *What we covered*,
  *Features highlighted*, *Pricing discussed* (only if price/tiers came up), *Open
  questions* (2-3 open-ended questions phrased to the prospect).
- **Open questions** live as a section *inside* the recap, phrased as questions to
  the prospect (not a separate internal Slack note).
- **Production method:** a single freeform `email_recap` string composed by Claude
  in one shot (Option A), not assembled in Python from sub-fields.
- **Internal `summary` is untouched** — still "2-3 sentence outcome summary," still
  feeds `_build_notion_prompt`. Two distinct outputs, each fit for purpose.
- **Slack header label:** `📧 *Follow-Up Email Recap*` (replaces `*Summary*`).
- **Fallback:** if `email_recap` is empty, fall back to `t.summary` so the slot is
  never blank.

## Changes

### 1. Tool schema — `collectors/avoma.py`

In `_EXTRACT_TOOL.input_schema.properties`, add:

```python
"email_recap": {
    "type": "string",
    "description": (
        "A prospect-facing recap the rep can paste into a follow-up email. "
        "Plain text, scannable, with these sections as short labeled blocks: "
        "'What we covered' (1-2 lines), 'Features highlighted' (the OS features "
        "that resonated), 'Pricing discussed' (ONLY if price or tiers came up — "
        "omit this section entirely otherwise), and 'Open questions' (2-3 "
        "open-ended questions phrased directly to the prospect). No greeting or "
        "signature. No internal jargon — do not surface objections/gaps as such; "
        "reframe concerns as questions where natural."
    ),
},
```

Add `"email_recap"` to the `required` list.

### 2. Dataclass — `collectors/avoma.py`

Add to `AvomaTranscript`:

```python
email_recap: str = ""
```

### 3. Populate the field in BOTH constructors — `collectors/avoma.py`

Both `AvomaTranscript(...)` construction sites must set the new field:

- `fetch_recent_meetings` (~line 365)
- `fetch_meeting_by_uuid` (~line 426) — **this is the path the Slack processor uses**

Add to each:

```python
email_recap=result.get("email_recap", ""),
```

### 4. System prompt — `collectors/avoma.py`

Append a bullet to `_SYSTEM_PROMPT` describing `email_recap` (mirrors the schema
description above). Emphasize: it is for the prospect, not internal; omit the
Pricing section when no price came up; keep it copy-paste ready.

### 5. `max_tokens` — `collectors/avoma.py`

In `_analyze_with_claude`, bump `max_tokens` from `1500` → `2000` to give the recap
room without crowding the other extracted fields.

### 6. Slack message — `processors/avoma_phase1.py`

In `_build_slack_message`, replace the summary block:

```python
# before
"*Summary*",
t.summary or "(no summary)",

# after
"📧 *Follow-Up Email Recap*",
t.email_recap or t.summary or "(no recap)",
```

Action Items section and the Notion payload path (`_build_notion_prompt`, which
still reads `t.summary`) are unchanged.

## Out of scope

- No change to the Notion/Claude-Desktop pipeline payload.
- No new structured fields (`price_points`, `follow_up_questions`) — the recap is a
  single string.
- No change to triggering, dedup, or the Cloudflare bridge.

## Testing

- Unit-level: construct an `AvomaTranscript` with a populated `email_recap` and
  assert `_build_slack_message` emits the `📧 *Follow-Up Email Recap*` header and the
  recap text; assert fallback to `summary` when `email_recap` is empty, and
  `(no recap)` when both are empty.
- Manual: re-run a recent transcript through `fetch_meeting_by_uuid` and inspect the
  Slack output for email-ready phrasing and correct conditional pricing.
