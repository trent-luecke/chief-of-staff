---
name: open-registry-ui
description: Opens the people registry UI HTML artifact in Chrome. Trigger phrases: "open registry UI", "open people tracker", "open the artifact", "open resolution UI".
---

## Steps

1. Sync observations from R2 to local disk so the UI can show observation snippets:

```bash
python3 scripts/sync_observations_local.py
```

2. Open the file in Chrome:

```bash
open -a "Google Chrome" "$(git rev-parse --show-toplevel)/tools/registry_ui.html"
```

3. Tell the user: "Registry UI opened in Chrome. Grant folder access to the repo root when prompted, then work through your pending resolutions. When done, say **reconcile pending people resolutions** to apply decisions."
