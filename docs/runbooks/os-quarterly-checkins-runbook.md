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

### Notion read budget (IMPORTANT)
The workspace has a **limited SQL / rows-mode `query-data-sources` allowance**. It ran out on 2026-11-02 while 65 Feature Requests and 100 accounts were being pulled. **All routine reads must use view mode** (`mode: "view"` with a view URL), which has no quota, and must page with `next_cursor`.
- **Check-ins:** By account view `view://40c24bca-36d7-81a9-912c-000cc4ce5164`.
- **OS Accounts and Feature Requests:** use a view URL from `notion-fetch` of the database.
- Use SQL only as a last resort, at most once per run. If you hit `usage_limit_reached`, stop that step and report it. Never retry in a loop.

---

## HARD RULES
- **DRAFT ONLY.** Never send, and never call a send tool. Trent reviews and sends every email himself.
- Every draft is a **new outbound** on channel `cha_30ds1` with BCC `4238329@bcc.hubspot.com`. Never a reply draft, because reply drafts silently drop the BCC.
- If Front, HubSpot, Google Drive or Notion is unavailable, **STOP** and report it. Never run on partial data.
- Never write to the Client List sheet or the Behavior Gaps DB.
- Never create a Feature Request without `Log it` ticked on its check-in row.
- Give-first and Different-sender openers must be **grounded**. Every claim cites a context-packet item. With no grounded angle, insert exactly `[PERSONAL OPENER — no grounded angle found]`.

---

## Draft pass (`os-checkins-draft`, Mondays)

`week_monday` = today if Monday, else the most recent Monday (America/Chicago).

### D1 — Load accounts
1. Google Drive `read_file_content` on the Client List sheet. Take the **Active Customers** rows: Account Name, Join Date (raw string), POC, Email.
2. Page the OS Accounts Database in view mode and build `{Account Name → page url}`.
3. For each sheet row, run `checkins.py match` with `{"raw": <sheet name>, "accounts": [<OS Accounts names>]}`. A single `matched` result is the account page. Anything else goes in the summary under "not in Notion" and the row gets no draft.
4. If Email is blank, skip the row and list it under "no email".

### D2 — Build holds (per account)
Build the `support` list for the CLI:
- Front `search_conversations` with the POC email, across all inboxes, last 120 days. Exclude conversations whose subject starts with the check-in subject (Appendix A).
  - Any **not archived**: `{"open": true}`.
  - Archived: `{"open": false, "closed_on": <last message date>}`.
- Bug Tracker items related to the account page with a status that isn't Done/Closed: `{"open": true}`.
- Trent's own outbound one-to-one emails to the POC in the last 21 days, excluding check-in drafts and sends: `{"open": false, "closed_on": <sent date>}`.

### D3 — Due list
From the By-account view, collect each account's Check-ins rows:
- `last_checkin_on`: the newest of `Sent`, or the created date for rows still at Drafted or Skipped.
- `prior_outcomes`: Outcome values, oldest to newest.

Run:
```
echo '{"week_monday": "...", "accounts": [{"name", "join_date", "email", "last_checkin_on", "support", "prior_outcomes"}]}' | python3 scripts/checkins.py due
```
Use `due` and `skipped` exactly as returned. Every `skipped` with reason `held` goes in the summary under "held — support issue".

### D4 — Context packet (Give-first and Different-sender only)
Gather, for that account:
1. **Their requests:** Feature Requests where `Requesting Accounts` contains the account. Split into shipped (`Completed/Closed?` true) and open.
2. **Their history:**
   - Front support conversations from the last 12 months: subjects plus a one-line gist.
   - Bug Tracker items linked to the account.
   - Prior Check-ins rows: scores, "Change one thing", "Alongside OS", Risk signals.
3. **What shipped:** Feature Requests completed in the last 120 days (any account), and Knowledge Hub pages edited in the last 120 days (`notion-search` "TeamBuildr OS Knowledge Hub").
4. **Their calls (best-effort):** Avoma meetings with the POC email. If Avoma is unreachable, note "Avoma: skipped" and continue.

Pick ONE angle, in this order:
1. A shipped request of theirs: "You asked for X, it's live."
2. A shipped fix or feature that addresses a problem they actually had.
3. A concrete idea to get more out of their account, grounded in their history.
4. A future-project invite: an open Feature Request that fits them. "We're thinking about building X — would you be open to a quick chat about it?"

Write `{{opener}}` as 1–2 sentences. Record the cited packet items for the summary.

