---
description: Launch the People Registry / Work UI (tasks, projects, people)
---

## Launch

```bash
python3 tools/server.py &
sleep 2 && open http://localhost:8787
```

Server runs at **http://localhost:8787**. The page auto-loads in server mode — no folder picker needed.

## Stop

```bash
pkill -f "tools/server.py"
```

## What it is

Flask server (`tools/server.py`) serving `tools/registry_ui.html`. Provides:
- **Work tab** — tasks and projects (CRUD, backed by `data/tasks.jsonl` and `data/projects_registry.json`)
- **People tab** — people registry (`data/people_registry.json`)
- **Pending tab** — person resolution workflow (only relevant when `data/people_unresolved_state.json` exists)

Data changes made in the UI are committed and pushed to `main` automatically via `git` calls in `server.py`.
