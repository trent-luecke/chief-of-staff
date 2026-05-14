# People Store — Design Spec

**Date:** 2026-04-18
**Status:** Approved

---

## Problem

The system reads calendar events, email threads, and Slack messages but has no memory of who those people are. A name like "Luke Martin" is just a string — the system doesn't know he's on the rev team, what's open between you, or that you're both working on CSM coverage. People context is the highest-leverage gap for brief quality.

---

## Goal

A persistent `data/people/` store that:
1. Accumulates signals automatically from calendar, Gmail, and Slack DMs on each brief run
2. Surfaces missed deliverables and relationship context to Claude as ambient background — not a new section in the brief, but richer existing sections

---

## File Organization

All contact files live in `data/people/`. Files are named `firstname-lastname.md` or `firstname.md` for contacts whose last names are unknown.

**Current files to migrate from project root:**
- `luke-martin.md`, `luke-green.md`, `nicole-foley.md`, `james-peters.md`, `hewitt-tomlin.md`
- `clayton.md`, `rachel.md`, `heather.md`
- Delete `__pycache__/people copy/` (duplicate backup)

---

## File Format

Each file has two zones separated by a hard marker:

```
# Luke Martin

**Email:** lmartin@teambuildr.com
**Role:** Revenue team
...

## Relationship
Hand-written context about the working relationship.

## Notes
- Hand-written notes

<!-- AUTO-UPDATED: do not edit below this line -->
## Activity
**Last seen:** 2026-04-17
**Recent touchpoints:**
- 2026-04-17 | email | "CSM coverage for Q2"
- 2026-04-15 | calendar | "Rev Team Sync"
**Open threads:**
- "CSM coverage for Q2" — needs reply
```

**Above the marker:** Trent's territory. Role, relationship context, behavioral notes. The system never reads this section to rewrite it, never writes above the marker.

**Below the marker:** Agent territory. Last seen date, last 5 touchpoints (date, source, subject), open email threads flagged needs-reply. The system replaces this entire section on each run. Never hand-edit below the marker — it will be overwritten.

The implementation splits on the marker string, keeps everything before it verbatim, then writes `marker + fresh content`. No parsing of the human section.

---

## Matching Logic

The system builds an in-memory `email → filepath` index at runtime by scanning all `.md` files in `data/people/` and extracting the `**Email:**` field. No separate index file to maintain — the markdown files are the index.

**Match sources:**
- Calendar events: attendee email addresses
- Gmail threads: sender email addresses
- Slack DMs: resolved via `users_info()` API call (Slack user ID → email)

**On no match:** Unmatched emails from calendar and Gmail are skipped silently. New contact files are not auto-created from calendar/Gmail — you create them manually when someone matters.

---

## Enrichment Step

New module: `processors/people.py`

Runs in `main.py` after all collectors finish, before the brief processor calls Claude.

```
collect_calendar() → collect_gmail() → collect_slack() →
enrich_people(calendar_events, email_threads, slack_dms) →  ← NEW
generate_brief(all_data + people_context)
```

**`enrich_people()` flow:**
1. Build email→file index from `data/people/`
2. Walk calendar events → match attendee emails → record touchpoint
3. Walk email threads → match sender emails → record touchpoint + flag open threads
4. Walk Slack DMs → match user emails → record touchpoint
5. For each matched contact: write updated `<!-- AUTO-UPDATED -->` section
6. For Slack DMs with no matching contact: pass the DM thread to Claude with a structured prompt. Claude returns JSON: `{"worth_tracking": bool, "suggested_filename": "firstname-lastname.md", "display_name": str, "reason": str}`. If `worth_tracking` is true, auto-create `data/people/<suggested_filename>` pre-populated with Slack display name, email (from `users_info`), and Slack user ID. Human sections (`## Relationship`, `## Notes`) are left empty for Trent to fill in.

**Touchpoint data stored — two tiers:**

- **Routine** (rolling, last 5): calendar appearances, email replies with no action item. Oldest falls off when a sixth is added.
- **Significant** (persistent): touchpoints where Claude identified a deliverable, commitment, or key decision. These never decay automatically. They are cleared only when explicitly resolved — either by Trent editing the file above the marker, or by a future resolved-items mechanism.

Claude assigns significance during enrichment by evaluating each new touchpoint for: open deliverable, stated commitment, key decision, or follow-up dependency.

Each touchpoint entry:
- Date (ISO)
- Source: `calendar` | `email` | `slack`
- Subject/title
- `significant: true` (if applicable) + one-line reason

**Open threads:** email threads where `needs_reply=True`, stored as subject strings.

---

## Slack DM Support

The existing `collectors/slack.py` only handles channels. New function needed: `fetch_dm_messages(token, since_hours)` using:
- `conversations_list(types="im")` — get all DM channel IDs
- `conversations_history()` per DM channel — get recent messages
- `users_info(user_id)` — resolve Slack user ID to display name + email

DMs only. No channel sweeps.

---

## Brief Integration

`processors/brief.py` loads all contact files from `data/people/` where that person appeared in today's calendar or email (matched by the same email index). Full file content — human notes + auto-section — is injected into the Claude prompt as background context before the brief is generated.

People context is **ambient input**, not a new output section. Claude uses it to:
- Identify missed deliverables and surface them in action items
- Add relationship context to follow-up suggestions
- Connect open threads to the people involved

The brief output format is unchanged.

---

## What's Not in Scope

- Auto-creating profiles from calendar/Gmail (manual only for those sources)
- Any UI for viewing/editing people files (use the editor directly)
- Matching on display names / fuzzy name matching (email is the only key)
