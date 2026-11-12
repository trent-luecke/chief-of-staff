# Why they switched: pulled from sales calls

The `os-accounts-notion-mirror` scheduled task runs this step for each **newly created** account in the Notion OS Accounts Database. It fills `Why they switched` from the customer's own words on earlier sales calls, so the orientation call can confirm the reason instead of starting cold ("On your demo you mentioned ___. Still the main thing?").

Why automate it: sales reps demo Strength and OS together and aren't asked to capture "why OS". When the prospect never stated a reason, the field stays empty and the orientation call asks fresh. That's the normal fallback, not a failure.

**Read-only on Avoma. The only write is two properties on the new account's page, and never when `Why they switched` already has a value.**

## 1. Find their earlier calls

1. Get the account's POC email from the Client List (Active Customers tab), matching by Account Name:
   ```bash
   cd /Users/trentluecke/dev/Claude-Projects/chief-of-staff && python3 scripts/checkins_sheet.py accounts
   ```
2. Pick the match term:
   - Use `@<domain>` when the email's domain is the gym's own.
   - Use the full email address for freemail (gmail, yahoo, outlook, hotmail, icloud, aol, live, me, msn).
   - Never use teambuildr.com.
3. **Look in the demo log first.** `data/deal_events.jsonl` on `origin/main` has a line for every demo the pipeline detected (since 2026-08-18). Keep lines with `kind` = `demo` whose `email` or `payload.contact_emails` matches the match term, and whose `timestamp` is before the Join Date. Each one's `payload.avoma_uuid` is the meeting to read. This is exact and fast. Use it whenever it has a match.
4. **Only if the demo log has nothing,** search Avoma for the 30 days before the Join Date. Wider windows run past the tool's page cap and come back incomplete.
   ```bash
   python3 .claude/skills/query-avoma/query_avoma.py list --from-date <join-30d>T00:00:00Z --to-date <join>T00:00:00Z --attendee "<match term>"
   ```
   If that finds no call with a recording, try `--title "<POC first and last name>"`, then `--title "<a distinctive word from the Account Name>"`, over the same window. Keep only meetings where someone from the gym took part. The buyer isn't always the POC on the Client List; a colleague on the gym's domain counts.
5. **Read only calls before the Join Date** (sales: demo, discovery, follow-up, pricing). Calls on or after the join date are setup or orientation. Read at most the 3 most recent:
   ```bash
   python3 .claude/skills/query-avoma/query_avoma.py transcript --uuid <uuid>
   ```
   "No transcript for this meeting" means the call wasn't recorded. Skip it; it isn't an error.

## 2. Extract the reason

Its job is to give the orientation host an opener ("On your demo you mentioned ___. Still the main thing?"), which the host confirms live. So capture **whatever reason the prospect gave for buying**, even when it covers Strength and OS together, and label which product it's about. (Loosened 2026-11-12: demos pitch both products, so OS-only reasons were rare. Trent approved.)

- **Who's speaking:** speaker labels (S0/S1) flip between calls. The rep works for TeamBuildr and does the pitching and screen-sharing; check the attendee emails. Everyone else on the call is the prospect side.
- **Only the prospect's own words.** Ignore the rep's pitch. Agreement with something the rep proposed ("yeah, that'd be great") doesn't count on its own; look for where they raised it themselves.
- **A reason, not a question.** "Do you have booking and payments?" is curiosity, not a reason. A reason is a pain with their current setup, a cost or simplicity goal ("fewer apps", "cut cost"), or something they need to run the business. Buyers with no system before (a school buying for the first time) have a need rather than a switch; write the need.
- **Label it:**
  - **(OS)** for gym management: booking, scheduling, memberships, billing and payments, the member app, waivers, reporting.
  - **(Strength)** for programming, the training app, athlete tracking, AMS.
  - **(both)** when the reason covers the bundle, like cost or fewer apps.
- **No inference.** If they never stated a reason, write nothing.

## 3. Write it

When a reason was found, set on the new account's page:
- `Why they switched`: `<one or two plain sentences, in their framing> (<OS|Strength|both>). "<verbatim quote, max 20 words>" (<call type> <YYYY-MM-DD>)`
  - Example: `Wants to cut cost and run on fewer apps; unhappy with their current platform's training app (both). "I'm trying to cut cost, and then on top of that, minimize the amount of apps that we have" (demo 2026-11-10)`
- `Why source`: `Sales call (unconfirmed)`

If nothing was found, leave both empty.

## 4. Report

Add one line to the task's report: `Why they switched: found for N of M new account(s); empty for [names] (no reason stated on calls | no recorded calls found)`.
