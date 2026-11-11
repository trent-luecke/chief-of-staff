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
- Feature Requests: `collection://ad23d54a-66ac-4f84-9fde-6c4e317892ea`. Fields: `Request` (title), `Requesting Account` (text), `Amount of Requests` (number), `Completed/Closed?` (checkbox), `Requesting Accounts` (relation → OS Accounts), `Shipped notified` (one-way relation → OS Accounts, the D4a dedupe), `Check-ins` (relation → Check-ins).
- Behavior Gaps: `collection://cd045eb1-489e-4566-924c-52bae236d36c`. **Never write to it and never add a column to it.** `Related Gap` on Check-ins is one-way on purpose.
- Bug Tracker: `collection://29d24bca-36d7-80ef-b574-000b739e37a8`. Read-only here, used for holds.

### Front / HubSpot
- Send-from channel: `cha_30ds1` (trent@teambuildr.com). It auto-appends the closing and signature, so templates have none.
- BCC on every draft: `4238329@bcc.hubspot.com`
- Trent teammate: `tea_2glc1`. Andrea Alamo teammate: `tea_d12je`.
- Owner map (for the Owner field and the Different-sender variant):

| Owner | Front teammate | Channel | Booking link |
| --- | --- | --- | --- |
| Trent Luecke | tea_2glc1 | cha_30ds1 | `https://meetings.hubspot.com/trent-luecke` (HubSpot Meetings) |
| Andrea Alamo | tea_d12je | not set up yet | not set up yet |

Until Andrea's row is filled in, the Different-sender variant drafts on Trent's channel and adds a Front comment: "Different-sender variant: hand to Andrea (tea_d12je) to send."

### Survey forms (set up in Task 6)
- Early (2–6 mo) form pre-fill URL: `https://docs.google.com/forms/d/e/1FAIpQLSc1XEuNpLrQpcUr9QXdv1mkBjsyGhSufj5QgWk8W7e4vwVGyA/viewform?usp=pp_url&entry.1924896125=ACCOUNT` (literal `ACCOUNT` is the Facility/Gym Name field)
- Settled (6–12 mo) form pre-fill URL: `https://docs.google.com/forms/d/e/1FAIpQLSe5lJ8zNsPbWglT7uONE9jBs1dS4HtFNg21GUnDwnjLertcCw/viewform?usp=pp_url&entry.1924896125=ACCOUNT`
- Mature (12+ mo) form pre-fill URL: `https://docs.google.com/forms/d/e/1FAIpQLSdiHPZ9Ru8AwIEHcMNE0-y0hIcwfBeuv1oiK90yzRRXcsntog/viewform?usp=pp_url&entry.1924896125=ACCOUNT`
- Responses spreadsheet: `1g4UJldueeEKytNolqqP-e8YPa6Xwo0ksKbpOiWiithI` ("OS Check-In Responses"; tabs `2-6 mo. Responses`, `6-12 mo. Responses`, `12+ mo. Responses`; the account is column `Facility/Gym Name`)
- Booking meeting name as it appears on HubSpot `MEETING_EVENT`: `TeamBuildr OS Customer Check-In` (HubSpot Meetings link, so bookings create the engagement natively)

**If any `<...>` placeholder above is still unfilled, STOP before drafting and report "config incomplete".**

### Rules CLI
`python3 /Users/trentluecke/dev/Claude-Projects/chief-of-staff/scripts/checkins.py <cmd>` takes one JSON object on stdin and writes JSON to stdout. Exit 2 means bad input: stop that step and report it.
- `due`: who is due this week, with version and variant
- `flags`: score flags
- `latest`: newest survey response
- `fr-link`: Feature Request link and count update
- `match`: free-text → account name

