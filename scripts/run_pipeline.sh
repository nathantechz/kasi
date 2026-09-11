#!/usr/bin/env bash
# run_pipeline.sh — one command to refresh everything.
#   ./scripts/run_pipeline.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
LOG="data/logs/run_${STAMP}.log"
mkdir -p data/logs

echo "== scrape ==" | tee "$LOG"
$PY scripts/scrape_all.py 2>&1 | tee -a "$LOG"

echo "== dashboard ==" | tee -a "$LOG"
$PY scripts/build_dashboard.py 2>&1 | tee -a "$LOG"

echo
echo "Done. Open dashboard/index.html"
echo "Log: $LOG"
