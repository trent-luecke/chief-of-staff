---
name: open-registry-ui
description: Opens the entity UI (people + projects) in Chrome. Trigger phrases: "open registry UI", "open people tracker", "open the artifact", "open resolution UI", "open entity UI", "open project UI".
---

## Steps

1. Sync observations from R2 to local disk so the UI can show observation snippets:

```bash
export $(grep -v '^#' .env | xargs) && python3 scripts/sync_observations_local.py
```

2. Start the entity UI server if it isn't already running:

```bash
REPO=$(git rev-parse --show-toplevel)
if ! lsof -ti:8787 > /dev/null 2>&1; then
  cd "$REPO" && python3 tools/server.py &>/tmp/entity-ui-server.log &
  sleep 1
fi
```

3. Open the UI in Chrome:

```bash
open -a "Google Chrome" "http://localhost:8787"
```

4. Tell the user: "Entity UI opened at http://localhost:8787. The People tab works as before (grant folder access when prompted). The Projects tab shows active projects with their open tasks — it reads live from the local server. When done with people resolutions, say **reconcile pending people resolutions** to apply decisions."