**Never touch Trent's working checkout.** At the start of each run, export the code from `origin/main` into a temp directory and run the CLI from there:
```
R=/Users/trentluecke/dev/Claude-Projects/chief-of-staff
T=$(mktemp -d) && git -C $R fetch origin main -q && git -C $R archive origin/main lib/__init__.py lib/checkins.py lib/account_match.py scripts/checkins.py scripts/checkins_sheet.py lib/google_auth.py | tar -x -C $T
python3 $T/scripts/checkins.py <cmd>
```
Wherever this runbook shows `python3 scripts/checkins.py`, use `python3 $T/scripts/checkins.py`.

**Inputs:** cast scores to integers, and convert dates to ISO `YYYY-MM-DD` before passing them.

Never re-derive these rules in prose. Use the CLI output as-is.

### Program start
`program_start`: `2026-11-09`. This is the first Monday the draft task runs live. Update it if go-live moves. Pass it to every `due` call. Slots that fell before this date are never caught up, which spreads kickoff at about 8 per week instead of everyone in week one.

### Program email subjects (used for exclusion in D2)
- `Quick check-in from TeamBuildr OS`
- `Re: Quick check-in from TeamBuildr OS`
- `Thanks for the feedback`

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
- If Front, HubSpot or Notion is unavailable, or `checkins_sheet.py` exits 2, **STOP** and report it. Never run on partial data.
- **Never read the Client List or the responses sheet with the Google Drive connector.** Its `read_file_content` returns only a sample of rows, so most accounts would be silently skipped. Always use `checkins_sheet.py` (Sheets API, read-only, full tab).
- Never write to the Client List sheet or the Behavior Gaps DB.
- Never create a Feature Request without `Log it` ticked on its check-in row.
- Give-first and Different-sender openers must be **grounded**. Every claim cites a context-packet item. With no grounded angle, insert exactly `[PERSONAL OPENER — no grounded angle found]`.

---

## Draft pass (`os-checkins-draft`, Mondays)

`week_monday` = today if Monday, else the most recent Monday (America/Chicago).

### D1 — Load accounts
1. Run `python3 $T/scripts/checkins_sheet.py accounts` from the same origin/main export as the Rules CLI. It returns every **Active Customers** row as JSON (`count` + `rows`). Use Account Name, Join Date (raw string), POC, Email. Put `count` in the run summary as "Accounts read: <n>". If `count` is under 50, STOP and report: the read is incomplete.
2. Page the OS Accounts Database in view mode and build `{Account Name → page url}`.
3. For each sheet row, run `checkins.py match` with `{"raw": <sheet name>, "accounts": [<OS Accounts names>]}`. A single `matched` result is the account page. Anything else goes in the summary under "not in Notion" and the row gets no draft.
4. If Email is blank, skip the row and list it under "no email".

### D2 — Build holds (per account)
Build the `support` list for the CLI:
- Front `search_conversations` with the POC email, across all inboxes, last 120 days. **Exclude every conversation whose subject is one of the Program email subjects** (Config). The program's own emails must never create a hold. **Also exclude failed-payment threads**: any subject (with or without "Re:"/"Fwd:") that contains "payment" and one of "failed", "declined" or "unsuccessful", in any order and any case (e.g. "Failed OS Payment", "Re: Failed TeamBuildrOS Payment", "Payment declined"). A billing notice is not a support issue and must never hold a check-in.
  - Any **not archived**: `{"open": true}`.
  - Keep each hold's subject and date, so the summary can give the specific reason for every held account.
  - Archived: `{"open": false, "closed_on": <last message date>}`.
- Bug Tracker items related to the account page:
  - Status isn't Done/Closed: `{"open": true}`.
  - Done/Closed and last edited in the last 21 days: `{"open": false, "closed_on": <last edited date>}`, which gives the post-fix cushion.
- Trent's own outbound one-to-one emails to the POC in the last 21 days, excluding check-in drafts and sends: `{"open": false, "closed_on": <sent date>}`.

