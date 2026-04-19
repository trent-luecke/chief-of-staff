#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/logs/brief_$(date +%Y%m%d).log"
mkdir -p "$SCRIPT_DIR/logs"
exec >> "$LOG_FILE" 2>&1
cd "$SCRIPT_DIR"
git pull --quiet origin main 2>/dev/null || echo "WARN: git pull failed, using existing pipeline cache"
source .venv/bin/activate || { echo "ERROR: .venv not found. Run: python3 -m venv .venv && pip install -r requirements.txt"; exit 1; }
export PATH="$HOME/.nvm/versions/node/v24.13.0/bin:$PATH"
python main.py "$@"
echo "Brief complete at $(date)"
