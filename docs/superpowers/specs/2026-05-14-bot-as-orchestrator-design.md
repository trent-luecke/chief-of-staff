# Bot as Trusted Orchestrator

**Date:** 2026-05-14  
**Status:** Approved  
**Goal:** Make the Telegram bot a trusted control point for the entire chief-of-staff system — with visible confirmation of all writes, a path to update Notion pipeline records, influence over the morning brief, and the ability to propose and apply small code changes.

---

## Problem

The bot currently writes to local files silently. There is no confirmation of what was written or where, no feedback loop into Notion (the actual pipeline source of truth), no way to influence what appears in the morning brief, and no way to give the bot feedback that results in behavior changes. This creates a trust gap: notes feel like they go nowhere.

---

## Scope

Four capabilities, all implemented in `chief-of-staff/`. No changes to Cloudflare Worker, GitHub Actions workflows (except as output of Section 4), or the Cowork scheduling environment.

---

## Section 1 — Write Confirmation

### What changes
The system prompt in `processors/query.py` is updated to require an explicit receipt block after every tool call that writes data. Tool descriptions in `processors/query_tools.py` are updated to instruct Claude to confirm what was written and where.

### Receipt format
```
Done. Here's what I wrote:

  → Jake Torres (people/jake-torres.md): demo follow-up note, May 14
  → Notion queue: trial interest high, pricing concern, follow-up May 21
  → Captures: "follow up with Jake Torres by May 21"

This will surface in tomorrow's brief under pipeline follow-ups.
```

### Rules
- Every write tool produces a receipt entry.
- The receipt names the file or destination, the content written (paraphrased, not the full text), and the downstream effect (brief, bot-queryable, Notion queue).
- Read-only tool calls (search_gmail, get_calendar_events, get_person_profile, get_pipeline_lead) do not produce receipts.
- No new code required — this is a system prompt and tool description change only.

---

## Section 2 — Notion Update Queue

### What changes
A new tool `queue_notion_update` is added to `processors/query_tools.py`. It writes structured entries to `data/notion_updates_queue.json`. Cowork reads this file on a scheduled run and applies each entry to the Notion pipeline via MCP, then clears processed entries.

### Queue entry schema
```json
{
  "id": "uuid",
  "timestamp": "2026-05-14T10:23:00-05:00",
  "person": "Jake Torres",
  "action": "add_note | update_stage | set_follow_up | delete_record",
  "note": "Trial interest high, pricing concern. Follow up May 21.",
  "stage": "Trial",
  "follow_up_date": "2026-05-21",
  "reason": "Rep requested removal — deal closed lost"
}
```

Fields are optional except `person`, `action`, and `timestamp`. The `reason` field is required for `delete_record` actions.

### Supported actions
| Action | What Cowork does |
|---|---|
| `add_note` | Appends note to the Notion pipeline record |
| `update_stage` | Updates the deal stage field |
| `set_follow_up` | Sets a follow-up date on the record |
| `delete_record` | Deletes the Notion pipeline record after confirming single match |

### Delete safety rule
For `delete_record`: Cowork searches Notion for the person name before deleting. If zero or more than one record matches, it skips the entry and logs the conflict rather than guessing. The unprocessed entry remains in the queue file with a `status: "conflict"` field for manual resolution.

### Commit behavior
`data/notion_updates_queue.json` is committed back to the repo at the end of each GitHub Actions run (existing behavior for all `data/` files). Cowork reads the latest committed version on the schedule configured in Cowork.

### Bot confirmation
The receipt for a `queue_notion_update` call explicitly states the action queued and that Cowork will execute it on its next scheduled run.

---

## Section 3 — Brief Customization

### What changes
A new tool `set_brief_preference` is added to `processors/query_tools.py`. It appends entries to `data/brief_prefs.md`. The daily brief orchestrator (`main.py`) reads this file and injects its contents into the brief generation prompt.

### Preference format
Freeform text, one preference per entry, with a timestamp:

```markdown
## 2026-05-14
- Skip the gym scout section this week
- Always lead with pipeline follow-ups
- Remind me about Jake Torres tomorrow
```

### Brief integration
`main.py` reads `data/brief_prefs.md` and includes its contents under a `Current preferences` section of the brief prompt. Claude interpreting the brief applies these as natural language instructions — no parsing or schema required.

### Clearing preferences
The bot can also call `set_brief_preference` with a message like "clear all brief preferences" or "remove the gym scout skip." The tool appends a correction entry; the brief prompt sees both the original and the correction and interprets them together. This is intentionally simple — no delete logic needed.

---

## Section 4 — Telegram-Gated Code Changes

### What changes
A new tool `propose_code_change` is added to `processors/query_tools.py`. It reads a target file, generates a proposed change, runs a syntax check, and stores a pending change record. The bot sends the diff to Telegram and waits for an "approve" or "reject" reply.

### Whitelisted files
The tool only operates on:
- `processors/query_tools.py`
- `processors/query.py`
- `main.py`
- `config.json`

Any request targeting a file outside this list is rejected by the tool with an explanation.

### Flow
1. User describes desired change in Telegram (e.g., "trim the confirmation receipts" or "add a tool to look up cancellation reasons").
2. Bot calls `propose_code_change` with the target file and change description.
3. Tool reads the file, generates the modified version, writes the diff and full new content to `data/pending_change.json`.
4. Tool runs `python -m py_compile` on the modified content (written to a temp file).
   - If compile fails: returns the error to Telegram, deletes pending change, no diff sent.
   - If compile passes: sends the diff to Telegram as a formatted code block with prompt: **"Reply 'approve' or 'reject'."**
5. On "approve": bot reads `data/pending_change.json`, writes the new file content, commits, and pushes to `main`.
6. On "reject": bot deletes `data/pending_change.json` and confirms in Telegram.

### Pending change file schema
```json
{
  "timestamp": "2026-05-14T10:23:00-05:00",
  "file": "processors/query_tools.py",
  "description": "Trim confirmation receipt verbosity",
  "diff": "--- a/processors/query_tools.py\n+++ ...",
  "new_content": "... full file content ..."
}
```

### Constraints
- Only one pending change at a time. If a pending change exists when a new one is proposed, the bot asks the user to approve or reject the existing one first.
- The bot detects "approve" or "reject" by checking whether the entire message content (stripped, lowercased) is exactly `"approve"` or `"reject"`. Partial matches like "I approve" or "yes, reject it" are treated as regular queries, not approvals.
- Commit message is auto-generated: `"bot: <description> [telegram-approved]"`.
- Push target is always `main` (`git push origin main`). No branch creation.

### Risk
Claude can write syntactically valid but semantically wrong Python. The syntax check catches compile errors but not logic errors. The diff review in Telegram is the logic gate — the user must read the diff before approving. This is the intentional design: human eyes on every change before it ships.

---

## Data files introduced

| File | Purpose | Committed to git |
|---|---|---|
| `data/notion_updates_queue.json` | Staged Notion pipeline updates for Cowork | Yes |
| `data/brief_prefs.md` | Freeform brief customization preferences | Yes |
| `data/pending_change.json` | Active pending code change awaiting approval | No (gitignored) |

---

## What is not in scope

- Changes to `cloudflare/telegram-bridge.js` — the Worker is unchanged.
- Changes to GitHub Actions workflows (except as output of an approved Section 4 change).
- Cowork implementation — the queue file format is this spec's contract with Cowork; the Cowork scheduled task itself is configured separately.
- Any Notion MCP integration in the GitHub Actions environment — Cowork handles all Notion writes.
- New authentication or secrets — no new API keys required.
