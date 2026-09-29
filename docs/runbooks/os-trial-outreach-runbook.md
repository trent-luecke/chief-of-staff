# OS Trial Outreach — Daily Runbook

Version-controlled source of the `os-trial-outreach` claude.ai scheduled task. Runs in-session at 8:30 AM CT. Draft-only: it never sends. Any behavior change = edit this file, then `update_scheduled_task` with the new prompt.

## Config
- OS inbox (drafting target): `inb_346ip`
- Strength inbox (read-only, dedup): `inb_25ub`
- Send-from Front channel: `cha_30ds1` (trent@teambuildr.com, gmail)
- BCC on every draft: `4238329@bcc.hubspot.com`
- Trent Front teammate: `tea_2glc1` (HubSpot owner 294790730)
- Calendly CTA: `https://calendly.com/trent-luecke/30-minute-tbos-demo`
- Trial-window scan: notifications created in the last 16 days
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
| Rachel Hodgson (303992238) | tea_2grep — NEEDS CONFIRM (Front name is "Rachel Newman") |

**Unmappable active demo owners (no Front account → suppress + flag, never auto-assign):** Nick Hawkins (47696639), Shane Gring (77519053), Josh Beedle (84308332), Duncan Richey (87381684), Penn Riney (93606412), Alec Metzger (95076082), Eduardo/Eddy Poveda (95183716), John Rowbotham (96600088), Tyler Samani-Sprunk (3987522), Haley Mathis (47680956), Dawn Mathis* (39493992). Non-human owners (Info TeamBuildr 217718845, GymStudio Info 415599761, Analytics Account) also never receive assignments.

Rule: if a demo's `hubspot_owner_id` is in the map → reassign to that Front teammate (unless it's Trent). Otherwise → suppress the lead and flag "demo owner <name> not in Front — assign manually."

## Step A — Scan OS trials
1. Front `search_conversations`: scope `all_inboxes`, filters.inboxId=`inb_346ip`, query "New Account". Page until you have all conversations whose inbound notification is within the trial window (see step 4).
2. Keep conversations whose subject is exactly "TeamBuildr OS - New Account" and whose `assigneeId` is null (untouched) or `tea_2glc1` (Trent's). Skip any assigned to another teammate (out of Trent's lane). NOTE: include BOTH open and archived — Trent's in-flight leads are archived + team-snoozed + assigned to himself, so status is NOT a filter.
3. For each kept conversation, `read_conversation` (limit 5) and parse the `message_inbound` content:
   `New Account Created: Name: <name> Email: <email> Org. Name: <org> Studio Num.: <id> Trial Exp: <MM/DD/YYYY> Contact Number: <phone> HubSpot: View Contact ...`
   Extract: email, name, org, trialExpiration (parse MM/DD/YYYY). Record notificationConvId + notificationAssigneeId.
4. Active-window gate: process a lead only if `trialExpiration >= today - 1 day` (trial not already lapsed). Drop expired trials.
5. If the body does not parse (format drift), skip the lead and add it to the summary "parse failures". Never draft from a half-parsed record.

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
2. Matching emails = hs_email_status=SENT AND hs_email_subject contains "TeamBuildr OS: Welcome!" (this also matches "Re: …" replies and "Front: …" prefixed logs; it excludes other teams' templates like "Book your TeamBuildr Overview").
   touchCount = number of DISTINCT CALENDAR DAYS among matching emails (dedupes double-logged Front/BCC copies of one send). lastSend = the latest matching day.
3. nextTouch:
   - 0 → 1
   - 1 and (today − lastSend ≥ 7 days) → 2, else null
   - 2 and (today ≥ trialExpiration − 1 day) → 3, else null
   - 3 → null (done)
4. Front `search_conversations` scope my_conversations, query=<lead.email>: if a "TeamBuildr OS: Welcome!" thread exists, outreachConvId = its id; read_conversation → if `drafts` non-empty, hasPendingDraft=true → skip this lead (never stack drafts).
5. If no Front thread exists (lead first emailed via HubSpot), touches 2/3 go out as a fresh outbound to the lead (not a threaded reply). Correct recipient; threading differs only for launch-era in-flight leads.

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

### Touch 2 (nextTouch=2): REPLY on outreachConvId (or NEW outbound subject "Re: TeamBuildr OS: Welcome!" to lead.email if no Front thread)
create_draft: conversationId=outreachConvId, bcc=[4238329@bcc.hubspot.com], shared=false. Body:
```
Hey {{first_name}}!

Just wanted to follow up and push this to the top of your inbox. Hope you're enjoying your trial with us so far.

Got a question? Hit reply. Or if you're ready to dive in:

👉 Grab 30 minutes on my calendar [https://calendly.com/trent-luecke/30-minute-tbos-demo]
```

### Touch 3 (nextTouch=3): REPLY on outreachConvId (or NEW outbound as above)
create_draft: conversationId=outreachConvId, bcc=[4238329@bcc.hubspot.com], shared=false. Body:
```
Hey {{first_name}}!

As your trial starts to come to a close, I wanted to reach out one last time. It's not too late to get yourself acquainted with TeamBuildr OS and start setting up your account.

If now isn't a great time, let me know, but if you're interested in chatting, I'll leave my link below.

👉 Let's get you set up right before your trial ends. [https://calendly.com/trent-luecke/30-minute-tbos-demo]

We'd love to be part of your story.
```

<!-- Installed as scheduled task os-trial-outreach on <date>, manual-only pending validation. -->