### D5 — Create the draft
For each `due` account, in order:
1. **Idempotency:** if the account already has a Check-ins row at Drafted or later created in the last 70 days, skip it.
2. **Create the Check-ins row:**

   | Field | Value |
   | --- | --- |
   | Check-in | `<Account> — <Quarter>` |
   | Account | the account page |
   | Quarter | the calendar quarter label; add the option if missing (see Quarter rollover) |
   | Version | from the CLI |
   | Variant | from the CLI |
   | Owner | Trent |
   | Outcome | Drafted |
   | Follow-up | None needed |

3. **Build the links:**
   - `{{survey_link}}`: the version's pre-fill URL, with `ACCOUNT` replaced by the URL-encoded **OS Accounts** name.
   - `{{call_link}}`: the owner's Calendly URL.
4. **Front `create_draft`:** a new outbound on `cha_30ds1`, to the POC email, BCC `4238329@bcc.hubspot.com`. Subject and body come from Appendix A for the Variant. Fill `{{first_name}}` from the first word of POC (fallback "there"), `{{facility}}` from the account name, and `{{opener}}` from D4 (Give-first/Different sender only).
5. Write the draft's conversation link to `Front link`.
6. **Different-sender variant:** also `add_comment` on the conversation: "Different-sender variant (Silent ×2): hand to Andrea (tea_d12je) to send."
7. **Generic email** (`generic_email: true`): still draft, and list it under "generic inbox — check recipient".

### D6 — Nudges
For each Check-ins row at **Sent** where Sent is 7 or more days ago, Nudged is empty, and there's no response yet (Outcome is still Sent): draft the Nudge from Appendix A as a new outbound with BCC, then set `Nudged` = today. Never nudge twice.

---

## Log pass (`os-checkins-log`, weekdays)

Work through the By-account view (view mode, paged).

### L1 — Sent detection
For each row at **Drafted**, read the Front conversation (`Front link`):
- An outbound message exists: Outcome = **Sent**, `Sent` = that message's date.
- No outbound message and no draft left (Trent deleted it): Outcome = **Skipped**.
- The draft is still unsent 7 or more days after the row was created: list it under "sitting unsent". Change nothing.

### L2 — Responses
Check rows at **Sent** in this order. The first hit wins: a booking beats a survey, which beats a reply.
1. **Booking:** HubSpot contact by POC email → `MEETING_EVENT` with title containing `<CHECKIN_EVENT_TITLE>` and created after `Sent`. Outcome = **Call booked**.
2. **Survey:** Google Drive `read_file_content` on the responses sheet. Match each response's `Account` value to the row with `checkins.py match` (fallback: respondent email = POC email). Gather all responses for the row submitted after `Sent`, then run `checkins.py latest`. Write:
   - `Platform score`, `Support score`;
   - `Alongside OS` (core Q3), `Change one thing` (core Q4);
   - `Version answers`: the two version questions, as "Q: … A: …";
   - Outcome = **Survey answered**.

   If "Want to hop on a call?" = Yes, add "wants a call" to the summary.
3. **Reply:** an inbound message on the Front conversation after `Sent`. Outcome = **Replied**.

If a survey response matches no row, list it under "unmatched responses". Never guess.

### L3 — Flags (rows that got a survey this pass)
1. **Scores:**
   ```
   echo '{"current": {"platform", "support"}, "history": [<prior rows with scores, oldest→newest>]}' | python3 scripts/checkins.py flags
   ```
   Add each returned flag to Risk signals. If any flag comes back:
   - build the D4 context packet;
   - draft a personal reply (Appendix A "Score follow-up") as a new outbound with BCC, naming the specific area they rated low;
   - `add_comment` the packet summary on the conversation;
   - set Follow-up = **Drafted**.
2. **Free text** (`Alongside OS`, `Change one thing`, `Version answers`):
   - **Competitor tool:** names another gym or coaching platform (e.g. Mindbody, PushPress, Wodify, Kilo, Glofox, Exercise.com, Trainerize, TrueCoach, Momence, Arbox).
   - **Workaround:** exports, spreadsheets, or another tool doing a job OS should do.
   - **Built own:** a homemade, coded, or AI-built tool.

   Quote the exact phrase in the summary. For Workaround or Built own, write proposed wording into `Proposed entry`: "Feature Request: <title> — <one line>" or "Gap: <title> — <one line>" (a Gap if OS has the feature but it behaves inconsistently).
3. Never re-add a signal already on the row.

### L4 — Silent
For each row still at **Sent** where `Sent` is 14 or more days ago: Outcome = **Silent**, and add `Silent` to Risk signals. If the account's previous non-Skipped row was also **Silent**, add `Silent ×2` as well.

