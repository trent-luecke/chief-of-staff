# OS Trial Outreach Autopilot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily in-session claude.ai scheduled task that drafts (never sends) Trent's OS trial outreach in Front — an initial touch for new OS trials and two follow-ups for in-flight trials — while suppressing anyone with a sales demo booked and flagging leads who also opened a Strength trial.

**Architecture:** The runtime is a claude.ai **scheduled task** (like `os-accounts-notion-mirror`), not a compiled program. Its "source code" is a self-contained instruction runbook that, each morning, calls the Front and HubSpot MCP connectors and reasons over the results. Because those connectors are interactive-auth, this can only run inside a claude.ai session — never in GitHub Actions. This plan therefore has no unit tests: each task **validates one tool recipe against live Front/HubSpot data**, records the proven recipe into the runbook, and commits. The canonical runbook lives in the repo for version control; Task 9 installs it as the scheduled task.

**Tech Stack:** Front MCP connector (`search_conversations`, `read_conversation`, `read_message`, `create_draft`, `delete_draft`, `list_drafts`, `add_comment`, `assign_conversation`, `list_teammates`, `list_channels`); HubSpot MCP connector (`search_crm_objects`, `search_owners`, `discover_hubspot_schema`); scheduled-tasks MCP (`create_scheduled_task`, `update_scheduled_task`, `list_scheduled_tasks`).

## Global Constraints

Every task inherits these. Copy verbatim from the spec.

- **Draft-only, never send.** No `send_message`, ever. Every outbound email is a `create_draft` that Trent reviews and sends himself.
- **During validation, never draft to a real prospect.** Test-draft only to `trent@teambuildr.com`, confirm it exists as an unsent draft, then `delete_draft` it.
- **Drafting target is the OS inbox `inb_346ip` only.** The Strength inbox `inb_25ub` is read-only (dedup).
- **BCC `4238329@bcc.hubspot.com` on every outbound draft.**
- **Send from Front channel `cha_30ds1`** (`trent@teambuildr.com`, gmail).
- **3 touches maximum**, then stop. Cadence: touch 1 (new), touch 2 (≥7 days after touch 1 was sent), touch 3 (within ~1 day of Trial Expiration).
- **Demo suppression is re-checked every run**, including mid-trial.
- **Fail safe: if a lead's contact can't be found in HubSpot, do NOT draft — flag it instead.**
- **Copy is fixed in spec Appendix A.** Do not paraphrase, re-add em dashes, or "improve" the wording. `{{first_name}}` from HubSpot `firstname` (fallback `there`); `{{facility}}` from notification `Org Name` (HubSpot company fallback; omit clause if generic/missing).
- **Trent's Front teammate id is `tea_2glc1`.**
- **Calendly CTA (all touches):** `https://calendly.com/trent-luecke/30-minute-tbos-demo`.

Spec: `docs/superpowers/specs/2026-09-29-os-trial-outreach-autopilot-design.md`.

---

## File structure

