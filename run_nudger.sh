#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/nudger_$(date +%Y%m%d).log"
mkdir -p "$SCRIPT_DIR/logs"
cd "$SCRIPT_DIR"
source .venv/bin/activate
python nudger.py >> "$LOG_FILE" 2>&1
python reply_collector.py >> "$LOG_FILE" 2>&1
echo "Nudger+reply run at $(date)" >> "$LOG_FILE"
