# Churn sync — Runbook

Version-controlled step of the daily `os-accounts-notion-mirror` scheduled task. Marks accounts **Churned** in the Notion OS Accounts Database when Trent logs them in the cancellations sheet, and tells him which ones are still Active on the Client List (which drives MRR and the check-in program). The task prompt fetches this file from `origin/main` each run.

## Why it exists

The Notion mirror copies the Client List's active accounts and never updates existing pages, and nothing read the cancellations sheet. On 2026-11-23 seven cancelled gyms were still Active everywhere, and four got quarterly check-in drafts.

## Sources

- **Cancellations sheet** "TEAMBUILDR OS Non-Renewal/Cancellation Feedback": `1BYMMVKw19Y9pwp7oFYMvUC4Webk-NI-Y-kevj7CX6D4`, tabs `MONTHLY Cancellations` and `ANNUAL Non-Renewals`. READ ONLY. Read it only with `scripts/checkins_sheet.py cancellations` (Sheets API, full tab). Never use the Google Drive connector's `read_file_content`, which returns a sample of rows.
- **OS Accounts Database**: `collection://3d124bca-36d7-8069-a2fa-000b83deae3d`. Use the full `{Account Name, Status}` list the mirror already paged in its step 3 (view mode). Do not read it again.
- **Client List actives**: the mirror's `accounts_data.json` from step 1.

## HARD RULES

- Never write to the cancellations sheet or the Client List.
- The only Notion write is `Status` → `Churned` on accounts the CLI returns in `to_churn`. Never set an account back to Active. Never touch any other property.
- Matching is exact and lives in the CLI (`lib/churn.py`). Never match names yourself and never act on `near_matches`.
- If more than 5 accounts come back in `to_churn`, change nothing and report the names. A batch that large almost always means a bad read.

## Steps

1. Export the code from `origin/main` (never run from Trent's working checkout):
   ```
   R=/Users/trentluecke/dev/Claude-Projects/chief-of-staff
   T=$(mktemp -d) && git -C $R fetch origin main -q && git -C $R archive origin/main lib/__init__.py lib/checkins.py lib/account_match.py lib/churn.py scripts/checkins.py scripts/checkins_sheet.py lib/google_auth.py | tar -x -C $T
   ```
2. `python3 $T/scripts/checkins_sheet.py cancellations > $T/canc.json`. If it exits 2, or `count` is 0, skip the rest of this runbook and report "churn sync skipped: <error or 'cancellations sheet read 0 rows'>".
3. Build the payload and run the rules:
   ```
   echo '{"today": "<today, America/Chicago, YYYY-MM-DD>", "cancellations": <canc.json rows>, "accounts": [{"name": "<Account Name>", "status": "<Status>"}, ...]}' | python3 $T/scripts/checkins.py churn
   ```
   Exit 2 means bad input: stop and report it.
4. For each `to_churn` entry (subject to the 5-account cap), `notion-update-page` the matching OS Accounts page with `{"Status": "Churned"}`.
5. **Still on the Client List:** every account in `to_churn` or `already_churned` whose name is in `accounts_data.json` (exact Account Name) is still Active on the Client List.
6. **Slack DM to Trent** (`U04ECG6KEA3`), only when step 4 changed something, step 5 found anything, or `returned_but_churned` / `near_matches` is non-empty. Otherwise send nothing. Format: bold title `**Churn sync, <date>**`, then these `#` sections (drop empty ones), one account per bullet, no IDs or URLs:
   - `# Marked Churned in Notion: <n>`: `<account> - cancelled <date>`
   - `# Still Active on the Client List: <n>`: `<account> - set Status to cancelled and clear Price on All OS Customers (MRR and check-ins still count it)`
   - `# Came back but still Churned in Notion: <n>`: `<account> - sheet says they returned; set Notion Status back to Active if so`
   - `# Possible matches to check: <n>`: `<cancelled name> - looks like <candidates>; rename one side to match exactly if it's the same gym`
7. Add one line to the mirror's report: `Churn sync: marked N churned; M still Active on Client List.`
