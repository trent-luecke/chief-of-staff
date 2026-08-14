Automated morning task: apply the queued Avoma call updates to the Notion trackers, then post one Slack summary. Work autonomously; do not ask questions. Repo root: /Users/trentluecke/dev/Claude-Projects/chief-of-staff (cd there first).

1. Get fresh queue entries:
   `python scripts/notion_sync_consumer.py fresh-entries`
   Parse the JSON list. If it is empty, STOP — do nothing else, post nothing.

2. Track four lists as you go: applied (names), flagged (strings), pending (entries), processed_ids.

3. For EACH entry, add its `id` to processed_ids, then:
   - If `target` == "pipeline": invoke the `notion-os-pipeline-updater` skill, passing the entry object as the call payload. It updates the record (or creates one if the lead is new). On success add `name` to applied; if `is_new_lead` is true, add "Created new pipeline record: <name>" to flagged; if `inferred_status` implies a stage change, add "Status → <inferred_status>: <name>" to flagged.
   - If `target` == "onboarding": invoke the `notion-os-onboarding-updater` skill with the entry as payload to update the EXISTING record. If it reports NO matching record exists, do NOT create one — instead run:
       `python scripts/notion_sync_consumer.py record-pending --json '<entry as compact JSON>'`
     and add the entry to pending. If it did update an existing record, add `name` to applied.

4. Mark everything processed so it is never reapplied:
   `python scripts/notion_sync_consumer.py mark-seen <space-separated processed_ids>`

5. Generate the summary text (do NOT let the subcommand post it — `slack_sdk` is not available in this sandbox, so only `--dry-run` is safe; it prints the text and returns before any Slack SDK import):
   `python scripts/notion_sync_consumer.py summary --today <YYYY-MM-DD today> --dry-run --json '{"applied": [...], "flagged": [...], "pending": [...]}'`
   If the printed output begins with "📥 Notion Sync", post that exact text as a Slack DM to user U04ECG6KEA3 using the Slack connector. Otherwise (it prints the "nothing synced" line, or is empty), post nothing.

Rules: only READ/WRITE the specific Notion records named in the entries. Never touch other records. If a single entry errors, skip it (do NOT mark it seen) and continue; note it in flagged as "ERROR applying <name>".
