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

<!-- Installed as scheduled task os-trial-outreach on <date>, manual-only pending validation. -->
