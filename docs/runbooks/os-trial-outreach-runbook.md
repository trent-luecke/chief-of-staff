# OS Trial Outreach — Daily Runbook

Version-controlled source of the `os-trial-outreach` claude.ai scheduled task. Runs in-session at 8:30 AM CT. Draft-only: it never sends. Any behavior change = edit this file, then `update_scheduled_task` with the new prompt.

## Config
- OS inbox (drafting target): `inb_346ip`
- Strength inbox (read-only, dedup): `inb_25ub`
- Send-from Front channel: `cha_30ds1` (trent@teambuildr.com, gmail)
- BCC on every draft: `4238329@bcc.hubspot.com`
- Trent Front teammate: `tea_2glc1` (HubSpot owner 294790730)
- Calendly CTA: `https://calendly.com/trent-luecke/30-minute-tbos-demo`
- "Expired Trial" tag (applied after the final email): `tag_v1kw1`
- "Trial Outreach" tag (the in-sequence marker on the notification thread): `tag_4puwt6`
- Scan paging bound: stop paging notifications older than ~16 days (14-day trial + buffer). The real active filter is the Trial Expiration gate in Step A.
- Cadence: touch1 new; touch2 ≥7d after touch1 sent; touch3 within 1d of Trial Expiration; max 3 touches

### HubSpot owner → Front teammate map (for demo-booked reassignment)
Reassignment only works for reps who exist in Front. Match is by name (HubSpot `search_owners` returns no email).

| HubSpot owner (id) | Front teammate |
| --- | --- |
| Chris Reynolds (33259350) | tea_a691 |
| Brian Szutkowski (109722116) | tea_2ca4h |
| Luke Green (31306047) | tea_46s9 |
| Ryan Allwein (41768528) | tea_keo5 |
| Colin Snyder (300307606) | tea_2jd4x |
| Andrea Alamo (89103279) | tea_d12je |
| Luke Martin (80627285) | tea_2kp35 |
| Irene Pérez Fernández (72043592) | tea_2jt4x |
| Jeff Davidson (294790731) | tea_2gldt |
| Teofe Ziemnicki (164484886) | tea_2ea69 |
| Clayton Young (158178098) | tea_2dz7l |
| Nicole Foley (436197768) | tea_2hoxt |
| Evan Lodder (436197769) | tea_2how1 |
| Amanda Kelso (550422844) | tea_2i7nl |
| Melissa Mercado (1667428966) | tea_2jgox |
| Heather Briere (78202178) | tea_2k3wh |
| Quinn Kastle (83468192) | tea_2k98h |
| James Peters (31192162) | tea_1wbr |
| Hewitt Tomlin (31189629) | tea_1wbx |
| Elvis Guillen (33910742) | tea_acx1 |
| Kyle Miller (240422487) | tea_28am9 |
| Tyler Johnson (117102366) | tea_2cm4h |
| Emily Nickerson (117151902) | tea_2cjk1 |
| Grace Stiles (59200905) | tea_28ydd |
| Evan Brizendine (49384101) | tea_26bb5 |
| Kylah Broadnax (1362076808) | tea_2j88x |
| Seth Gray (79961820) | tea_cyjq2 |
| Cora Van Dyck (80743806) | tea_2kps1 |
| Rachel Hodgson (303992238) | tea_2grep (same person as Front "Rachel Newman"; note: she does not own demos, so this row is effectively unused) |

**Unmappable active demo owners (no Front account → suppress + flag, never auto-assign):** Nick Hawkins (47696639), Shane Gring (77519053), Josh Beedle (84308332), Duncan Richey (87381684), Penn Riney (93606412), Alec Metzger (95076082), Eduardo/Eddy Poveda (95183716), John Rowbotham (96600088), Tyler Samani-Sprunk (3987522), Haley Mathis (47680956), Dawn Mathis* (39493992). Non-human owners (Info TeamBuildr 217718845, GymStudio Info 415599761, Analytics Account) also never receive assignments.

Rule: if a demo's `hubspot_owner_id` is in the map → reassign to that Front teammate (unless it's Trent). Otherwise → suppress the lead and flag "demo owner <name> not in Front — assign manually."