### D3 — Due list
From the By-account view, collect each account's Check-ins rows:
- `last_checkin_on`: the newest of `Sent`, or the created date for rows still at Drafted or Skipped.
- `prior_outcomes`: Outcome values, oldest to newest.

Run:
```
echo '{"week_monday": "...", "program_start": "<Config program_start>", "accounts": [{"name", "join_date", "email", "last_checkin_on", "support", "prior_outcomes"}]}' | python3 scripts/checkins.py due
```
Use `due` and `skipped` exactly as returned. Two skip reasons go in the summary:
- `held`: under "held — support issue".
- `bad_join_date` / `future_join_date`: under "bad join date". These accounts never get a check-in until the sheet is fixed, so they must be visible.

`too_new`, `recent_checkin` and `not_slot_week` are normal and are not listed.

### D4a — Shipped for them (every variant)
There is no standalone "it's live" email. Feature launches already go out as their own announcement, so the check-in just closes the loop for the gym that asked.

Dedupe lives on the **Feature Request** in `Shipped notified` (relation → OS Accounts), never on a Check-ins row. The Task 5 backfill seeded `Shipped notified` = `Requesting Accounts` for every request already Completed, so only **new** completions show up.

1. `shipped_for_them` = Feature Requests with `Completed/Closed?` true, the account in `Requesting Accounts`, and the account **not** in `Shipped notified`.
2. **Seed guard:** drop any request whose `Shipped notified` is empty *and* whose `Requesting Accounts` has more than 5 accounts. List it under "check: shipped request with no notify history". That's an un-seeded backfill row, not a new ship.
3. If `shipped_for_them` is empty, `{{shipped_line}}` is empty. Otherwise write `{{shipped_line}}` as one or two plain sentences naming at most 2 of them (most recently edited first), e.g. "Also, the custom invoice fields you asked for went live recently." Add one grounded sentence on where to find it only if the Knowledge Hub page or the request's notes say so. Never invent a location.
4. Give-first / Different sender: if D4 picks angle 1 (a shipped request of theirs), that request goes in `{{opener}}` instead and is left out of `{{shipped_line}}`. Never mention the same request twice.

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
1. A shipped request of theirs, from D4a's `shipped_for_them`: "You asked for X, it's live."
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
   - `{{call_link}}`: the owner's booking link.
4. **Front `create_draft`:** a new outbound on `cha_30ds1`, to the POC email, BCC `4238329@bcc.hubspot.com`. Subject and body come from Appendix A for the Variant. Fill `{{first_name}}` from the first word of POC (fallback "there"), `{{facility}}` from the account name, `{{opener}}` from D4 (Give-first/Different sender only), and `{{shipped_line}}` from D4a. When `{{shipped_line}}` is empty, drop its paragraph entirely so no blank line is left.
5. Write the draft's conversation link to `Front link`.
   - **Shipped dedupe:** for every request named in `{{shipped_line}}` or `{{opener}}`, add the account to that request's `Shipped notified`, right after the draft is created. If Trent later deletes the draft (Outcome Skipped), the mention is not retried. That's accepted: the launch announcement already reached them.
6. **Different-sender variant:** also `add_comment` on the conversation: "Different-sender variant (Silent ×2): hand to Andrea (tea_d12je) to send."
7. **Generic email** (`generic_email: true`): still draft, and list it under "generic inbox — check recipient".

### D6 — Nudges
Nudges run in the **log pass** (L3b), not here, so they go out on day 7 whatever weekday the original was sent.

---

## Log pass (`os-checkins-log`, weekdays)

Work through the By-account view (view mode, paged).

### L1 — Sent detection
For each row at **Drafted**, read the Front conversation (`Front link`):
- An outbound message exists: Outcome = **Sent**, `Sent` = that message's date.
- No outbound message and no draft left (Trent deleted it): Outcome = **Skipped**.
- The draft is still unsent 7 or more days after the row was created: list it under "sitting unsent". Change nothing.

