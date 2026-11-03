# OS Quarterly Check-ins: Design

**Date:** 2026-11-02
**Status:** Draft, awaiting Trent's review
**Owner:** Trent Luecke (kickoff). Later shared with Andrea Alamo (CSM).

## Problem

OS cancellations arrive out of the blue. The usual pattern is a cancellation email after months of silence, or after one or two harmless questions over the previous six months. Looking back, there is no signal anywhere: no ticket trend, no slowdown in replies, nothing Trent could have watched. The stated reasons are almost always one of two:

1. Moving to a competitor platform.
2. Replacing OS with something they built themselves (vibe-coded).

Both are slow decisions. Nobody evaluates a competitor or builds their own tool in a weekend. In the weeks before, the customer is working around a gap. Right now nobody asks, so nobody sees it.

There is no CS team. Sales (Trent) owns post-sale, and Andrea is a new CSM hire who will share the load later. Most of the base is small (~$200/mo) and there are a lot of accounts, so any program has to be cheap per account and mostly run itself.

## Goal

Create a regular, deliberate touchpoint with **every active OS account, every quarter**, so that churn risk shows up months before a cancellation email. Each check-in offers the customer two ways to respond:

- **A call** for customers who want one. Cover new features, take feedback and requests, and answer questions.
- **A short survey** for customers who don't want a call. Ask about pain points, their experience with the platform and support, and especially **what they use alongside OS or work around**.

Every check-in ends in a recorded outcome. **Silence is recorded as a signal**, not dropped.

Secondary goal: every request or workaround heard is logged against the account that raised it, so that when it ships Trent can tell that customer ("you asked, it's live").

## Non-goals

- **Not a formal business review.** No metrics decks and no usage reports. OS has no product-usage data to show (see Constraints).
- **Not upselling.** Expansion might come up, but it is not a goal and the copy must not read like a pitch.
- **No auto-send.** The routine drafts and Trent sends. This is the same contract as the trial-outreach autopilot.
- **No repeated chasing.** One follow-up nudge per quarter at most. Never a third ask in the same quarter.
- **Not Strength.** OS accounts only.
- **Not a replacement for Layer 1.** Buyer's-story interviews (day 14–30 after signing) stay as they are.

## Anti-goals (failure even if it technically works)

- Customers feel nagged. Asking more often or more insistently is explicitly what Trent does not want.
- A survey that measures "are you happy?" and gets polite 9s right up until cancellation. The questions must surface workarounds and alternatives.
- A dashboard nobody looks at. Flags must turn into a specific next action with a draft ready, not just a red cell.
- Trent buried under 100 check-ins in one week.

## Constraints and facts (verified 2026-11-02)

- **Account list and contacts:** the TeamBuildr OS Client List sheet (`1Rxk54_u3w0Llm78Yqv8e2BaKG9ddG4UzTMEvaTCmgzs`), **Active Customers** tab. Columns: Account Name, Join Date, POC, Email, Phone, Status, Price Point, Length of Engagement (tenure in months, formula-driven). This tab is formula output. **Read only, never write to it** (see memory note on the sheet). Some emails are generic inboxes (`info@`, `admin@`, `contact@`). Drafts go to whatever the sheet lists, and the run summary flags generic addresses so Trent can decide.
- **The sheet already has an informal outreach log:** All OS Customers has "Marketing Connect – Need Help reach out" and "Any communication" columns, with entries from 10/8–10/9. This program does not write to those columns. The builder should mention them to Trent as possible prior context, not reuse them.
- **Canonical account records in Notion:** OS Accounts Database (`collection://3d124bca-36d7-8069-a2fa-000b83deae3d`). Fields are Account Name, Join Date, Status, and a Bug Tracker relation. It is mirrored daily from the sheet by the `os-accounts-notion-mirror` task. It has no contact fields.
- **Account-age spread (105 active as of 2026-11-02):** 26 at 0–6 months, 28 at 6–12, 28 at 12–24, 23 at 24+. Even spread. At 105 accounts over 13 weeks, that's about 8 per week.
- **No product-usage data** exists anywhere in the stack (OS-Metric-Sync has none). Never target or score accounts on usage.
- **Front and HubSpot connectors are interactive-auth claude.ai connectors.** Anything that drafts in Front must run as an in-app claude.ai scheduled task, not in GitHub Actions. This is the same reason trial outreach runs that way.
- **Behavior Gaps DB** (`cd045eb1-489e-4566-924c-52bae236d36c`): Trent deliberately removed its "Related Customers" column. **Do not add any column to the Gaps DB**, including the reverse side of a relation. Gaps entries follow his conventions ("Verified Against" a gymstudio commit, etc.), so the routine never creates Gaps entries itself.
- **Feature Requests DB** (`collection://ad23d54a-66ac-4f84-9fde-6c4e317892ea`): "Requesting Account" is free text and "Amount of Requests" is a number typed by hand. Nothing links requests to accounts reliably today.