- Create: `docs/runbooks/os-trial-outreach-runbook.md` — the canonical daily instruction runbook (version-controlled source of the scheduled task's prompt). Built up across Tasks 1–8.
- Runtime artifact (created in Task 9, not committed): `~/.claude/scheduled-tasks/os-trial-outreach/SKILL.md` — installed from the runbook.

Each validation task appends its proven recipe to the runbook and commits, so the runbook grows into the complete prompt by Task 8.

---

### Task 1: Resolve fixed IDs + build the rep-owner → Front-teammate map

**Files:**
- Create: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Produces: a `## Config` block in the runbook holding all fixed IDs and a `HubSpot owner id → Front teammate id` mapping table used by the reassignment recipe (Task 4).

- [ ] **Step 1: Pull the Front teammate list**

Run Front `list_teammates` (no filter). Expected: a list of teammates with `id` (tea_xxx), name, email. Confirm the sales reps appear (Chris, Irene, Brian, Ryan, Nick, Jake, Luke, etc.) and note Trent = `tea_2glc1`.

- [ ] **Step 2: Pull the HubSpot owners**

Run HubSpot `search_owners` with no `searchQuery` (paginate `limit:100` until exhausted). Expected: owners with `ownerId`, `name`, `isActive`. These are the values `MEETING_EVENT.hubspot_owner_id` resolves to.

- [ ] **Step 3: Build the mapping by email**

For each active HubSpot owner, match to a Front teammate on email (same `@teambuildr.com` address). Produce a table: `hubspot_ownerId | name | front_teammateId`. Note any HubSpot owner with no Front teammate match (these become the "unmappable → flag, don't auto-assign" case).

- [ ] **Step 4: Write the Config block to the runbook**

Create `docs/runbooks/os-trial-outreach-runbook.md` starting with:

```markdown
# OS Trial Outreach — Daily Runbook

## Config
- OS inbox (drafting target): inb_346ip
- Strength inbox (read-only, dedup): inb_25ub
- Send-from Front channel: cha_30ds1 (trent@teambuildr.com)
- BCC (all drafts): 4238329@bcc.hubspot.com
- Trent Front teammate: tea_2glc1
- Calendly CTA: https://calendly.com/trent-luecke/30-minute-tbos-demo
- Trial window scan: notifications created in the last 16 days
- Cadence: touch1 new; touch2 >=7d after touch1 sent; touch3 within 1d of Trial Expiration; max 3

### HubSpot owner -> Front teammate map
| hubspot_ownerId | name | front_teammateId |
| ... (from Steps 1-3) ... |
Owners with no Front match: [list] -> suppress+flag, never auto-assign.
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): runbook config + owner-to-teammate map"
```

---

### Task 2: OS notification scan + parser recipe

**Files:**
- Modify: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Consumes: Config (Task 1).
- Produces: a `Lead{ email, name, org, trialExpiration, notificationConvId, notificationAssigneeId }` extraction recipe used by every downstream task.

- [ ] **Step 1: Validate the scan query against the live OS inbox**

Run Front `search_conversations` with `scope: "all_inboxes"`, `filters: { inboxId: "inb_346ip" }`, `query: "New Account"`. Expected: `TeamBuildr OS - New Account` conversations. Note each conversation's `id`, `status`, `assigneeId`, `updatedAt`.

- [ ] **Step 2: Validate the body parse on 2+ real notifications**

For two returned conversations, run Front `read_conversation` (`limit: 5`) and read the inbound `message_inbound` entry's content. Confirm it parses into: `Name`, `Email`, `Org. Name`, `Studio Num.`, `Trial Exp` (MM/DD/YYYY), `Contact Number`. Expected: clean extraction of `email`, `name`, `org`, and `trialExpiration` for both.

- [ ] **Step 3: Confirm the trial-window + ownership filter**

Confirm you can identify, per conversation: created within the last 16 days, and `assigneeId` is null or `tea_2glc1`. A notification assigned to another teammate is out of scope (skip).

- [ ] **Step 4: Record the recipe in the runbook**

Append:

```markdown
## Step A — Scan OS trials
1. Front search_conversations: scope all_inboxes, filters.inboxId=inb_346ip, query "New Account". Page until conversations older than 16 days.
2. Keep only conversations whose subject is "TeamBuildr OS - New Account", created in the last 16 days, and assigned to none or tea_2glc1.
3. For each, read_conversation (limit 5); from the inbound message content parse:
   email, name, org (Org. Name), trialExpiration (Trial Exp, MM/DD/YYYY -> ISO).
   Record notificationConvId and notificationAssigneeId.
4. If the body does not parse (format drift), skip the lead and add it to the run summary under "parse failures". Never draft from a half-parsed record.
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): OS notification scan + parse recipe"
```

---

### Task 3: HubSpot contact lookup + Strength-segment recipe

**Files:**
- Modify: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Consumes: `Lead.email` (Task 2).
- Produces: `Contact{ contactId, firstName, company }` and `segment ∈ {existing_strength_customer, concurrent_strength_trial, os_only}`; consumed by Tasks 4 (contactId), 8 (segment + firstName).

- [ ] **Step 1: Validate contact-by-email lookup on a real new lead**

Run HubSpot `search_crm_objects`: `objectType: "CONTACT"`, `query: "<a real lead email from Task 2>"`, `properties: ["email","firstname","company","account_status","teambuildr_subscription_start_date","teambuildr_subscription_end_date","trial_start","trial_end","os_subscription_level","lifecyclestage"]`. Expected: 1 match with `contactId` and `firstname`.

- [ ] **Step 2: Validate segment detection on a known Strength customer**

Run the same lookup for a known active-Strength contact (from `search_crm_objects CONTACT` filtered `teambuildr_subscription_start_date HAS_PROPERTY`, `account_status EQ Active`). Expected: `account_status = "Active"` and populated `teambuildr_subscription_*` dates.

- [ ] **Step 3: Confirm the classification rules**

Confirm the decision produces the right segment for both test contacts:
- `existing_strength_customer` if `account_status = "Active"` OR (`teambuildr_subscription_start_date` set AND `teambuildr_subscription_end_date` in the future).
- else `concurrent_strength_trial` if Strength `trial_start`/`trial_end` indicates an active trial (this is finalized together with the Front dedup in Task 5).
- else `os_only`.
- Precedence: existing_strength_customer > concurrent_strength_trial > os_only.

- [ ] **Step 4: Record the recipe in the runbook**

Append:

```markdown
## Step B — HubSpot contact + Strength segment
1. HubSpot search_crm_objects CONTACT, query=<lead.email>, properties:
   email, firstname, company, account_status, teambuildr_subscription_start_date,
   teambuildr_subscription_end_date, trial_start, trial_end, os_subscription_level, lifecyclestage.
2. If NO contact matches -> do NOT draft; add to summary "contact not found"; stop processing this lead (fail-safe).
3. firstName = firstname (fallback "there"). facility = lead.org (fallback company; omit clause if generic/missing).
4. Segment (precedence customer > concurrent-trial > os_only):
   - existing_strength_customer: account_status="Active" OR (teambuildr_subscription_start_date set AND end_date in future)
   - concurrent_strength_trial: active Strength trial (trial_start/end) OR present in Strength inbox (Step D)
   - os_only: otherwise
5. Keep contactId for Step C.
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): HubSpot contact + Strength segment recipe"
```

---

### Task 4: Demo-check recipe (MEETING_EVENT association, classify, resolve rep)

**Files:**
- Modify: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Consumes: `Contact.contactId` (Task 3), owner→teammate map (Task 1).
- Produces: `DemoStatus{ suppressed, confidence ∈ {confident,flagged}, reassignTeammateId? , meetingTitle? }`; consumed by Task 8.

- [ ] **Step 1: Validate the association query on a contact WITH an upcoming demo**

Find a contact that has an upcoming `MEETING_EVENT` (via `search_crm_objects MEETING_EVENT`, sort `hs_meeting_start_time DESC`, pick a future one, note its associated contact id). Then run `search_crm_objects`: `objectType: "MEETING_EVENT"`, `filterGroups: [{ associatedWith: [{ objectType: "contacts", operator: "EQUAL", objectIdValues: [<contactId>] }] }]`, `properties: ["hs_meeting_title","hs_meeting_start_time","hs_meeting_outcome","hubspot_owner_id"]`. Expected: the upcoming meeting is returned with owner + title.

- [ ] **Step 2: Validate no-false-positive on a fresh lead**

Run the same association query for a brand-new OS lead's contactId (from Task 3 Step 1). Expected: no upcoming SCHEDULED meeting (empty or only past/cancelled).

- [ ] **Step 3: Confirm title classification + owner resolution**

Confirm the classifier on the returned titles:
- upcoming (`hs_meeting_start_time` > now), `hs_meeting_outcome = "SCHEDULED"`, title does NOT start with `[Canceled]`:
  - title contains `Demo` → suppress, confidence `confident`
  - title contains `Orientation` or `Support` → ignore (not sales contact)
  - any other title (incl. generic `Minute Meeting`) → suppress, confidence `flagged`
- Resolve `hubspot_owner_id` → owner name/email (`search_owners ownerIds:[...]`) → Front teammate via the Task 1 map. If that teammate is `tea_2glc1` (Trent) → keep assigned to Trent (no reassignment). If unmappable → suppress + flag, no auto-assign.

- [ ] **Step 4: Record the recipe in the runbook**

Append:

```markdown
## Step C — Demo-booked check (runs BEFORE drafting, every touch)
1. HubSpot search_crm_objects MEETING_EVENT, filterGroups[0].associatedWith=[{objectType:"contacts",operator:"EQUAL",objectIdValues:[contactId]}],
   properties: hs_meeting_title, hs_meeting_start_time, hs_meeting_outcome, hubspot_owner_id.
2. Keep meetings that are upcoming (start_time > now), outcome=SCHEDULED, title not starting "[Canceled]".
3. Classify by title:
   - contains "Demo" -> SUPPRESS (confident)
   - contains "Orientation" or "Support" -> ignore
   - anything else (incl. "... Minute Meeting") -> SUPPRESS (flagged)
4. If suppressed: resolve hubspot_owner_id via search_owners -> owner email -> Front teammate (Config map).
   - owner is Trent (tea_2glc1): keep assigned to Trent, do not reassign.
   - owner maps to another teammate: reassignTeammateId = that id.
   - owner unmappable: no reassignment; mark flagged.
5. If suppressed -> skip drafting for this lead this run (see Step F).
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): HubSpot demo-check recipe"
```

---

### Task 5: Strength-inbox dedup recipe

**Files:**
- Modify: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Consumes: `Lead.email` (Task 2).
- Produces: `alsoInStrength: bool`; consumed by Task 8 (dedup flag comment + segment tie-break).

- [ ] **Step 1: Validate the dedup search**

Run Front `search_conversations`: `scope: "all_inboxes"`, `filters: { inboxId: "inb_25ub" }`, `query: "<a real lead email>"`. Expected: matches if that email opened a Strength trial, empty otherwise. Test with one email known to be OS-only (expect empty).

- [ ] **Step 2: Record the recipe in the runbook**

Append:

```markdown
## Step D — Strength dedup
1. Front search_conversations: scope all_inboxes, filters.inboxId=inb_25ub, query=<lead.email>.
2. alsoInStrength = any match found. If true, this also satisfies the concurrent_strength_trial segment (Step B) unless the lead is already an existing_strength_customer.
```

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): Strength-inbox dedup recipe"
```

---

### Task 6: Cadence-state recipe (find outreach conversation, count touches)

**Files:**
- Modify: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Consumes: `Lead.email`, `Lead.trialExpiration` (Task 2).
- Produces: `nextTouch ∈ {1,2,3,null}` and `hasPendingDraft: bool`; consumed by Task 8.

- [ ] **Step 1: Validate finding a Trent↔recipient conversation and counting outbound**

Pick an existing real email thread between Trent and any external person (Front `search_conversations` scope `my_conversations`, `query:"<that person's email>"`). Run `read_conversation` and confirm you can count `message_outbound` entries authored by `tea_2glc1` and read their timestamps, and that the first page reports `drafts`. Expected: an accurate outbound count + last-send timestamp + drafts array.

- [ ] **Step 2: Validate the empty case for a fresh lead**

Run the same search for a brand-new OS lead's email. Expected: no outreach conversation yet (0 outbound) → this lead is touch 1.

- [ ] **Step 3: Confirm the derivation + idempotency rules**

Confirm the logic:
- outbound count 0 → `nextTouch = 1`
- 1, and `today − lastSend ≥ 7d` → `nextTouch = 2` (else null; not due yet)
- 2, and `today ≥ trialExpiration − 1d` → `nextTouch = 3` (else null)
- 3 → `nextTouch = null` (done)
- If an unsent draft already exists on the outreach conversation (`drafts` non-empty), `hasPendingDraft = true` → skip (never stack drafts).

- [ ] **Step 4: Record the recipe in the runbook**

Append:

```markdown
## Step E — Cadence state
1. Front search_conversations scope my_conversations, query=<lead.email>. If a Trent<->lead conversation exists, read_conversation.
2. touchCount = number of message_outbound entries authored by tea_2glc1. lastSend = latest such timestamp. hasPendingDraft = drafts non-empty.
3. nextTouch:
   - 0 -> 1
   - 1 and (today - lastSend >= 7 days) -> 2, else null
   - 2 and (today >= trialExpiration - 1 day) -> 3, else null
   - 3 -> null (done)
