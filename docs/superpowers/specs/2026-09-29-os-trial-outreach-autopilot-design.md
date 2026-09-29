# OS Trial Outreach Autopilot — Design

**Date:** 2026-09-29
**Status:** Design approved; ready for implementation plan
**Owner:** Trent Luecke

## Problem

Every day Trent spends 15–20 minutes on OS trial reach-out, entirely in click-labor. For each new OS trial he clicks the "View Contact" link in the Front notification, lands on the HubSpot contact, picks a template, and sends. He repeats the same click-path for a second touch ~7 days later and a third at trial-end (~14 days), using a Front snooze on the notification as his only reminder. There is no automated sequence — the snooze button *is* the cadence engine and the process is pure manual repetition.

## Goal

A daily scheduled task that eliminates the click-path by drafting the outreach for Trent to review and send: initial touch for new OS trials, plus the two follow-ups for in-flight trials. It must never email a lead who is already in active contact (has a sales demo booked), and must catch leads who opened both an OS and a Strength trial so they aren't double-touched.

## Non-goals (v1)

- **No Strength outreach.** The Strength inbox is read-only here; Chris/Irene own it.
- **No auto-send.** The task only drafts. Trent reviews and sends every email.
- **No HubSpot sequence rebuild** and **no HubSpot writes.** HubSpot is read-only (demo/contact lookup) plus a BCC target for logging.
- **No handling of lead replies.** Once a lead replies, it's a live conversation Trent owns manually; the cadence stops for that lead.
- **No account-health scope.**

## Architecture & runtime

- **Runs as an in-session claude.ai scheduled task at 8:30 AM CT**, using the same pattern as the `os-accounts-notion-mirror` task. This is mandatory: the Front and HubSpot connectors are interactive-auth claude.ai connectors and are only available inside a claude.ai session. They **cannot** run in the chief-of-staff GitHub Actions crons, so nothing here goes into that repo's runtime.
- **Connectors required on the task's account:** Front, HubSpot, Google (not strictly needed once HubSpot is the demo source), Slack (optional, for run summary).
- **One-time tool pre-approval** on the first supervised run for the write tools: `create_draft`, `add_comment`, `assign_conversation`. After the first "Run now" approves them, the task runs autonomously.

## Data sources

