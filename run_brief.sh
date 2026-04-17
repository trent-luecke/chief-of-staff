#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/brief_$(date +%Y%m%d).log"
mkdir -p "$SCRIPT_DIR/logs"
exec >> "$LOG_FILE" 2>&1
cd "$SCRIPT_DIR"
source .venv/bin/activate || { echo "ERROR: .venv not found. Run: python3 -m venv .venv && pip install -r requirements.txt"; exit 1; }
python main.py "$@"
echo "Brief complete at $(date)"
