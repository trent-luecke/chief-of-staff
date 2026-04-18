#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/watcher_$(date +%Y%m%d).log"
mkdir -p "$SCRIPT_DIR/logs"
cd "$SCRIPT_DIR"
source .venv/bin/activate
export PATH="$HOME/.nvm/versions/node/v24.13.0/bin:$PATH"
python watcher.py >> "$LOG_FILE" 2>&1
echo "Watcher run at $(date)" >> "$LOG_FILE"
