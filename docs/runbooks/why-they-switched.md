# Why they switched: pulled from sales calls

The `os-accounts-notion-mirror` scheduled task runs this step for each **newly created** account in the Notion OS Accounts Database. It fills `Why they switched` from the customer's own words on earlier sales calls, so the orientation call can confirm the reason instead of starting cold ("On your demo you mentioned ___. Still the main thing?").

Why automate it: sales reps demo Strength and OS together and aren't asked to capture "why OS". When a call doesn't contain an OS-specific reason, the field stays empty and the orientation call asks fresh. That's the normal fallback, not a failure.

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
3. List meetings from 180 days before the Join Date up to 7 days after it:
   ```bash
   python3 .claude/skills/query-avoma/query_avoma.py list --from-date <join-180d>T00:00:00Z --to-date <join+7d>T23:59:59Z --attendee "<match term>"
   ```
   The list reads every page of results and waits out Avoma's rate limit, so a 180-day window can take a few minutes. That's fine for a handful of new accounts.
   **If it returns nothing,** try once more with `--title "<POC first and last name>"`, then with `--title "<a distinctive word from the Account Name>"`. Prospects sometimes book from a different email address, and Avoma names meetings after attendees. Keep only meetings where the POC or the gym clearly took part.
4. Keep sales calls only: demos, discovery, follow-ups and pricing calls. Skip orientation, onboarding and support calls, since those come after the decision. Read at most the 3 most recent qualifying calls:
   ```bash
   python3 .claude/skills/query-avoma/query_avoma.py transcript --uuid <uuid>
   ```

## 2. Extract the reason (strict)

- **Only the prospect's own words.** Ignore the rep's pitch, and ignore agreement like "yeah that'd be great" in reply to a feature the rep described.
- **OS only.** TeamBuildr OS is gym management: booking, scheduling, memberships, billing and payments, the member app, waivers and reporting. Leave out reasons that are only about Strength (programming, training app, athlete tracking, AMS). On a mixed call, keep only the OS part.
- **The reason they're switching or buying,** such as a pain with their current system, something they want in one place, or something they need to run the business. Not general small talk about the gym.
- **No inference.** If no OS-specific reason was stated, write nothing.

## 3. Write it

When a reason was found, set on the new account's page:
- `Why they switched`: `<one or two plain sentences, in their framing>. "<verbatim quote, max 20 words>" (<call type> <YYYY-MM-DD>)`
  - Example: `Wants billing, booking and the member app in one place instead of Mindbody plus spreadsheets. "I'm paying for three things that don't talk to each other" (demo 2026-08-07)`
- `Why source`: `Sales call (unconfirmed)`

If nothing was found, leave both empty.

## 4. Report

Add one line to the task's report: `Why they switched: found for N of M new account(s); empty for [names] (no OS-specific reason on calls | no calls found, including the title fallback)`.