## Step A — Scan OS trials
1. Front `search_conversations`: scope `all_inboxes`, filters.inboxId=`inb_346ip`, query "New Account". Page until you have all conversations whose inbound notification is within the trial window (see step 4).
2. Keep conversations whose subject is exactly "TeamBuildr OS - New Account" AND `assigneeId` is null (untouched) or `tea_2glc1` (Trent's). Skip any assigned to another teammate (out of Trent's lane).
   **IGNORE `ticketStatus` entirely.** Front auto-sets every archived conversation to "Resolved", so Resolved carries no meaning here (this was the 2026-10-08 bug: the old "skip Resolved" rule hid every archived in-flight lead). Membership in the sequence is decided ONLY by the Trial Outreach tag (`tag_4puwt6`), per the lanes below.
3. Assign each kept conversation a **lane**:
   - `tagged` — `tagIds` includes `tag_4puwt6` (any status, archived or not). In the sequence: full pipeline (touches 1–3).
   - `new` — no `tag_4puwt6` AND `status` is NOT archived (still sitting open in the inbox). A fresh signup Trent hasn't triaged: eligible for **touch 1 only**.
   - `archived_untagged` — no `tag_4puwt6` AND `status` is archived. Trent either dismissed it (deleted the touch-1 draft + archived) or sent touch 1 and archived it without tagging. Handled in Step E2 (auto-tag) — never drafted unless auto-tagged.
   How Trent drives it: sending touch 1 = opt in (the routine auto-tags, Step E2). Deleting the touch-1 draft + archiving = dismiss. **Removing the Trial Outreach tag = stop the sequence** (the routine never re-adds a tag Trent removed — see Step E2's marker rule).
4. For each kept conversation, `read_conversation` (limit 5) and parse the `message_inbound` content:
   `New Account Created: Name: <name> Email: <email> Org. Name: <org> Studio Num.: <id> Trial Exp: <MM/DD/YYYY> Contact Number: <phone> HubSpot: View Contact ...`
   Extract: email, name, org, trialExpiration (parse MM/DD/YYYY). Record notificationConvId + notificationAssigneeId.
5. Active-window gate: process a lead only if `trialExpiration >= today - 1 day` (trial not already lapsed). Drop expired trials.
6. If the body does not parse (format drift), skip the lead and add it to the summary "parse failures". Never draft from a half-parsed record.

## Step B — HubSpot contact + Strength segment
1. HubSpot `search_crm_objects` CONTACT, query=<lead.email>, properties: email, firstname, company, teambuildr_subscription_end_date, trial_end, os_subscription_level, lifecyclestage.
2. If NO contact matches → do NOT draft; add to summary "contact not found"; stop this lead (fail-safe).
3. contactId = result id. firstName = firstname (fallback "there"). facility = lead.org (fallback company; omit the facility clause if missing or clearly not a facility name).
4. Strength segment (precedence: customer > concurrent-trial > os_only):
   - `existing_strength_customer`: `teambuildr_subscription_end_date` is set AND ≥ today. **Do NOT use `account_status`** — it is stale (shows "Active" for long-lapsed subs, e.g. a sub that ended 2025).
   - `concurrent_strength_trial`: Strength `trial_end` ≥ today, OR the lead is present in the Strength inbox (Step D).
   - `os_only`: otherwise (includes lapsed Strength customers and lapsed trials).

## Step C — Demo-booked check (runs BEFORE drafting, every touch)
1. HubSpot `search_crm_objects` MEETING_EVENT, filterGroups[0].associatedWith=[{objectType:"contacts",operator:"EQUAL",objectIdValues:[contactId]}], properties: hs_meeting_title, hs_meeting_start_time, hs_meeting_outcome, hubspot_owner_id.
2. Keep meetings where hs_meeting_start_time > now, hs_meeting_outcome=SCHEDULED, and title does NOT start with "[Canceled]".
3. Classify by title:
   - contains "Demo" → SUPPRESS (confident)
   - contains "Orientation" or "Support" → ignore (not sales contact)
   - anything else (incl. "… Minute Meeting") → SUPPRESS (flagged)
4. If suppressed, resolve hubspot_owner_id via the Config owner→teammate map:
   - maps to Trent (tea_2glc1) → keep assigned to Trent, no reassignment.
   - maps to another teammate → reassignTeammateId = that id.
   - not in the map (e.g. Nick Hawkins) → no reassignment; mark "demo owner not in Front — assign manually".
5. If suppressed → skip drafting this lead this run (Step F).

## Step D — Strength dedup
1. Front `search_conversations`: scope all_inboxes, filters.inboxId=inb_25ub, query=<lead.email>.
2. alsoInStrength = any match found. If true and the lead is not already existing_strength_customer → segment = concurrent_strength_trial.

## Step E — Cadence state (from HubSpot EMAIL engagements)
1. HubSpot `search_crm_objects` EMAIL, filterGroups[0].associatedWith=[{objectType:"contacts",operator:"EQUAL",objectIdValues:[contactId]}], properties: hs_email_subject, hs_timestamp, hs_email_status; sort hs_timestamp desc.
2. Matching emails = hs_email_status=SENT AND hs_email_subject CONTAINS ANY of these outreach subjects (case-insensitive; "Re: …" and "Front: …" prefixes still match via contains):
   - `TeamBuildr OS: Welcome!`
   - `TeamBuildr OS Follow-Up`
   - `TeamBuildr OS Trial`
   This covers the current template (Welcome + Re: replies) and the older manual subjects (Follow-Up, Trial) used on in-flight leads. It excludes other teams' templates ("Book your TeamBuildr Overview") and the notification ("… - New Account").
   touchCount = number of DISTINCT CALENDAR DAYS among matching emails (dedupes double-logged Front/BCC copies of one send). lastSend = the latest matching day.
   CAVEAT: a touch sent outside HubSpot (never logged) is invisible here regardless of subject — if one slips through, Trent removes the Trial Outreach tag (Step A lanes) to stop the sequence.
3. nextTouch:
   - 0 → 1
   - 1 and (today − lastSend ≥ 7 days) → 2, else null
   - 2 and (today ≥ trialExpiration − 1 day) → 3, else null
   - 3 → null (done)
4. Idempotency: Front `search_conversations` scope my_conversations, query=<lead.email>; read any matching conversation and if any has a non-empty `drafts` array (an unsent draft from a prior run), hasPendingDraft=true → skip this lead (never stack drafts).
5. Every touch (1, 2, 3) is sent as a NEW outbound conversation (see Step F) — never a threaded reply. Reply drafts cannot carry a BCC, which would drop HubSpot logging and break this counter; new-outbound-with-BCC guarantees each touch logs and advances the count.

## Step E2 — Auto-tag (sending touch 1 = opt in)
Runs right after Step E, for leads in lane `new` or `archived_untagged` (Step A) — never for `tagged`.
1. If `touchCount == 0`:
   - lane `new` → stays `new` (touch-1 candidate). Continue.
   - lane `archived_untagged` → Trent dismissed it (deleted the draft + archived). **Skip silently** — no comment, no draft, not listed under contact-not-found, not in the summary.
2. If `touchCount >= 1` (touch 1 really went out per HubSpot):
   - **Removed-tag marker check:** if the notification thread already has a comment beginning `Added to Trial Outreach` OR `First email sent`, this lead was in the sequence before and Trent has since removed the tag → he stopped it. **Skip silently, never re-tag.**
   - Otherwise → `tag_conversation` addTags=[`tag_4puwt6`] on notificationConvId, then `add_comment`: `Added to Trial Outreach (auto: touch 1 sent M/D).` (M/D = first send day). Treat the lead as lane `tagged` for the rest of this run. Do NOT unarchive / change status.
Step B's contact-not-found for an `archived_untagged` lead is also silent (it's almost always junk Trent already dismissed).