### L5 — Confirmed entries
For each row with `Log it` ticked and `Related Feature Request` empty:
1. Look for an open Feature Request whose title matches the proposed one (`notion-search` within Feature Requests). If none fits, create one with `Request` = the proposed title, `Completed/Closed?` false, and `Amount of Requests` 0.
2. Run:
   ```
   echo '{"linked": [<current Requesting Accounts names>], "text": "<Requesting Account>", "count": <Amount of Requests>, "account": "<OS Accounts name>"}' | python3 scripts/checkins.py fr-link
   ```
   If `changed`, write the account into `Requesting Accounts`, plus the returned `text` → `Requesting Account` and `count` → `Amount of Requests`.
3. Set the row's `Related Feature Request` to that request.

For `Related Gap`, Trent pastes it by hand. Nothing to do.

### L6 — Shipped requests ("you asked, it's live")
For each Feature Request with `Completed/Closed?` true and a non-empty `Requesting Accounts`:
1. For each **active** account in it, check its newest Check-ins row. If `Call notes` does not already contain `notified-shipped: <request url>`, continue.
2. Draft Appendix A "You asked, it's live" as a new outbound with BCC.
3. Append `notified-shipped: <request url>` to that row's `Call notes` and set Follow-up = **Drafted**.

---

## Run summary (both passes)

Send a Slack DM to Trent. If Slack is unavailable, put the same block in the task output.

```
OS check-ins — <draft|log> pass, <date>
At risk (Silent ×2): <accounts>
New flags: <account — signal — "quote">
Waiting on you ("Log it"): <account — proposed entry>
Drafts created: <n> (Standard <n> · Give-first <n> · Different sender <n> · Nudge <n> · Score follow-up <n> · It's live <n>)
Give-first openers: <account — angle — cited items | PLACEHOLDER>
Held (support issue): <accounts>
Sitting unsent: <accounts>
Wants a call (from survey): <accounts>
Check: generic inboxes <…> · not in Notion <…> · no email <…> · unmatched responses <…> · Avoma <ok|skipped>
```
If a section is empty, drop it. If nothing happened, say "Nothing to do".

---

## Appendix A — Email copy (DRAFT: Trent must approve before the first supervised run)

These are plain, short, and from Trent. Channel `cha_30ds1` appends the closing and signature, so there's no sign-off. Avoid em dashes in the body.

**Subject (all check-in variants):** `Quick check-in from TeamBuildr OS`

**Standard**
> Hi {{first_name}},
>
> I'm checking in with every gym on OS this quarter, and I'd love to hear how things are going at {{facility}}. What's working, what isn't, and what you wish OS did.
>
> Two easy ways to share:
> - Grab 20 minutes with me: {{call_link}}
> - No time? 6 quick questions, about 2 minutes: {{survey_link}}
>
> Honest answers help us most, good or bad.

**Give-first**
> Hi {{first_name}},
>
> {{opener}}
>
> If it's useful, I'm always happy to hop on a quick call ({{call_link}}). Or if you have 2 minutes, these 6 questions tell us where to focus next: {{survey_link}}

**Different sender** (written for Andrea to send. Until her row is set up, Trent forwards it.)
> Hi {{first_name}},
>
> I'm Andrea on the TeamBuildr OS team. {{opener}}
>
> I'd love to hear how OS is fitting at {{facility}}. 20 minutes here if you're open to it: {{call_link}}. Or 2 minutes here: {{survey_link}}

**Nudge** (subject `Re: Quick check-in from TeamBuildr OS`)
> Hi {{first_name}}, bumping this in case it got buried. If a call isn't in the cards, the 2-minute version is here: {{survey_link}}

**Score follow-up** (subject `Thanks for the feedback`)
> Hi {{first_name}},
>
> Thanks for filling that out. I noticed {{low_area}} scored lower than I'd like{{their_words}}. I want to understand what happened and get it fixed. Could we grab 15 minutes ({{call_link}}), or just reply here with what's been getting in the way?

`{{low_area}}` is "the platform" or "our support". `{{their_words}}` is ", and you mentioned \"<their phrase>\"" when their free text explains it, otherwise empty.

**You asked, it's live** (subject `You asked for this one`)
> Hi {{first_name}},
>
> A while back you asked for {{request}}. It's live now. {{one_line_how}}
>
> Thanks for pushing us on it. If anything about how it works doesn't fit how {{facility}} runs, tell me.

`{{one_line_how}}` is one grounded sentence about where to find it. Source: the Knowledge Hub page or the request's notes. If there's none, leave it out.