| Source | Access | Use |
|--------|--------|-----|
| Front OS inbox `inb_346ip` | read + write (draft/comment/assign) | Trigger: `TeamBuildr OS - New Account` notifications; drafting target |
| Front Strength inbox `inb_25ub` | read-only | Dedup: detect the same lead's Strength trial |
| HubSpot `CONTACT` | read-only | Resolve lead by email; owner |
| HubSpot `MEETING_EVENT` | read-only | Demo-booked check (start time, owner, title, outcome) |
| HubSpot `OWNER` (`search_owners`) | read-only | Map meeting `hubspot_owner_id` → rep name/email |
| Front `list_teammates` | read-only | Map rep email/name → Front teammate ID for reassignment |
| Front channel (Trent's) | write | Channel the outbound drafts are composed from |

## Notification payload (parsed input)

The `New Account` notification body is templated structured text. Two variants:

- **OS** (`inb_346ip`): `Name`, `Email`, `Org. Name`, `Studio Num.`, `Trial Exp` (`MM/DD/YYYY`), `Contact Number`, `HubSpot: View Contact <link>`.
- **Strength** (`inb_25ub`): `Name`, `Email`, `Org. Name`, `Org. Type`, `Account ID`, `Trial Expiration` (`YYYY-MM-DD`), `Referred By`.

Fields used: **Email** (identity/dedup key), **Name** + **Org** (personalization), **Trial Expiration** (cadence anchor for touch 3). Two parsers keyed by inbox handle the format difference.

## Components

Each component is independently testable with a clear input/output contract.

### 1. Notification scanner + parser
- **Input:** OS inbox conversations.
- **Does:** finds `TeamBuildr OS - New Account` notifications **within the trial window** (created in the last ~16 days = 14-day trial + buffer) whose assignee is **none or Trent** (a notification reassigned to another rep is skipped — it's out of Trent's lane). Parses the OS-variant body into a `Lead{ email, name, org, trialExpiration, notificationConvId }`.
- **Output:** list of `Lead` records.
- **Note:** this single scan feeds both legs. Whether a lead is Leg A (touch 1) or Leg B (touch 2/3) is decided downstream by the cadence engine, not by a separate scan. The notification thread — which lives in the inbox for the whole trial window — is the enumeration anchor; the outreach conversation supplies the touch count.

### 2. Strength dedup check
- **Input:** a `Lead`'s email.
- **Does:** searches the Strength inbox (`inb_25ub`) for the same email.
- **Output:** `alsoInStrength: bool` (+ the Strength conv reference for the flag comment).

### 3. HubSpot demo-check (exclusion + reassignment source)
- **Input:** a `Lead`'s email.
- **Does:** resolves the contact by email (`search_crm_objects CONTACT`), then finds associated `MEETING_EVENT`s (`search_crm_objects MEETING_EVENT` with `associatedWith` the contact id) that are **upcoming** (`hs_meeting_start_time` in the future), **`hs_meeting_outcome = SCHEDULED`**, and **not** `[Canceled]` in the title. Classifies by title:
  - title contains `Demo` → **suppress (confident)**
  - title contains `Orientation` or `Support` → **ignore** (not sales contact)
  - any other title, incl. generic `... Minute Meeting` or manually-titled → **suppress (flag for review)**
- **Output:** `DemoStatus{ suppressed: bool, confidence: "confident"|"flagged", meetingOwnerId?, meetingTitle? }`.
- **Reassignment target:** if suppressed and `meetingOwnerId` resolves (via `search_owners` → email/name → Front `list_teammates` → teammate id), that teammate is the reassignment target. If the owner is Trent, keep assigned to Trent. If the owner can't be mapped to a Front teammate, do not auto-assign — flag it.

### 4. Cadence engine (touch-state derivation)
- **Input:** a `Lead` (email + trialExpiration).
- **Does:** finds the outreach conversation with this lead (Front conversation where the lead's email is the recipient, on Trent's channel) and counts **Trent's outbound messages** to derive the touch state. Because Trent now sends from Front, each send is a real timestamped outbound message — this is the ground truth, no external tracker.
  - 0 sent → **touch 1 due** now (Leg A)
  - 1 sent, and `today − lastSendDate ≥ 7d` → **touch 2 due** (Leg B)
  - 2 sent, and `today ≥ trialExpiration − 1d` → **touch 3 due** (Leg B)
  - 3 sent → **done**, skip
- **Output:** `nextTouch: 1|2|3|null`.
- **Idempotency guard:** if an unsent draft already exists on the lead's outreach conversation (`read_conversation.drafts`), skip — never stack drafts.

### 5. Draft composer
- **Input:** `Lead`, `nextTouch`, template set, and (for touch 1) the lead's Strength segment.
- **Does:** selects the touch-N template — for touch 1, picks the `{{middle}}` variant by Strength segment (existing-customer > concurrent-trial > OS-only; see Appendix A) — personalizes `{{first_name}}`/`{{facility}}`, and creates the draft via `create_draft` — for touch 1 a **new outbound conversation** `to` the lead's email from Trent's channel with `subject`; for touches 2–3 a reply on the existing outreach conversation. Adds Trent's HubSpot logging **BCC** on every draft so the send logs to the HubSpot timeline.
- **Output:** draft created (private to Trent for review).

### 6. Reassignment
- **Input:** `DemoStatus` with a resolved Front teammate target.
- **Does:** `assign_conversation` on the OS notification conversation to the demo's rep (skip if that rep is Trent). Internal, reversible action.

### 7. Daily orchestrator + run summary
One scan (component 1), then each lead flows through the same pipeline; "Leg A/B" are just labels for the touch that comes due.

For each `Lead`:
1. **Demo-check** (component 3). If suppressed → reassign to the demo's rep if applicable (component 6), add a comment noting why (and flag it if the suppression was the "flagged" confidence tier), and **skip drafting**. Re-running this every morning is what stops the cadence mid-trial when a lead books a demo after touch 1.
2. **Cadence engine** (component 4) → `nextTouch`. If `null` (done) → skip.
3. **Dedup check** (component 2). If `alsoInStrength` → add the flag comment on the OS notification thread; still proceed.
4. **Draft composer** (component 5) for the due touch. `nextTouch == 1` is Leg A; `2|3` is Leg B.

- **Run summary (in-session, optionally Slack):** counts of drafts created (touch 1/2/3), leads suppressed for a booked demo, reassignments, dedup flags, and anything needing Trent's eyes (flagged generic-meeting suppressions, unmappable owners, contact-not-found, parse failures).

## Cadence timing

| Touch | Trigger | Anchor |
|-------|---------|--------|
| 1 — Initial | New OS trial, 0 prior sends, not suppressed | Signup / next run |
| 2 — Mid | 1 prior send, ≥7 days since that send | Real send date |
| 3 — Trial-end | 2 prior sends, within ~1 day of Trial Expiration | `Trial Expiration` from notification |

Thresholds (`7d`, `trialExpiration − 1d`, max `3` touches) are configuration, not hard-coded literals.

## Safety & idempotency

- **Draft-only, always.** No `send_message`. Every outbound email is reviewed and sent by Trent.
- **No double-drafting.** Skip any lead with an unsent draft already on its outreach conversation.
- **Clock anchored on real sends,** not on "drafted" — if Trent doesn't send a draft, the cadence does not advance.
- **Hard cap at 3 touches.**
- **Demo suppression is re-checked every run,** including mid-trial, so a lead who books a demo after touch 1 never receives another "book a demo" nudge.
- **Reassignment is internal and reversible;** unmappable owners are flagged, never force-assigned.

## Configuration / inputs (owed by Trent before build)

1. **Three template bodies** — initial / mid / trial-end (copy from the current HubSpot templates).
2. **HubSpot logging BCC address** (`...@bcc.hubspot.com`).
3. **Front sending channel** — the channel drafts are composed from (I'll list channels; we pick Trent's personal one).

Derived at build time (no user input): OS/Strength inbox ids (known), rep-owner → Front-teammate map (from `search_owners` + `list_teammates`).

## Failure modes

- **Notification parse failure** (format drift) → skip the lead, add to run summary; never draft from a half-parsed record.
- **Contact not found in HubSpot** → cannot run the demo-check reliably → do **not** draft; flag for manual review (fail safe, since the whole point is to avoid emailing someone already engaged).
- **HubSpot/Front API error** → skip that lead this run, report in summary; the daily cadence self-heals next run.
- **Owner unmappable to a Front teammate** → suppress + flag, don't auto-assign.

## Future / v2 (out of scope now)

- Richer HubSpot contact enrichment for personalization if templates need more than name/org.
- Optional auto-send for the highest-confidence touches once trust is established.
- Consider open-deal state as an additional "already engaged" signal beyond booked demos.

## Appendix A — Template copy (provided 2026-09-29)

**Personalization:** `{{first_name}}` resolves from the HubSpot contact's `firstname` (already fetched during the demo-check), **not** parsed from the Front notification `Name` (which mixes titles/initials — "Coach Edgar", "Joey H"). Fallback when `firstname` is missing or non-personal → `Hey there!`. `{{facility}}` resolves from the notification `Org Name` (HubSpot company as fallback); omitted from the sentence when missing or clearly not a facility.

**Touch 1 is segmented** on the lead's Strength relationship (read from the same HubSpot contact fetch used for the demo-check — `account_status`, `teambuildr_subscription_start_date/_end_date`, Strength `trial_start/_end` — plus the Front Strength-inbox dedup). Touches 2 and 3 are not segmented. Segment precedence when more than one could apply: **existing Strength customer > concurrent Strength trial > OS-only.**

**Shared CTA (all three touches):** `https://calendly.com/trent-luecke/30-minute-tbos-demo` — Trent's own OS demo Calendly. A booking through this link creates an OS demo owned by Trent, which the demo-check detects on the next run and auto-suppresses the remaining touches (self-consistent cadence stop).

**HubSpot BCC (all three):** `4238329@bcc.hubspot.com`.

### Touch 1 — Initial (new outbound conversation), segmented
- **Subject:** `TeamBuildr OS: Welcome!`
- **Body skeleton** (only `{{middle}}` varies by segment):
```
Hey {{first_name}}!

This is Trent, from TeamBuildr OS. Saw you signed up for a trial account and wanted to reach out and introduce myself.

{{middle}}

Were there any questions I could help out with? If it's easier, you can book a call using this link -> Book a call with me [https://calendly.com/trent-luecke/30-minute-tbos-demo]

Thanks, {{first_name}}!
```

**`{{middle}}` — OS-only** (no Strength account or trial):
```
We are stoked to have you trying us out, and I think you'll find a lot to like in TeamBuildr OS for your business.
```

**`{{middle}}` — Existing Strength customer** (`account_status = Active` / active `teambuildr_subscription`):
```
We're stoked to have you checking out OS! Since {{facility}} is already running TeamBuildr Strength, you're in a great spot — you can manage the training side and the business/scheduling side under one roof, and existing Strength accounts tend to have the smoothest time getting set up.
```
Facility-less fallback: `Since you're already running TeamBuildr Strength, you're in a great spot — ...`

**`{{middle}}` — Concurrent Strength trial** (Strength `trial` active, or lead present in the Front Strength inbox):
```
We're stoked to have you trying us out! Looks like you're kicking the tires on TeamBuildr Strength as well — they're built to work together, so I'm happy to walk you through how OS and Strength fit side by side.
```

### Touch 2 — Follow-up (reply on the touch-1 thread)
```
Hey {{first_name}}!

Just wanted to follow up and push this to the top of your inbox. Hope you're enjoying your trial with us so far.

Got a question? Hit reply. Or if you're ready to dive in:

👉 Grab 30 minutes on my calendar [https://calendly.com/trent-luecke/30-minute-tbos-demo]

Thanks, {{first_name}}!
```

### Touch 3 — Final / trial-end (reply on the touch-1 thread)
```
Hey {{first_name}}!

As your trial starts to come to a close, I wanted to reach out one last time. It's not too late to get yourself acquainted with TeamBuildr OS and start setting up your account.

If now isn't a great time, let me know, but if you're interested in chatting, I'll leave my link below.

👉 Let's get you set up right before your trial ends. [https://calendly.com/trent-luecke/30-minute-tbos-demo]

We'd love to be part of your story.
```

**Rendering note:** bracketed link text becomes an HTML `<a>` anchor on the phrase (e.g. "Book a call with me", "Grab 30 minutes on my calendar") wrapping the URL; emojis pass through as UTF-8.
