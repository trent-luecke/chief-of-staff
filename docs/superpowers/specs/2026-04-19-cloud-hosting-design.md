# P0 — Cloud Hosting Design

**Date:** 2026-04-19  
**Status:** Approved, pending implementation

---

## Problem

The system runs on a macOS launchd schedule and requires the local machine to be on. Since reliable machine availability can't be guaranteed, the brief runs inconsistently. Everything — scheduling, data persistence, auth — needs to move to a hosted environment that runs unconditionally.

---

## Architecture

**GitHub Actions** (free tier) replaces macOS launchd as the scheduler. The private repo is the persistence layer — `data/` changes are committed back after each run. Google APIs move from the `gws` CLI to `google-api-python-client` with a service account.

```
GitHub Actions (cron: 7am CDT/CST)
  ├── actions/checkout         → pulls latest data/ from repo
  ├── pip install
  ├── python main.py           → runs brief, sends email
  └── git commit data/ + push  → persists state for next run
```

**What stays the same:** all processors, brief generation, Anthropic API, Notion (MCP cache model), Slack, email sending, every output. The only changes are how Google APIs are called and where the process runs.

---

## Scheduling

**File:** `.github/workflows/brief.yml`

```yaml
name: Daily Brief

on:
  schedule:
    - cron: "0 12 * * *"  # 7am CDT (UTC-5); change to "0 13 * * *" in Nov for CST
  workflow_dispatch:        # manual trigger for testing

jobs:
  run-brief:
    runs-on: ubuntu-latest
    env:
      TZ: America/Chicago

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - run: pip install -r requirements.txt

      - name: Run brief
        env:
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
        run: python main.py

      - name: Persist data
        run: |
          git config user.name "chief-of-staff[bot]"
          git config user.email "noreply@github.com"
          git add data/
          git diff --cached --quiet || git commit -m "chore: daily data update $(date +%Y-%m-%d)"
          git push
```

**`workflow_dispatch`** provides a manual trigger button in the GitHub Actions UI — used for testing and mid-day re-runs.

**Timezone note:** cron in GitHub Actions is UTC-only. `0 12 * * *` = 7am CDT (Apr–Oct). Update to `0 13 * * *` in November for CST.

---

## Google Auth — Service Account

**One-time setup:**

1. In Google Cloud Console: create a service account, enable domain-wide delegation
2. In Google Workspace Admin Console, grant the service account these scopes:
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.modify`
3. Download the service account JSON key → store as `GOOGLE_SERVICE_ACCOUNT_JSON` GitHub Secret

**`lib/google_auth.py`** (new file):
```python
import json
import os
from google.oauth2 import service_account

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

def get_google_credentials(scopes: list[str], user_email: str):
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=scopes
    )
    return credentials.with_subject(user_email)
```

`with_subject` impersonates the Workspace user so Calendar and Gmail return the right account's data.

---

## Collector Rewrites

### `collectors/calendar.py`

Replaces `gws calendar` subprocess calls with `google-api-python-client`. Function signatures and return types (`list[CalendarEvent]`) unchanged — nothing downstream breaks.

```python
from googleapiclient.discovery import build
from lib.google_auth import get_google_credentials, CALENDAR_SCOPES

def fetch_two_day_events(config) -> list[CalendarEvent]:
    creds = get_google_credentials(CALENDAR_SCOPES, config["email"])
    service = build("calendar", "v3", credentials=creds)
    # Same query logic: today + tomorrow, all calendar_ids from config
    ...
```

### `collectors/gmail.py`

Replaces `gws gmail` subprocess calls with direct Gmail API calls. Same return types.

```python
from googleapiclient.discovery import build
from lib.google_auth import get_google_credentials, GMAIL_SCOPES

def fetch_threads_needing_attention(config) -> list[EmailThread]:
    creds = get_google_credentials(GMAIL_SCOPES, config["email"])
    service = build("gmail", "v1", credentials=creds)
    ...
```

### `outputs/sender.py`

Replaces `gws gmail send` with `service.users().messages().send()` using the same base64-encoded MIME message already constructed.

### `collectors/gmail_personal.py` — removed

Personal Gmail cannot be accessed via domain-wide delegation (personal accounts are outside the Workspace domain). This collector is removed entirely. Personal items will be captured via quick capture (existing) or the P4 two-way interface.

**`main.py` change required:** remove the `fetch_personal_emails()` call and any reference to `PersonalEmail` results in the brief prompt build. The `personal_allowlist.json` config file can be left in place but is unused.

---

## GitHub Secrets

| Secret | Value |
|--------|-------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full service account key JSON (downloaded from GCP) |
| `ANTHROPIC_API_KEY` | Current value from `.env` |
| `SLACK_BOT_TOKEN` | Current value from `.env` |

No Notion token — pipeline data is accessed via Claude Code MCP and cached in `data/pipeline_cache.json`, which persists via git commit-back. Manual re-sync via Claude Code still works unchanged.

---

## Data Persistence

`data/` is committed back to the repo at the end of each run. The git commit only fires if files actually changed (`git diff --cached --quiet ||` guard).

**Files persisted this way:**
- `data/state/` — daily email/notion ID snapshots
- `data/people/` — contact profiles
- `data/issues.json` — multi-day issue tracker
- `data/pipeline_cache.json` — Notion pipeline cache
- `data/meeting_memory/` — session notes
- `data/drafts/` — generated email drafts
- `data/memory/` — P3 cross-day memory files (observations, synthesized memories)

**`.gitignore` audit required:** currently some `data/` subdirectories are gitignored (logs, credentials, output). Ensure `data/state/`, `data/people/`, `data/issues.json`, and `data/pipeline_cache.json` are tracked.

---

## Notion (Unchanged)

Pipeline cache syncs manually via Claude Code MCP (`notion_pipeline.py`). The updated `pipeline_cache.json` gets committed to the repo. GitHub Actions reads from the committed cache on each run. The existing 7-day staleness warning in the brief handles infrequent syncs.

---

## New Dependencies

Add to `requirements.txt`:
```
google-api-python-client>=2.0.0
google-auth>=2.0.0
```

Remove from `requirements.txt` (if present):
- Any `gws` CLI wrapper packages

---

## What This Does Not Do

- **`watcher.py` and `nudger.py` not migrated** — these two scripts (pipeline email watcher, post-meeting nudger) also run via launchd and still require the local machine. Migrating them is a follow-on task after the daily brief is stable in Actions. For now they either run locally when the machine is on, or are temporarily disabled.
- **No auto-timezone adjustment** — cron schedule requires a manual comment update in November when CDT→CST. A future improvement could use a GitHub Actions matrix or a timezone-aware scheduler.
- **No retry on failure** — if the brief fails (API timeout, Claude error), GitHub Actions marks the run failed and sends an email notification to the repo owner. No automatic retry. Acceptable for now.
- **No dashboard** — `output/dashboard.html` is currently gitignored and not committed back. The dashboard remains local-only until P6.