## Step F — Compose the draft (DRAFT ONLY — never send)
Only if NOT suppressed (Step C) AND nextTouch is 1/2/3 AND not hasPendingDraft.
- Always BCC `4238329@bcc.hubspot.com`. Send-from channel `cha_30ds1`. `shared=false` (private draft for Trent).
- `bodyFormat` html: linkify the "Book a call with me" / "Grab 30 minutes on my calendar" / "Let's get you set up…" phrases onto the Calendly URL; keep the 👉 emoji on touches 2/3.
- Personalize {{first_name}} (fallback "there") and {{facility}} (omit the clause if missing/generic).
- **Do NOT add a signature or a closing like "Thanks,"** — the `cha_30ds1` channel auto-appends "Have a good one!" + Trent's signature block. End the body at the last content line.

### Touch 1 (nextTouch=1): NEW outbound conversation
create_draft: channelId=cha_30ds1, to=[lead.email], bcc=[4238329@bcc.hubspot.com], subject="TeamBuildr OS: Welcome!", shared=false.
Body skeleton:
```
Hey {{first_name}}!

This is Trent, from TeamBuildr OS. Saw you signed up for a trial account and wanted to reach out and introduce myself.

{{middle}}

Were there any questions I could help out with? If it's easier, you can book a call using this link -> Book a call with me [https://calendly.com/trent-luecke/30-minute-tbos-demo]
```
{{middle}} by segment:
- os_only:
  `We are stoked to have you trying us out, and I think you'll find a lot to like in TeamBuildr OS for your business.`