4. If hasPendingDraft -> skip this lead (do not create another draft).
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): cadence-state derivation recipe"
```

---

### Task 7: Draft composer recipe (create_draft, draft-only, BCC) — SAFETY-CRITICAL

**Files:**
- Modify: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Consumes: `segment`, `firstName`, `facility`, `nextTouch`, outreach conversation id (Tasks 3, 6).
- Produces: the exact `create_draft` recipe for touch 1 (new outbound) and touches 2–3 (reply), each BCC'd, draft-only.

- [ ] **Step 1: Validate a NEW-outbound draft to a SAFE address (not a prospect)**

Run Front `create_draft`: `channelId: "cha_30ds1"`, `to: ["trent@teambuildr.com"]`, `bcc: ["4238329@bcc.hubspot.com"]`, `subject: "TeamBuildr OS: Welcome!"`, `bodyFormat: "html"`, `body: "<p>Hey there! (draft mechanics test)</p>"`. Expected: a draft is created (a `dra_`/draft reference), and NO message is sent.

- [ ] **Step 2: Confirm it is an unsent draft, then delete it**

Run Front `list_drafts` (or `read_conversation` on the new conversation) and confirm the item is a draft, unsent. Then run Front `delete_draft` on it. Expected: draft removed; nothing was ever sent. (This proves the tool drafts and does not send, and leaves no residue.)

- [ ] **Step 3: Validate a REPLY draft on an existing conversation**

On the test conversation from Task 6 Step 1, run `create_draft` with `conversationId: "<that cnv>"`, `bcc: ["4238329@bcc.hubspot.com"]`, `bodyFormat: "html"`, `body: "<p>reply draft mechanics test</p>"`, `shared: false`. Confirm a reply draft is created, then `delete_draft` it. Expected: reply draft created and cleanly deleted.

- [ ] **Step 4: Record the recipe + the exact copy in the runbook**

Append (copy the three touch bodies and the touch-1 segment middles verbatim from spec Appendix A — reproduced here so the runbook is self-contained):

```markdown
## Step F — Compose the draft (DRAFT ONLY, never send)
Only if NOT suppressed (Step C) and nextTouch is 1/2/3 and not hasPendingDraft.

