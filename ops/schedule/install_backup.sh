#!/bin/bash
# Render (and, only when explicitly asked, stage/enable) the nightly state backup.
#
#   ./install_backup.sh                 render to rendered_backup/ + lint. NOTHING installed.
#   ./install_backup.sh --hour 23 --minute 55       custom local fire time
#   ./install_backup.sh --prod ~/prod/QUANTT        which tree to archive (default)
#   ./install_backup.sh --install       ALSO copy to ~/Library/LaunchAgents (not loaded)
#   ./install_backup.sh --enable        ALSO bootstrap it  (LIVE -- human only)
#   ./install_backup.sh --disable       bootout + remove
#
# WHY THIS IS SEPARATE FROM install.sh
# ------------------------------------
# ops/schedule/install.sh renders com.quantt.book.daily / .weekly, which are the
# PRE-2026-07-31 jobs. Nothing loads them any more -- the loaded set is
# com.quantt.{cef,phase0,benchmarks,collect,watchdog,weekly}.daily plus
# ibgateway/dashboard/awake -- and CLAUDE.md landmine #2 records that
# ops/schedule/rendered/*.plist are stale and point at a repo path that no
# longer exists. Extending install.sh would have filed this job in that same
# dead directory, next to two plists that lie about what runs. So this
# installer stands alone and targets the live mechanism: a plist in
# ~/Library/LaunchAgents, bootstrapped into the GUI domain.
#
# It renders into rendered_backup/ rather than rendered/ for the same reason:
# rendered/ is documented as stale, and a live artifact must not be filed with
# artifacts nobody trusts.
#
# --enable is the HUMAN's switch. (A PreToolUse guard used to block an agent from
# running launchctl at all -- removed 2026-09-10 -- because a stopped agent is a
# silently non-trading book and that failure has already cost this project a
# month. The reasoning outlived the guard, so the convention holds here. An
# agent may run this script only in its default render mode; --install,
# --enable and --disable are for a person. Note also that the only label this
# script ever touches is com.quantt.backup.daily: it can neither start nor stop
# a trading job, and it is not a path around that hook.
set -euo pipefail

SCHED="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPPORT="$HOME/Library/Application Support/quantt"
AGENTS="$HOME/Library/LaunchAgents"
PLIST=com.quantt.backup.daily.plist
LABEL=com.quantt.backup.daily
GUI="gui/$(id -u)"

PROD="$HOME/prod/QUANTT"
HOUR=23; MINUTE=55
DO_INSTALL=0; DO_ENABLE=0; DO_DISABLE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prod)    PROD="$2"; shift 2 ;;
        --hour)    HOUR="$2"; shift 2 ;;
        --minute)  MINUTE="$2"; shift 2 ;;
        --install) DO_INSTALL=1; shift ;;
        --enable)  DO_INSTALL=1; DO_ENABLE=1; shift ;;
        --disable) DO_DISABLE=1; shift ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [ "$DO_DISABLE" = 1 ]; then
    launchctl bootout "$GUI" "$AGENTS/$PLIST" 2>/dev/null || true
    rm -f "$AGENTS/$PLIST"
    echo "disabled + removed $AGENTS/$PLIST"
    exit 0
fi

# The whole job is one path. If it is wrong the job silently archives nothing,
# which is the exact failure this backup exists to insure against -- so refuse
# to render rather than emit a plist that looks fine and tars air.
[ -x "$PROD/ops/backup_state.sh" ] || {
    echo "ERROR: $PROD/ops/backup_state.sh missing or not executable." >&2
    echo "       That path is what the job runs; rendering it wrong gives a" >&2
    echo "       job that fails silently every night. Pass --prod <tree>." >&2
    exit 2
}

mkdir -p "$SCHED/rendered_backup" "$SUPPORT"
OUT="$SCHED/rendered_backup/$PLIST"
sed -e "s|__PROD__|$PROD|g" -e "s|__SUPPORT__|$SUPPORT|g" \
    -e "s|__HOUR__|$HOUR|g" -e "s|__MINUTE__|$MINUTE|g" \
    "$SCHED/$PLIST.template" > "$OUT"
plutil -lint "$OUT"

echo ""
echo "Rendered (NOT installed):"
echo "  $OUT"
echo "  archives : $PROD  ->  \${BACKUP_DIR:-\$HOME/prod-backups}/state_<stamp>.tgz"
echo "  fires    : every day at ${HOUR}:$(printf '%02d' "$MINUTE") local"
echo "  log      : $SUPPORT/launchd_backup.log"

if [ "$DO_INSTALL" = 1 ]; then
    mkdir -p "$AGENTS"; cp "$OUT" "$AGENTS/"
    echo "staged into $AGENTS (not yet loaded)"
fi

if [ "$DO_ENABLE" = 1 ]; then
    launchctl bootout "$GUI" "$AGENTS/$PLIST" 2>/dev/null || true
    launchctl bootstrap "$GUI" "$AGENTS/$PLIST"
    echo "ENABLED. Verify:  launchctl print $GUI/$LABEL | head -20"
else
    cat <<EOF

To enable (human step):
  $SCHED/install_backup.sh --install    # stage into ~/Library/LaunchAgents
  $SCHED/install_backup.sh --enable     # stage + bootstrap (goes live)

Verify after enabling, without waiting for ${HOUR}:$(printf '%02d' "$MINUTE"):
  launchctl print $GUI/$LABEL | head -20
  launchctl kickstart -p $GUI/$LABEL     # fire it once, now
  ls -lt \${BACKUP_DIR:-\$HOME/prod-backups}/state_*.tgz | head -3
EOF
fi
