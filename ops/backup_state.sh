#!/bin/bash
# Nightly copy of PROD STATE -- everything that is not code and cannot be
# re-fetched: the shadow ledgers, the heartbeat, the halt file, the order maps,
# broker fills, slippage logs, the NAV fallback log and the borrow panel.
#
#   ~/prod/QUANTT/ops/backup_state.sh            # -> ~/prod-backups/state_<stamp>.tgz
#
# WHY: ledgers were tracked in git until 2026-09-08, which made "git status" in
# the live tree permanently dirty and every promotion a merge with state. They
# are state, not code, so they came out of git. This is what replaces the
# commit as their backup. Keeps the last 90 archives. Prices/NAV parquets are
# NOT included: yfinance serves them again; what it cannot serve is here.
set -uo pipefail
PROD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${BACKUP_DIR:-$HOME/prod-backups}"; mkdir -p "$DEST"
STAMP="$(date +%Y%m%d_%H%M)"
OUT="$DEST/state_${STAMP}.tgz"
tar -czf "$OUT" -C "$PROD" \
    ops/books ops/heartbeat.json \
    $( [ -f "$PROD/ops/HALT.md" ] && echo ops/HALT.md ) \
    $( [ -f "$PROD/data/cef/nav_fallback_log.csv" ] && echo data/cef/nav_fallback_log.csv ) \
    $( [ -f "$PROD/data/cef/cef_borrow.csv" ] && echo data/cef/cef_borrow.csv ) \
    2>/dev/null
rc=$?
if [ $rc -ne 0 ] || [ ! -s "$OUT" ]; then
  echo "[$(date '+%F %T')] backup FAILED rc=$rc"; exit 1
fi
ls -1t "$DEST"/state_*.tgz | tail -n +91 | xargs -r rm -f
echo "[$(date '+%F %T')] wrote $OUT ($(du -h "$OUT" | cut -f1)); $(ls -1 "$DEST"/state_*.tgz | wc -l | tr -d ' ') kept"
