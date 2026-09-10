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
# TCC, MEASURED 2026-09-10. Under launchd this runs as /bin/bash, which has NO
# Full Disk Access -- the same boundary that killed the 09:35 session on
# 2026-07-31 with exit 126. `data/` in prod is a SYMLINK into ~/Desktop, so
# every path under it is on the far side of that boundary. A launchd-triggered
# run at 12:17 produced a healthy-looking 172KB archive containing the ledgers
# and NO `data/cef/cef_borrow.csv`, while the log said only "FAILED rc=1".
#
# That silence was this script's doing, twice over, and both are fixed below:
#   * `tar ... 2>/dev/null` discarded the one message that says WHY the only
#     failure path fired. The backup's log could never explain itself.
#   * `[ -f ]` cannot tell "not there" from "not allowed to look". A denied file
#     was dropped from the archive exactly as if it did not exist.
# The borrow panel is the file that makes this matter: `data/` is gitignored, it
# is forward-only (IBKR publishes no archive), one reading per day, and nothing
# else copies it. A backup that quietly omits it is worse than none, because the
# directory listing looks healthy.
set -uo pipefail
PROD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${BACKUP_DIR:-$HOME/prod-backups}"; mkdir -p "$DEST"
STAMP="$(date +%Y%m%d_%H%M)"
OUT="$DEST/state_${STAMP}.tgz"
ERRLOG="$(mktemp)"

# Classify each optional path as present / absent / UNREADABLE, so a permission
# denial is reported instead of silently becoming an omission.
INCLUDE=(ops/books ops/heartbeat.json)
MISSING=()
UNREADABLE=()
for rel in ops/HALT.md data/cef/nav_fallback_log.csv data/cef/cef_borrow.csv; do
  if [ -r "$PROD/$rel" ]; then
    INCLUDE+=("$rel")
  elif [ -e "$PROD/$rel" ]; then
    UNREADABLE+=("$rel")          # it is there and we cannot read it
  else
    # `-e` is false both when absent and when the DIRECTORY above is unreadable,
    # so probe the parent to tell the two apart rather than assume the benign one.
    if [ -d "$(dirname "$PROD/$rel")" ]; then MISSING+=("$rel")
    else UNREADABLE+=("$rel (parent directory unreadable)"); fi
  fi
done

tar -czf "$OUT" -C "$PROD" "${INCLUDE[@]}" 2>"$ERRLOG"
rc=$?
if [ ${#UNREADABLE[@]} -gt 0 ]; then
  echo "[$(date '+%F %T')] backup INCOMPLETE: could not read ${UNREADABLE[*]}"
  echo "    These are NOT in $OUT. Under launchd this is the TCC boundary:"
  echo "    /bin/bash cannot read ~/Desktop, and prod/data symlinks there."
fi
if [ ${#MISSING[@]} -gt 0 ]; then
  echo "[$(date '+%F %T')] note: not present, so not archived: ${MISSING[*]}"
fi
if [ $rc -ne 0 ] || [ ! -s "$OUT" ]; then
  echo "[$(date '+%F %T')] backup FAILED rc=$rc"
  sed 's/^/    tar: /' "$ERRLOG"      # never discard the reason
  rm -f "$ERRLOG"; exit 1
fi
rm -f "$ERRLOG"
# An archive missing the forward-only borrow panel must not report plain success.
if [ ${#UNREADABLE[@]} -gt 0 ]; then
  echo "[$(date '+%F %T')] wrote $OUT but it is INCOMPLETE — see above"
  exit 2
fi
ls -1t "$DEST"/state_*.tgz | tail -n +91 | xargs -r rm -f
echo "[$(date '+%F %T')] wrote $OUT ($(du -h "$OUT" | cut -f1)); $(ls -1 "$DEST"/state_*.tgz | wc -l | tr -d ' ') kept"
