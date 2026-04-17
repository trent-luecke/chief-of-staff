#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/brief_$(date +%Y%m%d).log"
mkdir -p "$SCRIPT_DIR/logs"
cd "$SCRIPT_DIR"
source .venv/bin/activate
python main.py "$@" >> "$LOG_FILE" 2>&1
echo "Brief complete at $(date)" >> "$LOG_FILE"
