#!/bin/bash
# Nightly copy of PROD STATE -- everything that is not code and cannot be
# re-fetched: the shadow ledgers, the heartbeat, the halt file, the order maps,
# broker fills, slippage logs, the NAV fallback log and the borrow panel.
#
#   ~/prod/QUANTT/ops/backup_state.sh            # -> ~/prod-backups/state_<stamp>.tgz
#
# WHY: the ledgers are state, not code. Tracking them makes "git status" in the
# live tree permanently dirty and every promotion a merge with state, which is
# why ops/promote.sh carries pathspec exclusions and --merge. They are meant to
# come out of git, and this job is what replaces the commit history as their
# off-machine copy. Keeps the last 90 archives. Prices/NAV parquets are NOT
# included: yfinance serves them again; what it cannot serve is here.
#
# STATUS 2026-09-10: they are STILL TRACKED — 30 files under ops/books/cef_live,
# 74 under benchmarks_live, 20 under phase0_live, plus ops/heartbeat.json.
# Untracking is deliberately gated on THIS job being scheduled, because until it
# is, git history is their only backup and removing them would leave none. Do
# not describe the untracking as done until `git ls-files ops/books/cef_live`
# is empty. The .gitignore stanza and the ordering (untrack in DEV, then tag and
# promote — never in the detached prod worktree) are written up in .gitignore.
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
