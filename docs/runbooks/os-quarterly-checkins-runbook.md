# OS Quarterly Check-ins — Runbook

Version-controlled source of the `os-checkins-draft` (weekly) and `os-checkins-log` (weekdays) claude.ai scheduled tasks. Draft-only: it never sends. Any behavior change = edit this file on `main`; the task prompts fetch it from `origin/main` each run.

Spec: `docs/superpowers/specs/2026-11-02-os-quarterly-checkins-design.md`. Plan: `docs/superpowers/plans/2026-11-02-os-quarterly-checkins.md`.

## Config

### Accounts
- Client List sheet: `1Rxk54_u3w0Llm78Yqv8e2BaKG9ddG4UzTMEvaTCmgzs`, tab **Active Customers** (Account Name, Join Date, POC, Email, Phone, Status, Price Point, Length of Engagement). READ ONLY. Never write to this sheet.
- OS Accounts Database: `collection://3d124bca-36d7-8069-a2fa-000b83deae3d` (Account Name, Join Date, Status, `TeamBuildr OS 🪲 Tracker` relation, `Check-ins` and `Feature Requests` back-relations).

### Notion
- 🔁 OS Check-ins database: `522a80535342453789d4564ca28acaa7`, data source `collection://73b2f83a-ad40-4514-bde4-eee179d8bf69` (under OS Customer Success).
  - Views:
    - Needs attention: `view://40c24bca-36d7-8127-b9f5-000cafb08bed`
    - This quarter: `view://40c24bca-36d7-819e-a24d-000c15899e2e` (filtered to one Quarter value; see Quarter rollover)
    - At risk: `view://40c24bca-36d7-818f-ad2a-000cf761c1be`
    - By account: `view://40c24bca-36d7-81a9-912c-000cc4ce5164`
- Feature Requests: `collection://ad23d54a-66ac-4f84-9fde-6c4e317892ea`. Fields: `Request` (title), `Requesting Account` (text), `Amount of Requests` (number), `Completed/Closed?` (checkbox), `Requesting Accounts` (relation → OS Accounts), `Check-ins` (relation → Check-ins).
- Behavior Gaps: `collection://cd045eb1-489e-4566-924c-52bae236d36c`. **Never write to it and never add a column to it.** `Related Gap` on Check-ins is one-way on purpose.
- Bug Tracker: `collection://29d24bca-36d7-80ef-b574-000b739e37a8`. Read-only here, used for holds.

### Front / HubSpot
- Send-from channel: `cha_30ds1` (trent@teambuildr.com). It auto-appends the closing and signature, so templates have none.
- BCC on every draft: `4238329@bcc.hubspot.com`
- Trent teammate: `tea_2glc1`. Andrea Alamo teammate: `tea_d12je`.
- Owner map (for the Owner field and the Different-sender variant):

| Owner | Front teammate | Channel | Calendly |
| --- | --- | --- | --- |
| Trent Luecke | tea_2glc1 | cha_30ds1 | `<CHECKIN_CALENDLY_URL>` |
| Andrea Alamo | tea_d12je | not set up yet | not set up yet |

Until Andrea's row is filled in, the Different-sender variant drafts on Trent's channel and adds a Front comment: "Different-sender variant: hand to Andrea (tea_d12je) to send."

### Survey forms (set up in Task 6)
- Early form pre-fill URL: `<EARLY_FORM_PREFILL_URL>` (contains literal `ACCOUNT`)
- Settled form pre-fill URL: `<SETTLED_FORM_PREFILL_URL>`
- Mature form pre-fill URL: `<MATURE_FORM_PREFILL_URL>`
- Responses spreadsheet: `<RESPONSES_SHEET_ID>`
- Calendly event title as it appears on HubSpot `MEETING_EVENT`: `<CHECKIN_EVENT_TITLE>`

**If any `<...>` placeholder above is still unfilled, STOP before drafting and report "config incomplete".**

### Rules CLI
`python3 /Users/trentluecke/dev/Claude-Projects/chief-of-staff/scripts/checkins.py <cmd>` takes one JSON object on stdin and writes JSON to stdout. Exit 2 means bad input: stop that step and report it.
- `due`: who is due this week, with version and variant
- `flags`: score flags
- `latest`: newest survey response
- `fr-link`: Feature Request link and count update
- `match`: free-text → account name

Run it from the repo checkout. `git -C <repo> fetch origin main -q && git -C <repo> checkout -q origin/main -- lib/checkins.py lib/account_match.py scripts/checkins.py` first, so the code matches this runbook.

Never re-derive these rules in prose. Use the CLI output as-is.

### Quarter rollover
- **Quarter label:** the calendar quarter of the draft date ("2027 Q1"). If the label doesn't exist yet as a `Quarter` option, add it (`notion-update-data-source` ALTER COLUMN with all existing options plus the new one).
- **This quarter view:** on the first run of a new quarter, update the view's filter to the new label.