Personalize: {{first_name}} (fallback "there"); {{facility}} (omit clause if missing/generic).
Always BCC 4238329@bcc.hubspot.com. bodyFormat html (linkify the Calendly phrase; keep the 👉 emoji as-is on touches 2/3).

### Touch 1 (nextTouch=1): NEW outbound conversation
create_draft: channelId=cha_30ds1, to=[lead.email], bcc=[4238329@bcc.hubspot.com],
subject="TeamBuildr OS: Welcome!", shared=false.
Body skeleton:
  Hey {{first_name}}!
  This is Trent, from TeamBuildr OS. Saw you signed up for a trial account and wanted to reach out and introduce myself.
  {{middle}}
  Were there any questions I could help out with? If it's easier, you can book a call using this link -> Book a call with me [https://calendly.com/trent-luecke/30-minute-tbos-demo]
  Thanks, {{first_name}}!
{{middle}} by segment:
  os_only:
    We are stoked to have you trying us out, and I think you'll find a lot to like in TeamBuildr OS for your business.
  existing_strength_customer:
    We're stoked to have you checking out OS! Since {{facility}} already runs TeamBuildr Strength, this is an easy next step. You can keep your training programming and your booking and scheduling in one place, and accounts that already use Strength usually have the smoothest setup.
    (facility-less: "Since you already run TeamBuildr Strength, this is an easy next step. You can keep your training programming and your booking and scheduling in one place, and accounts that already use Strength usually have the smoothest setup.")
  concurrent_strength_trial:
    We're stoked to have you trying us out! Looks like you're kicking the tires on TeamBuildr Strength too. They're built to work together, so I'm happy to walk you through how OS and Strength fit side by side.