### L2 — Responses
**Open rows** are the account's newest row, when it is at Sent, Replied, Call booked or Silent, `Sent` is within the last 60 days, and `Platform score` is empty. A row stays open for surveys even after a reply or a Silent mark, so late answers aren't lost.

For the outcome, a booking beats a survey, which beats a reply. A survey can overwrite Replied, Call booked or Silent.
1. **Booking** (rows at Sent or Silent): HubSpot contact by POC email → `MEETING_EVENT` with title containing `TeamBuildr OS Customer Check-In` and created after `Sent`. Outcome = **Call booked**. If the row was Silent, remove the `Silent` and `Silent ×2` signals.
2. **Survey** (any open row): run `python3 $T/scripts/checkins_sheet.py responses`. It returns every response from all three tabs, each tagged with `version`. **Only consider responses whose Timestamp is in the last 60 days and later than the row's `Response at`, if that's set.** Convert each Forms `Timestamp` (`M/D/YYYY H:MM:SS`) to ISO before use. Match each response's `Facility/Gym Name` value to the row with `checkins.py match` (fallback: respondent email = POC email). Gather all qualifying responses for the row submitted after `Sent`, then run `checkins.py latest`. Write:
   - `Platform score`, `Support score`;
   - `Alongside OS` (the "What do you use alongside…" column), `Change one thing` (the "If you could change one thing…" column);
   - `Version answers`: every other non-empty free-text column (everything except Timestamp, Facility/Gym Name, the two scores, those two, and the call question), as "Q: … A: …". Match columns by header text, never by position, because the three tabs have different column counts;
   - `Response at` = that response's timestamp;
   - Outcome = **Survey answered**. If the row was **Silent**, remove `Silent` and `Silent ×2` from Risk signals.

   If "Want to hop on a call?" = Yes, add "wants a call" to the summary.
3. **Reply** (rows at Sent or Silent): an inbound message after `Sent` on the `Front link` conversation **or** the `Nudge link` conversation. Ignore auto-replies (out-of-office, "automatic reply"). Outcome = **Replied**. If the row was Silent, remove the Silent signals.

