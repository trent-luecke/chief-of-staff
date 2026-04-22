# P9 — Tool Use & Action Execution

**Date:** 2026-04-22
**Status:** Approved

## Problem

The Telegram bot is read-only with a fixed data fetch strategy. The intent classifier guesses what to pre-fetch before Claude sees the query. There is no write path — pipeline records, projects, people notes, and system config cannot be updated from mobile. Small operational actions (log a note after a call, mark a task done, flag a backlog idea) require being at a laptop.

## Goal

Replace the intent classifier + two-pass fetch with a native Claude tool use loop. Give Claude a defined set of read and write tools. Let it decide what to fetch and what to execute based on the actual query rather than a pre-classification guess. Enable meaningful mobile-first control over all key data stores.

---

## Architecture

### What Changes

The existing `answer_query()` function in `processors/query.py` is replaced by `answer_query_with_tools()`. The intent classifier (`_classify_intent()`) is retired — tools do that job natively. The `captures` JSON response field is removed — captures become `add_capture` tool calls during the loop instead of a parsed field in the final response. `ask.py` is simplified: no more JSON parsing of the answer, no separate capture-processing pass.

### What Stays

Local context (memory, people, projects, captures, pipeline summary) remains pre-loaded in the system prompt. This data is small, always relevant, and cheap to include. Tools handle anything requiring live fetch or a write.

### Loop

```
system_prompt = JARVIS persona + local context
messages = [{"role": "user", "content": query}]

loop (max 10 iterations):
  response = claude(model, tools=all_tools, messages=messages, max_tokens=1000)

  if stop_reason == "end_turn":
    return extract_text(response)

  if stop_reason == "tool_use":
    for each tool_use block:
      result = execute_tool(name, input)   # returns string
      collect as tool_result
    append assistant turn to messages
    append user turn with tool_results to messages
    continue
```

Max iterations is 10. If the loop hits the cap without `end_turn`, the last assistant text is returned as-is with a warning logged.

---

## Tool Set

### Read Tools

| Tool | Inputs | Executes |
|------|--------|----------|
| `search_gmail` | `query: str`, `max_results: int = 5` | `collectors.gmail.fetch_threads_needing_attention()` |
| `get_calendar_events` | `days_ahead: int = 7` | `collectors.calendar.fetch_today_events()` |
| `get_pipeline_lead` | `lead_name: str` | Lookup in `data/pipeline_cache.json`, fuzzy name match |
### Write Tools — Execute Immediately

| Tool | Inputs | Executes |
|------|--------|----------|
| `add_capture` | `capture_type: str`, `text: str` | Appends to `data/captures.md` (types: todo, idea, note, flag) |
| `complete_task` | `description: str` | Removes from `data/captures.md` or marks project next-action done in `data/projects.md` |
| `create_email_draft` | `to: str`, `subject: str`, `body: str` | Pushes to Gmail drafts via `users.drafts.create` API |
| `add_people_note` | `person_name: str`, `note: str` | Appends note with timestamp to matching `data/people/*.md` file |
| `update_project_next_action` | `project_name: str`, `next_action: str` | Updates next-action field in `data/projects.md` |
| `create_project` | `name: str`, `description: str`, `next_action: str` | Appends new project entry to `data/projects.md` |
| `resolve_issue` | `title_fragment: str` | Marks matching issue as resolved in `data/issues.json` |
| `update_config` | `key: str`, `value` | Writes to `config.json` — safe keys only (see below) |
| `add_to_backlog` | `description: str` | Appends item to `BACKLOG.md` under `## 📥 Inbox` section (created if absent) |

### Safe Config Keys

`update_config` accepts only: `memory_budget_tokens`, `max_active_projects`, `issue_auto_resolve_days`, `pipeline.enabled`. Any other key returns an error string to Claude; Claude tells the user it can't make that change and offers to log it to the backlog instead.

### Email Sending

Sending email is never a tool. `create_email_draft` creates a draft only. Claude tells the user to review and send from Gmail.

---

## Error Handling

All tool executor functions catch exceptions and return a descriptive error string. Claude sees the error as `tool_result` content and incorporates it into the answer (e.g., "Couldn't find a lead named X in the pipeline cache — here's what I do have..."). No exceptions propagate out of the tool loop. The loop always reaches `end_turn` or the iteration cap.

---

## Confirmation Model

| Risk level | Behavior |
|-----------|----------|
| Low (add capture, add note, resolve issue, update project) | Execute immediately, report what was done |
| Medium (create project, update config) | Execute immediately, explicitly state what changed |
| High (send email) | Not supported — draft only, user sends manually |

True two-turn confirmation (Claude asks, user replies yes, second Actions run executes) is out of scope. The risk tier is managed by what tools exist, not by a confirm/deny flow.

---

## Data Commitback

Write tools that modify files in `data/` or `BACKLOG.md` or `config.json` rely on the existing GitHub Actions commitback step at the end of `ask.yml`. No changes needed to the commit step — it already commits all modified tracked files.

---

## Absorbs Deferred Items

- **P7 (Push Drafts to Gmail):** `create_email_draft` tool implements `users.drafts.create` — P7 is resolved as a side effect.
- **P8 (Project Intelligence — create project via Telegram):** `create_project` tool covers the natural language project creation use case from P8.

---

## Logging

Each Claude call in the tool loop is logged via `lib/llm_logger.log_usage()` with caller `"query_tool_loop"`. Multiple iterations produce multiple log entries, distinguished by timestamp. Flush happens in the existing `finally` block in `ask.py`.

---

## Files Changed

| File | Change |
|------|--------|
| `processors/query.py` | Replace `_classify_intent` + `answer_query` with `answer_query_with_tools` + tool definitions + tool executor |
| `ask.py` | Remove JSON response parsing and capture post-processing; call `answer_query_with_tools` |
| `BACKLOG.md` | Add `## 📥 Inbox` section; note Notion write access deferred pending API key |