### Touch 2 (nextTouch=2): REPLY on the outreach conversation
create_draft: conversationId=<outreach cnv>, bcc=[4238329@bcc.hubspot.com], shared=false.
Body:
  Hey {{first_name}}!
  Just wanted to follow up and push this to the top of your inbox. Hope you're enjoying your trial with us so far.
  Got a question? Hit reply. Or if you're ready to dive in:
  👉 Grab 30 minutes on my calendar [https://calendly.com/trent-luecke/30-minute-tbos-demo]
  Thanks, {{first_name}}!

### Touch 3 (nextTouch=3): REPLY on the outreach conversation
create_draft: conversationId=<outreach cnv>, bcc=[4238329@bcc.hubspot.com], shared=false.
Body:
  Hey {{first_name}}!
  As your trial starts to come to a close, I wanted to reach out one last time. It's not too late to get yourself acquainted with TeamBuildr OS and start setting up your account.
  If now isn't a great time, let me know, but if you're interested in chatting, I'll leave my link below.
  👉 Let's get you set up right before your trial ends. [https://calendly.com/trent-luecke/30-minute-tbos-demo]
  We'd love to be part of your story.
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): draft composer recipe + verbatim copy"
```

---

### Task 8: Assemble the daily orchestration + run summary

**Files:**
- Modify: `docs/runbooks/os-trial-outreach-runbook.md`

**Interfaces:**
- Consumes: Steps A–F (Tasks 2–7).
- Produces: the complete ordered runbook prompt, ready to install.

- [ ] **Step 1: Write the orchestration section**

Append the top-level flow that ties the steps together:

```markdown
## Daily flow
For today's run:
1. Step A — scan OS trials in the window -> list of Leads.
2. For each Lead, in order:
   a. Step B — HubSpot contact + segment. If contact not found -> record "contact not found", skip.
   b. Step C — demo-check. If suppressed: reassign (if reassignTeammateId) via assign_conversation on notificationConvId; add_comment on notificationConvId stating "Suppressed: <meetingTitle> booked (owner <rep>)"; if flagged, note it for the summary; SKIP drafting.
   c. Step E — cadence state. If nextTouch is null or hasPendingDraft -> skip.
   d. Step D — Strength dedup (also feeds segment). If alsoInStrength -> add_comment on notificationConvId: "Also has a Strength trial — coordinate before sending."
   e. Step F — compose the draft (draft only).
