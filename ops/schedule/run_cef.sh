#!/bin/bash
# Credit CEF discount sleeve — daily unit, fired after the US close on trading days.
#
# Order matters: refresh price AND NAV first, because the entire signal is
# price-minus-NAV and a stale NAV is not a cheap fund, it is a blind one. If the
# refresh fails the run aborts rather than trading on yesterday's discounts.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"
CAL="$REPO/ops/schedule/nyse_calendar.py"
LOGDIR="$REPO/ops/schedule/logs"; mkdir -p "$LOGDIR"
TODAY="$(date +%Y-%m-%d)"
LOG="$LOGDIR/cef_${TODAY}.log"
stamp(){ echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

ENV_FILE="${SCHEDULE_ENV:-$REPO/ops/schedule/cef.env}"
# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
DRY_RUN="${DRY_RUN:-1}"; EXECUTION="${EXECUTION:-simulator}"
BOOK="${BOOK:-$REPO/ops/books/cef_discount_book.json}"
BOOKS_ROOT="${BOOKS_ROOT:-$REPO/ops/books/cef_live}"

if ! "$PY" "$CAL" --check "$TODAY" >> "$LOG" 2>&1; then
  stamp "not an NYSE trading day — skip"; exit 0
fi

# Same-day NAV (2026-09-08): sponsors publish after 17:15, so the session waits
# for today's NAV on every deployed name and then REQUIRES the pair complete.
# Standing down beats deciding on yesterday's discounts -- an MOC placed at
# 20:00 fills in the same auction as one placed at 17:15. Mirrors launch_job.py,
# which is what launchd actually runs; this script is for manual use.
stamp "waiting for today's NAV (deadline ${NAV_DEADLINE:-21:30})"
"$PY" "$REPO/scripts/cef/wait_for_nav.py" --asof "$TODAY" \
    --deadline "${NAV_DEADLINE:-21:30}" --interval "${NAV_POLL_SECONDS:-600}" \
    --book "$BOOK" >> "$LOG" 2>&1
wrc=$?
stamp "refreshing CEF price + NAV"
"$PY" "$REPO/scripts/cef/fetch_daily.py" --require-asof "$TODAY" \
    --nav-fallback cefconnect --book "$BOOK" >> "$LOG" 2>&1
rrc=$?
if [ $wrc -ne 0 ] && [ $wrc -ne 3 ]; then
  stamp "TODAY'S NAV NOT PUBLISHED by ${NAV_DEADLINE:-21:30} — standing down"; exit 1
fi
if [ $rrc -eq 4 ]; then
  stamp "TODAY'S PAIR INCOMPLETE — standing down, will not trade on a lagged pair"; exit 1
elif [ $rrc -ne 0 ]; then
  stamp "DATA REFRESH FAILED — aborting, will not trade on stale NAV"; exit 1
fi

ASOF="$TODAY"
ARGS=(--asof "$ASOF" --book "$BOOK" --source yfinance)

if [ "$DRY_RUN" = "1" ]; then
  SCRATCH="$(mktemp -d)"
  stamp "RUNG-0 dry run -> $SCRATCH (nothing transmitted)"
  EXECUTION=simulator "$PY" -m src.deploy.run_book "${ARGS[@]}" \
      --books-root "$SCRATCH" --dry-run >> "$LOG" 2>&1
  rc=$?
else
  stamp "EXECUTION=$EXECUTION books-root=$BOOKS_ROOT asof=$ASOF"
  EXECUTION="$EXECUTION" "$PY" -m src.deploy.run_book "${ARGS[@]}" \
      --books-root "$BOOKS_ROOT" >> "$LOG" 2>&1
  rc=$?
fi
[ $rc -ne 0 ] && stamp "FAILED rc=$rc" || stamp "ok"
exit $rc
