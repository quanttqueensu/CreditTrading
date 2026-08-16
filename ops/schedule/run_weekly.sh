#!/bin/bash
# Weekly report unit, fired by launchd/cron on Saturday morning.
# Writes ops/reports/weekly_book_<date>.md (read-only roll-up — never trades).
# Runs regardless of holidays: Saturday is never a trading day, and the report
# simply summarizes whatever the daily runs wrote this week.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"
LOG_DIR="$REPO/ops/schedule/logs"
mkdir -p "$LOG_DIR"

ENV_FILE="$REPO/ops/schedule/schedule.env"
# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
PY="${PYTHON:-$PY}"

LOG="$LOG_DIR/weekly_$(date +%F).log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] weekly book report" >> "$LOG"
cd "$REPO"
"$PY" "$REPO/ops/schedule/weekly_book_report.py" >> "$LOG" 2>&1
RC=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] weekly_book_report exit=$RC" >> "$LOG"
exit "$RC"