- existing_strength_customer:
  `We're stoked to have you checking out OS! Since {{facility}} already runs TeamBuildr Strength, this is an easy next step. You can keep your training programming and your booking and scheduling in one place, and accounts that already use Strength usually have the smoothest setup.`
  (facility-less: `Since you already run TeamBuildr Strength, this is an easy next step. You can keep your training programming and your booking and scheduling in one place, and accounts that already use Strength usually have the smoothest setup.`)
- concurrent_strength_trial:
  `We're stoked to have you trying us out! Looks like you're kicking the tires on TeamBuildr Strength too. They're built to work together, so I'm happy to walk you through how OS and Strength fit side by side.`

### Touch 2 (nextTouch=2): NEW outbound conversation
create_draft: channelId=cha_30ds1, to=[lead.email], bcc=[4238329@bcc.hubspot.com], subject="Re: TeamBuildr OS: Welcome!", shared=false. (New outbound, NOT a reply — a reply would drop the BCC.) Body:
```
Hey {{first_name}}!

Just wanted to follow up and push this to the top of your inbox. Hope you're enjoying your trial with us so far.

Got a question? Hit reply. Or if you're ready to dive in:

👉 Grab 30 minutes on my calendar [https://calendly.com/trent-luecke/30-minute-tbos-demo]
```

### Touch 3 (nextTouch=3): NEW outbound conversation
create_draft: channelId=cha_30ds1, to=[lead.email], bcc=[4238329@bcc.hubspot.com], subject="Re: TeamBuildr OS: Welcome!", shared=false. (New outbound, NOT a reply.) Body:
```
Hey {{first_name}}!

As your trial starts to come to a close, I wanted to reach out one last time. It's not too late to get yourself acquainted with TeamBuildr OS and start setting up your account.

If now isn't a great time, let me know, but if you're interested in chatting, I'll leave my link below.

👉 Let's get you set up right before your trial ends. [https://calendly.com/trent-luecke/30-minute-tbos-demo]

We'd love to be part of your story.
```

## Step H — Touch-log comments (record actual sends on the notification thread)
Records when each outreach email actually went out, as comments on the OS notification thread (notificationConvId). Uses ACTUAL sends from HubSpot (Step E), not draft dates — so it only logs what truly sent, and it back-fills prior sends (incl. pre-launch/in-flight leads).
1. From Step E's matching SENT emails, take the DISTINCT send days sorted ascending. The 1st, 2nd, 3rd map to First / Follow-up / Final.
2. For each send day that exists, the intended comment is:
   - 1st → `First email sent: M/D`
   - 2nd → `Follow-up email sent: M/D`
   - 3rd → `Final email sent: M/D`
3. Read the notification thread's existing comments (from Step A's read_conversation; paginate the timeline if there are many entries). If a comment already begins with that label ("First email sent" / "Follow-up email sent" / "Final email sent"), SKIP it — only `add_comment` the missing ones. This makes it idempotent and back-fills history.
4. Run this for every lead in lane `tagged` (incl. leads auto-tagged in Step E2) or `new` that has a HubSpot contact — never for a silently-skipped `archived_untagged` lead — regardless of suppression (Step C) or nextTouch — it is a record of real sends, independent of whether a new draft is created today. Use the notification thread currently being processed (for duplicate signups, the one assigned to Trent, else the most recent).
5. Archived/snoozed threads: add_comment works on them in place and does NOT reopen or resurface them (verified 2026-10-01 on archived+snoozed leads — they stayed archived). So the log lands on in-flight snoozed notifications without Trent having to unarchive anything.