## Decided (by Trent in conversation)

1. **Layers 2 and 3 merge** into one program covering every active OS account. Each check-in offers a call or a survey.
2. **Purpose is early churn detection.** Feedback for the roadmap is secondary.
3. **Quarterly cadence** per account.
4. **Draft-and-review delivery, like the trial-outreach autopilot.** The system drafts a personal email from Trent in Front, Trent reviews and sends, and the system tracks the outcome.
5. **Survey versions by account age.** On top of pain points, ask general questions about experience with the platform and the support team.
6. **Workarounds get logged** to Behavior Gaps (OS behaves inconsistently) or Feature Requests (OS doesn't do it yet), depending on what the workaround is.
7. **Response playbook for flags** (proposed by Claude, accepted by Trent):
   - Workaround mentioned → log it (see #6).
   - Score drop → a fast, specific, personal reply to the exact thing they rated low. No new survey.
   - Silent → don't re-ask. The next touch gives something instead (a relevant feature note, or "you asked for X, it's live").
   - Silent two quarters in a row → mark at-risk, and the next reach-out comes from a different person (Andrea, or whoever onboarded them).
8. **Trent runs it at kickoff, and Andrea joins later as a tag team.** The design must allow a per-account owner from day one, even though every account starts as Trent's.
9. **Hold check-ins during an open support problem**, until it's sorted plus a 2–3 week cushion.
10. **Give-first emails need in-depth per-account context.** The angle can be features shipped, past issues, ideas to get more out of their account, or an open Feature Request offered as an invite to chat about a future project.
11. **Feature Requests get linked to real accounts.** That means a backfill plus ongoing writes, and the routine updates Requesting Account and Amount of Requests.

## How it works

### 1. Who and when

- **Population:** every row on the Active Customers tab.
- **Grace period (Claude's call):** an account becomes eligible once its tenure is 2 months or more. The first 60 days are onboarding (matches the 60-day onboarding window used in the account-health work), and Layer 1 buyer's-story interviews cover day 14–30.
- **Check-in week (Claude's call):** each account's slot within the 13-week quarter is fixed and derived from its Join Date:
  `slot = (days since Join Date ÷ 7) mod 13`, and the account is due in the week where its slot comes up. *(Build note: an account whose slot was missed, for example because it was held, catches up once the hold clears. Slots before the program's start date are never caught up, so kickoff doesn't flood week one.)*
  This spreads accounts evenly, needs no stored schedule, and stays stable over time. The routine also checks the log: if an account already has a check-in sent in the last 70 days, skip it. That handles edge cases like newly eligible accounts and manual sends.
- **Weekly volume:** about 8 drafts per week at today's account count.
- **Hold during support issues (Trent's call):** don't send a check-in while the account has an open support problem. Hold it until the problem is sorted, plus a **2–3 week cushion**.
  - **Detecting a problem:** search Front for conversations with the account's POC email (or the account name) that are not archived. Also check the OS Accounts DB Bug Tracker relation for open bugs.
  - **Releasing the hold:** the hold clears **21 days** after the last such conversation is archived or the bug is resolved. *(21 days, the specific Front recipe, and including open bugs are Claude's calls.)*
  - **Where held accounts go:** a held account moves to the first week after its hold clears, and is listed in the summary as "held — support issue".
- **Recent direct contact (Claude's call):** if Trent sent the POC a one-to-one email in the last 21 days, push the check-in back by the same rule. The Oct 8–9 "Marketing Connect" round is older than 21 days and needs no special handling.

### 2. Survey versions

Three versions, chosen by tenure at send time. The **core questions are identical in every version** so answers can be compared quarter over quarter.

**Core (every version):**
1. How would you rate OS overall? (1–10)
2. How would you rate our support team? (1–10)
3. What do you use alongside OS to run your gym, or keep track of outside of it? (free text)
4. If you could change one thing about OS tomorrow, what would it be? (free text)

**Early accounts (2–6 months):**
- Is there anything you set out to do in OS that you still haven't gotten set up?
- Has anything confused you or your members?

**Settled accounts (6–12 months):**
- What do you wish OS did that it doesn't today?
- Is there anything you export out of OS into a spreadsheet or another tool?

**Mature accounts (12+ months, includes 24+):**
- Have you looked at any other platforms recently? What caught your eye?
- Have you built, or thought about building, any of your own tools to fill gaps?

Plus an optional last question in every version: "Want to hop on a quick call? (Yes/No)". It catches survey responders who'd also take a call.

Keep the survey to 6–7 questions and under 2 minutes. Wording is a draft for Trent to edit. The structure (identical core + 2 age-specific questions) is what's decided.

### 3. Survey tool (Claude's call: Google Forms)

- **Why:** free, Trent already has Google Workspace, and responses land in a Google Sheet that the routine can read through the existing Google Drive connector. A pre-filled link lets each email carry the account name, so responses join to the account without the customer typing anything.
- **Setup:** one Form per version (3 Forms), each with a hidden or pre-filled "Account" field. All three send responses to one Responses spreadsheet, using one tab per form or a version column.
- Trent creates the forms by hand, or the builder walks him through it. The routine only reads responses.
- **Trade-off named:** Typeform or Tally look nicer and handle hidden fields more cleanly, but each would add a new account and connector. Revisit if response rates are poor.

### 4. Booking a call

- A new Calendly event type, "OS Check-in, 20 min", on Trent's Calendly. Trent creates it.
- Bookings reach HubSpot the same way demo bookings do. The routine detects a booking by looking up HubSpot `MEETING_EVENT` for the contact, the same recipe as the trial-outreach demo check, filtered by the check-in event title.
- Once Andrea joins, she gets her own event type, and the email uses the account owner's link.

### 5. The email (draft in Front)

- Drafted on Trent's channel (`cha_30ds1`) to the account's POC email, as a **new outbound** with BCC to HubSpot `4238329@bcc.hubspot.com`. (Lesson from trial outreach: reply drafts silently drop the BCC.)
- Short and personal, from Trent. Two clear options: "Grab 20 minutes with me" (Calendly link) or "No time? 6 quick questions, 2 minutes" (pre-filled Form link for the account's version).
- The copy changes by context:
  - **Standard:** the default check-in.
  - **Give-first (after a silent quarter):** opens with something genuinely useful *to this specific account*. The call/survey options are still offered softly at the end, but asking is not the point. Trent's direction: this needs in-depth, per-account context. Before drafting, the routine builds an **account context packet** from:
    - **Their requests:** Feature Requests linked to the account, both shipped ("you asked for X, it's live") and still open.
    - **Their history:** past Front support conversations and the OS Accounts DB Bug Tracker relation (what they've struggled with), plus prior check-in rows (scores, "change one thing", workarounds).
    - **What's shipped:** recent OS features. The source is completed Feature Requests plus the Notion sales Knowledge Hub. *(Claude's call. The Hub is kept current per [[project_os_knowledge_hub_refresh]].)*
    - **Their calls:** Avoma calls with the account, if any (buyer's story, onboarding, past check-ins).

    From the packet, the routine picks **one** angle, in this order of preference:
    1. A shipped request of theirs.
    2. A fix or feature that addresses a problem they actually had.
    3. A concrete idea to get more out of their account, grounded in their history.
    4. **A future-project invite:** an open Feature Request that fits them, offered as "we're thinking about building X — would you be open to a quick chat about it?" This turns them from a survey target into a design partner.

    **Grounding rule:** every claim in the opener must trace to a packet item, cited in the run summary. If the packet is too thin to support a specific angle, the routine leaves a marked `[PERSONAL OPENER — no grounded angle found]` placeholder for Trent instead of inventing one. The same packet is attached as a Front comment on every Low-score / Score-drop reply draft.
  - **Different sender (after two silent quarters):** drafted for the alternate owner (Andrea). Until Andrea is set up in the flow, this is drafted for Trent to forward or hand off. Builder: confirm Andrea's Front teammate ID (`tea_d12je` in the trial-outreach owner map).
- Template copy is Trent's to write and approve. The builder drafts it in the runbook appendix, as was done for trial outreach.
- **Follow-up nudge:** if there's no response 7 days after the send, draft one short nudge, once. No more after that. *(Build note: nudges run in the weekday log pass so they land on day 7, and replies to the nudge's own conversation count.)*
- **Silent:** no response 14 days after the original send, **and** at least 7 days after the nudge (call booked, survey submitted, or email reply all count as responses). The check-in is then marked Silent. A late survey or booking upgrades a Silent row.

### 6. The check-in log (new Notion DB)

**"🔁 OS Check-ins"**, under TeamBuildr OS HQ → OS Customer Success. One row per account per quarter.

| Field | Type | Notes |
|---|---|---|
| Check-in | title | e.g. "FSP — 2026 Q4" |
| Account | relation → OS Accounts Database | two-way, so each account page shows its check-in history |
| Quarter | select | "2026 Q4", etc. |
| Version | select | Early / Settled / Mature |
| Variant | select | Standard / Give-first / Different sender |
| Owner | person | Trent at kickoff, Andrea later |
| Sent | date | when Trent actually sent it (detected, not when drafted) |
| Nudged | date | |
| Outcome | select | Drafted / Sent / Call booked / Survey answered / Replied / Silent / Skipped |
| Proposed entry | text | the routine's proposed Feature Request / Gap wording (see Flag rules) |
| Log it | checkbox | Trent ticks this to approve the proposed Feature Request |
| Platform score | number | 1–10 |
| Support score | number | 1–10 |
| Alongside OS | text | core Q3 answer |
| Change one thing | text | core Q4 answer |
| Version answers | text | the two age-specific answers |
| Risk signals | multi-select | Competitor tool · Workaround · Built own · Score drop · Low score · Silent · Silent ×2 |
| Related Feature Request | relation → Feature Requests | **two-way** (Claude's call: adds an account-linked rollup to Feature Requests, which isn't restricted) |
| Related Gap | relation → Behavior Gaps | **one-way only**, so nothing is added to the Gaps DB (Trent's rule) |
| Follow-up | select | None needed / Drafted / Done |
| Front link | url | the check-in conversation |
| Call notes | text | for calls (Avoma link or summary) |

**Views:** "Needs attention" (Risk signals not empty and Follow-up ≠ Done), "This quarter" (board by Outcome), "At risk" (Silent ×2, or Score drop in the latest quarter), "By account".

### 6b. Feature Requests ↔ accounts (Trent's call: yes, seed and maintain)

- **New relation on Feature Requests:** "Requesting Accounts" → OS Accounts Database. *(Claude's call: a real relation, so "which accounts asked for X?" is answerable.)* The existing free-text **Requesting Account** field and **Amount of Requests** number stay.
- **One-time backfill:** match each request's free-text Requesting Account to OS Accounts by name and set the relation.
  - **Matching:** exact or fuzzy. The builder produces a review list of uncertain or unmatched names for Trent before writing anything.
  - **Churned accounts:** they match too. The relation still records that they asked.
- **Ongoing writes (Trent's call):** when the routine creates or links a request from a check-in, it does three things:
  1. Adds the account to **Requesting Accounts**.
  2. Appends the account name to the **Requesting Account** text.
  3. Increments **Amount of Requests**. To avoid double-counting, it does this **only if the account wasn't already linked** to that request.
- **Shipped-request trigger:** this then works from day one, across every request the backfill linked.

### 7. Flag rules

These run after a survey response arrives, or when a check-in turns Silent.

| Signal | Trigger | Action the routine takes |
|---|---|---|
| **Low score** | platform or support score ≤ 6 | Draft a personal reply in Front about that score. Set Follow-up = Drafted. |
| **Score drop** | either score is ≥ 2 points below the account's previous quarter | Same as Low score. The draft names what changed, if their free text says. |
| **Competitor tool** | free text names another gym/coaching platform | Flag it. Included in the summary with the quote. No auto-email. Trent decides. |
| **Workaround / Built own** | free text describes exporting, spreadsheets, another tool for a job OS should do, or a homemade tool | Flag it. **Propose** (in the run summary) whether it's a Feature Request or a Behavior Gap, with draft wording. Trent confirms. For Feature Requests, the routine then creates or links the request and links it to the check-in. For Gaps, Trent runs his normal "log this gap" flow, and the routine links the check-in to the resulting entry one-way. |
| **Silent** | no response 14 days after sending | Mark it. Next quarter's draft uses the Give-first variant. |
| **Silent ×2** | Silent in this quarter and the previous one | Mark at-risk. Next draft uses the Different-sender variant. Called out at the top of the summary. |
| **Shipped request** | a Feature Request linked to the account is marked Completed/Closed | Mention it in that account's next check-in draft ("you asked for X, it's live"). **Changed 2026-11-03 (Trent):** no standalone email, because feature launches already go out as their own announcement and a second email would be redundant. |

Calls: after a check-in call, Trent's existing Avoma flow applies. The routine does not parse calls in v1. Trent (or a later version) fills in Call notes and Risk signals by hand. See open items.

### 8. Runtime

- **Two in-app claude.ai scheduled tasks**, with prompts that fetch a runbook from `origin/main`. This is the trial-outreach pattern: the runbook lives in `docs/runbooks/os-quarterly-checkins-runbook.md`, edits take effect without reinstalling, and a one-time supervised "Run now" pre-approves the tools.
  - `os-checkins-draft`: **weekly, Monday 8:45 CT**. Picks this week's due accounts, decides version and variant, creates log rows and Front drafts, and drafts the 7-day nudges.
  - `os-checkins-log`: **weekdays ~12:30 CT**. Detects sent drafts (sets Sent), reads new Form responses, checks HubSpot for bookings and Front for replies, applies flag rules, marks Silent, and drafts follow-ups. (Shipped requests are picked up by the draft pass, inside the next check-in.)
- **Connectors needed:** Front, HubSpot, Google Drive (sheet and form responses), Notion.
- **Avoma in the context packet: best-effort.** The avoma-transcripts MCP is flaky (it was down on 2026-11-02) and is scoped to demos. If Avoma is unreachable, the packet skips it and says so in the summary. It never blocks a draft.
- **Run summary:** each run ends with a short summary: drafts created, new flags (with quotes), at-risk accounts, generic-email warnings, and proposed Gap/Request entries. Where the summary is delivered (Slack DM vs. Today tab vs. scheduled-task output) is left to the builder. The default is a Slack DM, matching other Trent-facing summaries.
- **Idempotency:** never create a second draft for an account and quarter if a log row already exists at Drafted or later. Never re-flag a signal already recorded.
- **Deleted or unsent drafts (Claude's call):** if Trent deletes a check-in draft, the log pass sets Outcome = **Skipped**. The skip is deliberate and visible, it doesn't count toward Silent or Silent ×2, and the account comes up again next quarter. A draft still unsent after 7 days is listed in the summary ("sitting unsent"), so nothing gets skipped quietly.
- **Confirming proposed entries (Claude's call):** the routine writes its proposed wording into the row's *Proposed entry* field. For a **Feature Request**, Trent ticks *Log it*, and the next log pass creates the request (or links to an existing match) and fills *Related Feature Request*. For a **Gap**, Trent runs his normal "log this gap" flow and pastes the resulting Gap link into *Related Gap* himself. The routine never guesses which Gap matches. Nothing gets created without that tick or paste.

### 9. Ownership and the Andrea handoff

- The Owner field exists from day one, with every account set to Trent.
- When Andrea joins: reassign accounts by changing Owner. The routine drafts on the owner's Front channel with the owner's Calendly link. The builder should keep the channel and Calendly link in a small owner map in the runbook config, like the existing owner map.
- The Different-sender variant goes to whoever is *not* the current owner.

## Left to the builder

- Exact template copy (Trent approves), and form setup steps.
- How "names another platform" and "describes a workaround" are detected from free text. The routine is Claude, so a judgment prompt with examples is fine. Show the quote in the summary.
- How the routine matches Form responses to accounts (pre-filled field value plus fuzzy fallback on email or name), and what to do with unmatched responses (list them in the summary).
- Detecting that a draft was sent (Front outbound message on the conversation, as in trial outreach).
- How the Notion DB is created (MCP), and how its Account relation is seeded.

## Open items (not blocking v1)

- **Parsing check-in calls.** Later, add an Avoma recipe that fills Call notes and Risk signals from the transcript (sibling of `buyer_story_parser.py`).
- **Measuring success.** At the 2-quarter mark, compare check-in signals against actual cancellations. Did the accounts that churned show a flag first? That's the real test of whether this works.
- **Response-rate floor.** If survey and call response is under ~25% after the first quarter, revisit the email copy and survey length before adding more touches.