3. Emit the run summary (below).

## Run summary (final message)
One block:
- Drafts created: touch1=N, touch2=N, touch3=N
- Suppressed (demo booked): N  [list flagged ones: name + meetingTitle]
- Reassigned: N (to whom)
- Dedup flags (also in Strength): N
- Needs review: contact-not-found [list], unmappable owners [list], parse failures [list]
Nothing to do -> say so explicitly.
```

- [ ] **Step 2: Self-review the assembled runbook against the spec**

Read the whole runbook top to bottom. Confirm: every Global Constraint is enforced somewhere; the copy matches spec Appendix A character-for-character (no em dashes reintroduced); no step sends; the fail-safe (contact-not-found → no draft) is present; touch caps at 3.

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): assemble daily orchestration + run summary"
```

---

### Task 9: Install the scheduled task (manual-only, no cron yet)

**Files:**
- Runtime: `~/.claude/scheduled-tasks/os-trial-outreach/SKILL.md` (created by the tool)

**Interfaces:**
- Consumes: the finished runbook (Task 8).

- [ ] **Step 1: Create the task with NO schedule (ad-hoc, manual start)**

Run scheduled-tasks `create_scheduled_task`: `taskId: "os-trial-outreach"`, `description: "Daily draft-only OS trial outreach in Front (initial + 2 follow-ups); suppresses booked-demo leads; flags dual OS/Strength trials"`, `prompt: <full contents of docs/runbooks/os-trial-outreach-runbook.md>`. Do **not** pass `cronExpression` or `fireAt` yet — leaving both off makes it manual-start only, so it cannot fire on real leads until validated.

