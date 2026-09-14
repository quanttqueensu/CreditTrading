#!/bin/bash
# Render (and, only when explicitly asked, stage/enable) the launchd jobs.
#
#   ./install.sh                    render plists into ops/schedule/rendered/ + lint. NOTHING is installed.
#   ./install.sh --hour 16 --minute 40 --weekly-hour 9 --weekly-minute 0
#                                   same, custom LOCAL fire times (defaults shown; must be after the US close)
#   ./install.sh --install          ALSO copy rendered plists to ~/Library/LaunchAgents (still not loaded)
#   ./install.sh --enable           ALSO `launchctl bootstrap` them (the live switch — human only)
#   ./install.sh --disable          bootout + remove the plists from ~/Library/LaunchAgents
#
# The agent that built this ran only the default render mode. --install/--enable
# are for the human, per DEPLOY_CONTEXT ("the human enables it").
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHED="$REPO/ops/schedule"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"
HOUR=16; MINUTE=40; WHOUR=9; WMINUTE=0
DO_INSTALL=0; DO_ENABLE=0; DO_DISABLE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --hour)          HOUR="$2"; shift 2 ;;
        --minute)        MINUTE="$2"; shift 2 ;;
        --weekly-hour)   WHOUR="$2"; shift 2 ;;
        --weekly-minute) WMINUTE="$2"; shift 2 ;;
        --install)       DO_INSTALL=1; shift ;;
        --enable)        DO_INSTALL=1; DO_ENABLE=1; shift ;;
        --disable)       DO_DISABLE=1; shift ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

AGENTS="$HOME/Library/LaunchAgents"
DAILY=com.quantt.book.daily.plist
WEEKLY=com.quantt.book.weekly.plist
GUI="gui/$(id -u)"

if [ "$DO_DISABLE" = 1 ]; then
    for P in "$DAILY" "$WEEKLY"; do
        launchctl bootout "$GUI" "$AGENTS/$P" 2>/dev/null || true
        rm -f "$AGENTS/$P"
        echo "disabled + removed $AGENTS/$P"
    done
    exit 0
fi

if [ "$HOUR" -lt 16 ]; then
    echo "WARNING: daily hour $HOUR is before 16:00 — the US close is 4:00pm ET." >&2
    echo "         Only do this if this Mac's local time zone is WEST of ET."   >&2
fi

mkdir -p "$SCHED/rendered" "$SCHED/logs"
render() {  # $1=template $2=out
    sed -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$PY|g" \
        -e "s|__HOUR__|$HOUR|g" -e "s|__MINUTE__|$MINUTE|g" \
        -e "s|__WHOUR__|$WHOUR|g" -e "s|__WMINUTE__|$WMINUTE|g" \
        "$1" > "$2"
    plutil -lint "$2"
}
render "$SCHED/$DAILY.template"  "$SCHED/rendered/$DAILY"
render "$SCHED/$WEEKLY.template" "$SCHED/rendered/$WEEKLY"
chmod +x "$SCHED/run_after_close.sh" "$SCHED/run_weekly.sh"

echo ""
echo "Rendered (NOT installed):"
echo "  $SCHED/rendered/$DAILY   (weekdays ${HOUR}:$(printf '%02d' "$MINUTE") local)"
echo "  $SCHED/rendered/$WEEKLY  (Saturday ${WHOUR}:$(printf '%02d' "$WMINUTE") local)"

if [ "$DO_INSTALL" = 1 ]; then
    mkdir -p "$AGENTS"
    cp "$SCHED/rendered/$DAILY" "$SCHED/rendered/$WEEKLY" "$AGENTS/"
    echo "staged into $AGENTS (not yet loaded)"
fi

if [ "$DO_ENABLE" = 1 ]; then
    launchctl bootstrap "$GUI" "$AGENTS/$DAILY"
    launchctl bootstrap "$GUI" "$AGENTS/$WEEKLY"
    echo "ENABLED. Verify: launchctl print $GUI/com.quantt.book.daily | head"
else
    cat <<EOF

To enable (human step — see ops/schedule/README.md):
  $SCHED/install.sh --install     # stage into ~/Library/LaunchAgents
  $SCHED/install.sh --enable      # stage + launchctl bootstrap (goes live)
Cron alternative (crontab -e):
  $((MINUTE)) $((HOUR)) * * 1-5 /bin/bash $SCHED/run_after_close.sh
  $((WMINUTE)) $((WHOUR)) * * 6 /bin/bash $SCHED/run_weekly.sh
EOF
fi