## Step I — End-of-sequence cleanup (after the final email)
When `touchCount == 3` (the Final email has actually sent, per Step E — the full sequence is complete):
1. If the notification thread's `tagIds` does NOT already include `tag_v1kw1` ("Expired Trial"), add it: `tag_conversation` addTags=[`tag_v1kw1`].
2. If the thread's `status` is not already "archived", archive it: `update_conversation_status` status="archived". (Usually already archived, since leads come in archived; idempotent no-op if so.)
Idempotent — check existing `tagIds`/`status` first so daily re-runs don't re-tag or thrash. Runs regardless of suppression/draft state. After this the Step A trial-expiration gate drops the lead from the scan within a day or two (touch 3 sends ~1 day before expiry).

## Daily flow (orchestration)
Run Step A once, then for each Lead run this pipeline in order (early exits save work):
1. **Step B** — HubSpot contact + segment. If contact not found → add to summary "contact not found", skip this lead (fail-safe: never draft without a contact).
2. **Step E** — cadence: compute touchCount / lastSend / send-days from HubSpot, and hasPendingDraft.
2b. **Step E2** — lane resolution / auto-tag. `archived_untagged` leads either get auto-tagged (→ `tagged`) or are skipped silently here. Lane `new` with touchCount ≥ 1 is also auto-tagged.
3. **Step H** — touch-log comments: post any missing First/Follow-up/Final "…sent: M/D" comments on notificationConvId. Always runs (records real sends even for suppressed or completed leads).
3b. **Step I** — if `touchCount == 3` (final email sent): tag the notification "Expired Trial" (tag_v1kw1) if not already, and archive it if not already. End-of-sequence cleanup.
4. **Step C** — demo-booked check. If suppressed:
   - if `reassignTeammateId` (a rep who is in Front): `assign_conversation` notificationConvId → reassignTeammateId.
   - `add_comment` on notificationConvId: `Suppressed: <meetingTitle> booked (owner <rep>).` — if the owner is unmappable, use `… owner <name> not in Front — assign manually`; if the suppression was the flagged tier (generic "Meeting"), append `[flagged — verify it was a real sales touch]`.
   - Do NOT draft; go to next lead.
5. Cadence gate: if `nextTouch` is null (done/not due) or `hasPendingDraft` → go to next lead (no draft). Lane `new` may only receive touch 1 (touches 2/3 require lane `tagged`). Note: a `new` lead whose touch-1 draft Trent deleted but did NOT archive gets a fresh touch-1 draft next run — archiving is the dismiss signal.
6. **Step D** — Strength dedup (also finalizes the segment). If `alsoInStrength` → `add_comment` on notificationConvId: `Also has a Strength trial — coordinate before sending.`
7. **Step F** — compose the draft (draft only, using the segment for touch 1).

## Run summary (final message, one block)
- Drafts created: touch1=N, touch2=N, touch3=N (list lead name + segment for touch1)
- Suppressed for a booked demo: N (list each: lead, meetingTitle, reassigned-to or "not in Front")
- Dedup flags (also in Strength): N (list leads)
- Touch-log comments added: N (First/Follow-up/Final sent-date records)
- Auto-tagged into Trial Outreach (touch 1 sent): N (list leads)
- Sequences completed (tagged Expired Trial after final email): N
- Needs your review: contact-not-found [leads], demo-owner-not-in-Front [leads], parse failures [convo ids]
- If nothing was drafted or flagged, say so explicitly ("No new OS outreach today; N leads already handled/suppressed").

## Companion task — midday log pass (log-only)
A second scheduled task (`os-trial-outreach-log`, weekdays 12:00 CT) runs a LOGGING-ONLY subset of this runbook, so a follow-up sent in the morning gets its sent-date comment / Expired-Trial tag the same day instead of waiting for the next 8:30 run.
It runs ONLY: **Step A** (scan + all skip rules), **Step B** limited to resolving the HubSpot contactId/email (skip the Strength-segment classification — that's only for drafting), **Step E** (touchCount from HubSpot sends), **Step E2** (auto-tag — so a touch 1 sent this morning joins the sequence the same day), **Step H** (touch-log comments), **Step I** (end-of-sequence tag + archive).
It does NOT run **Step C** (demo-check/reassign), **Step D** (dedup comment), or **Step F** (drafting) — it never creates a draft. Every step it runs is idempotent, so re-running at noon never duplicates a comment/tag. All drafting stays in the 8:30 run.

<!-- Installed as scheduled task os-trial-outreach on <date>, manual-only pending validation. -->
<!-- Companion log-only task os-trial-outreach-log installed 2026-10-05, weekdays 12:00 CT. -->
