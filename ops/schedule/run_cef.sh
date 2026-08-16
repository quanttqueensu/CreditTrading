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

stamp "refreshing CEF price + NAV"
if ! "$PY" "$REPO/scripts/cef/fetch_daily.py" >> "$LOG" 2>&1; then
  stamp "DATA REFRESH FAILED — aborting, will not trade on stale NAV"; exit 1
fi

# Fires after the US close, so TODAY is the right as-of: today's close and NAV
# are both published by 17:15 ET. If the NAV has not landed yet the panel simply
# has no row for today (price and NAV are inner-joined on date) and the sleeve
# falls back to the last complete pair on its own. Do NOT substitute a flag the
# calendar does not implement -- an unrecognised flag exits non-zero and the
# fallback would silently pick a date nobody chose.
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