- [ ] **Step 2: Verify it registered**

Run `list_scheduled_tasks`. Expected: `os-trial-outreach` present, `enabled` reflects manual/ad-hoc, no `nextRunAt`.

- [ ] **Step 3: Commit (no repo change; record the install)**

No file to commit here. Note in the runbook a one-line "Installed as scheduled task `os-trial-outreach` on <date>, manual-only pending validation." then:

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "chore(outreach): install scheduled task (manual-only)"
```

---

### Task 10: Supervised first run (draft-only) + tool pre-approval + inspection

**Interfaces:**
- Consumes: installed task (Task 9).

- [ ] **Step 1: Run the task manually with Trent present**

Start `os-trial-outreach` manually ("Run now"). On first run, approve the write tools when prompted: `create_draft`, `add_comment`, `assign_conversation`. This is the one-time pre-approval.

- [ ] **Step 2: Inspect what it produced — before anything is sent**

Verify against Front + the run summary:
- Drafts exist in Trent's Front drafts, **unsent**, addressed to the right leads, correct segment copy, BCC present, Calendly link intact.
- Suppressed leads got the comment + correct reassignment; no draft was created for them.
- Dedup-flagged leads got the comment.
- Summary counts match reality; contact-not-found / parse failures are listed, not silently dropped.

- [ ] **Step 3: Trent reviews the actual draft copy**

Trent opens 2–3 drafts in Front and confirms they read correctly (personalization filled, no `{{...}}` left, no stray em dashes). Nothing is sent by the task — Trent sends manually if he approves.

- [ ] **Step 4: Fix any issues in the runbook, reinstall, re-run**

If anything is wrong, edit `docs/runbooks/os-trial-outreach-runbook.md`, run `update_scheduled_task` (taskId `os-trial-outreach`, new `prompt`), commit, and repeat Steps 1–3 until clean.

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "fix(outreach): runbook corrections from supervised run"
```

---

### Task 11: Enable the daily 8:30 CT cron

**Interfaces:**
- Consumes: validated task (Task 10).

- [ ] **Step 1: Add the schedule**

Run scheduled-tasks `update_scheduled_task`: `taskId: "os-trial-outreach"`, `cronExpression: "30 8 * * *"` (cron is evaluated in local time; Trent's timezone is America/Chicago = CT, so this is 8:30 AM CT). Ensure the task is enabled.

- [ ] **Step 2: Verify the schedule**

Run `list_scheduled_tasks`. Expected: `os-trial-outreach` enabled, `cronExpression: "30 8 * * *"`, a `nextRunAt` at the next 8:30 AM CT.

- [ ] **Step 3: Record go-live**

Update the runbook header: "Live daily at 8:30 AM CT since <date>." Commit.

```bash
git add docs/runbooks/os-trial-outreach-runbook.md
git commit -m "feat(outreach): enable daily 8:30 CT schedule"
```

- [ ] **Step 4: Watch the first autonomous run**

The morning after enabling, confirm the run summary looks right and drafts landed. If the app was closed at 8:30, the task runs on next launch — expected behavior, not a failure.

---

## Notes for the executor

- **The app must be open for the task to run.** Scheduled tasks fire only while the claude.ai app is open; a missed run fires on next launch.
- **Never let a validation step send.** Every `create_draft` in Tasks 7 and 10 is draft-only; test drafts go to `trent@teambuildr.com` and are deleted.
- **Keep the runbook and the installed SKILL.md in sync.** Any change to behavior = edit the repo runbook, then `update_scheduled_task` with the new prompt, then commit.
- **HubSpot is read-only here.** No task writes to HubSpot; logging happens only via the BCC on Front drafts.
