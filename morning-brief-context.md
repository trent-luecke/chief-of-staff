# Morning Brief Context

Notes from the planning session — constraints, what's working, and key design decisions.

---

## What We Built Already

- Notion Inbox database (in TeamBuildr workspace) with Type, Urgency, Category, Source fields
- Zapier webhook → Claude classification → Notion Inbox pipeline (working)
- Apple Shortcut for quick capture (working, uses Dictionary method for JSON body)
- Command Center page in Notion

---

## Constraints Discovered

- No admin access to TeamBuildr Notion — can't create internal integrations
- No Front API token — can't create one, not admin
- Slack Zapier integration has permission issues (`im:history` scope blocked)
- Slack Workflow Builder has no webhook/HTTP step available
- Can't create Slack channels — no permission
- Zapier Code step has 1-second timeout — too short for API calls
- Zapier AI Actions SDK is deprecated, replaced by Zapier MCP

---

## What Works

- `gws` CLI for Gmail (work + personal profiles)
- `gws` CLI for Google Calendar
- Anthropic API
- Zapier webhook for quick captures (open to pivoting to a different tool for this)
- Apple Shortcut capture flow

---

## Key Design Decisions

- Don't want to manage a task system — want an AI that manages it
- Open loops auto-resolve by diffing state, not manual check-offs
- Projects tracked in a markdown file, not Notion
- Recurring tasks in a config file with schedule rules
- Dashboard is local or deployed — could be read-only or interactive; still unsettled on what the primary "interface" should be