If a qualifying response (last 60 days, not yet applied) matches no open row, list it under "unmatched responses". Never guess. A response already applied (its timestamp equals some row's `Response at`) is never listed.

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

### L3b — Nudges
For each row at **Sent** where `Sent` is 7 or more days ago and `Nudged` is empty, draft the Nudge from Appendix A as a new outbound with BCC. Then set `Nudged` = today and `Nudge link` = the nudge's conversation. Never nudge twice.

### L4 — Silent
For each row still at **Sent** where `Sent` is 14 or more days ago **and** `Nudged` is set and 7 or more days ago: Outcome = **Silent**, and add `Silent` to Risk signals. If the account's previous non-Skipped row was also **Silent**, add `Silent ×2` as well.

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


---

## Run summary (both passes)

Send a Slack DM to Trent. If Slack is unavailable, put the same text in the task output.

The Slack tool takes standard markdown, headers included. Format rules:
- First line is a bold title, not a header: `**OS check-ins: <draft|log> pass, <date>**`, then `Accounts read: <n>` on the next line (draft pass only).
- Each section is a `#` header carrying its count, e.g. `# Drafts created: 2`.
- Under **Drafts created** only, add a `###` sub-header for each draft type that has drafts (Standard, Give-first, Different sender, Nudge, Score follow-up), with that type's accounts as bullets underneath.
- **One account per bullet.** Never put two accounts on the same line or in the same paragraph. If one account has several items, give it several bullets.
- Each bullet starts with the account name, then ` - ` and the detail.
- **No IDs**: no Front conversation or draft ids, no Notion page ids, no URLs.
- Drop any section that is empty. If nothing happened, send only the title and "Nothing to do".

Sections, in this order, with the detail each bullet carries:

| Header | Bullet: `<account> - …` |
|---|---|
| `# At risk: <n>` | Silent ×2 |
| `# New flags: <n>` | signal, "exact quote" |
| `# Waiting on you: <n>` | proposed entry (needs "Log it") |
| `# Drafts created: <n>` | `<tenure version> - draft ready in Front` under its `###` type |
| `# Shipped mentions: <n>` | request named in the draft |
| `# Give-first openers: <n>` | angle, cited items, or PLACEHOLDER |
| `# Held: <n>` | the specific reason, e.g. `open support conversation "<subject>" (last activity <date>)`, `support conversation "<subject>" closed <date>, held until <date + 21 days>`, `open Bug Tracker item "<title>"` |
| `# Sitting unsent: <n>` | drafted <date> |
| `# Wants a call: <n>` | from survey |
| `# Check: <n>` | check type and detail, e.g. `generic inbox - draft goes to <email>, check recipient`, `not in Notion - <why>`, `no email`, `bad join date - "<raw value>"`, `unmatched survey response`, `shipped request with no notify history - <request>` |

End with one plain line: `Avoma: ok` or `Avoma: skipped`.

Example (made-up accounts):

```
**OS check-ins: draft pass, 2026-11-10**
Accounts read: 100

# Drafts created: 2
### Standard
- Example Barbell Club - Mature - draft ready in Front
- Sample Athletic Lab - Settled - draft ready in Front

# Held: 1
- Demo Strength Co - support conversation "Billing question" closed 2026-11-10, held until 2026-12-01

# Check: 1
- Example Barbell Club - generic inbox - draft goes to a shared info@ address, check recipient

Avoma: skipped
```

---

## Appendix A — Email copy (APPROVED by Trent 2026-11-03)

These are plain, short, and from Trent. Channel `cha_30ds1` appends the closing and signature, so there's no sign-off. Avoid em dashes in the body.

**Subject (all check-in variants):** `Quick check-in from TeamBuildr OS`

**Standard**
> Hi {{first_name}},
>
> I'm checking in with every gym on OS this quarter, and I'd love to hear how things are going at {{facility}}. What's working, what isn't, and what you wish OS did.
>
> {{shipped_line}}
>
> Two easy ways to share:
> - Grab 15 or 30 minutes with me: {{call_link}}
> - No time? A few quick questions, about 2 minutes: {{survey_link}}
>
> Honest answers help us most, good or bad.

**Give-first**
> Hi {{first_name}},
>
> {{opener}}
>
> {{shipped_line}}
>
> If it's useful, I'm always happy to hop on a quick call ({{call_link}}). Or if you have 2 minutes, a few quick questions here tell us where to focus next: {{survey_link}}

**Different sender** (written for Andrea to send. Until her row is set up, Trent forwards it.)
> Hi {{first_name}},
>
> I'm Andrea on the TeamBuildr OS team. {{opener}}
>
> {{shipped_line}}
>
> I'd love to hear how OS is fitting at {{facility}}. 20 minutes here if you're open to it: {{call_link}}. Or 2 minutes here: {{survey_link}}

**Nudge** (subject `Re: Quick check-in from TeamBuildr OS`)
> Hi {{first_name}}, bumping this in case it got buried. If a call isn't in the cards, the 2-minute version is here: {{survey_link}}

**Score follow-up** (subject `Thanks for the feedback`)
> Hi {{first_name}},
>
> Thanks for filling that out. I noticed {{low_area}} scored lower than I'd like{{their_words}}. I want to understand what happened and get it fixed. Could we grab 15 or 30 minutes {{call_link}}, or just reply here with what's been getting in the way?

`{{low_area}}` is "the platform" or "our support". `{{their_words}}` is ", and you mentioned \"<their phrase>\"" when their free text explains it, otherwise empty.

`{{shipped_line}}` comes from D4a. It is empty for most accounts, and its paragraph is dropped when empty.
