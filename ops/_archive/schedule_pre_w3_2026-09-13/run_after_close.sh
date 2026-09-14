#!/bin/bash
# Daily book unit (v2), fired by launchd/cron every weekday after the US close.
# 1. No-ops (exit 0) unless today is an NYSE trading day (ops/schedule/nyse_calendar.py)
#    so the calendar-timed sleeves (EOM j-countdown, FOMC day-0) never see a holiday.
# 2. Runs the V2 runner (src.deploy.v2.run_book_v2) --asof <today> against $BOOK,
#    marking to yfinance EOD (--source yfinance). Missed days (machine off/asleep)
#    are caught up with --replay-start computed from book_status_v2.json's asof via
#    the NYSE calendar, so each calendar-timed sleeve sees the right day.
# 3. DRY_RUN=1 -> run into a THROWAWAY --books-root (scratch tmp), EXECUTION forced
#    to simulator, NOTHING transmitted, the target book logged; the live
#    book_status_v2.json / ledgers are untouched. DRY_RUN=0 -> the live $BOOKS_ROOT.
#    The HUMAN flips DRY_RUN (and, only much later, EXECUTION) in schedule.env; this
#    script never decides to trade on its own. Everything is SIMULATOR (no real orders).
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"
CAL="$REPO/ops/schedule/nyse_calendar.py"
LOG_DIR="$REPO/ops/schedule/logs"
mkdir -p "$LOG_DIR"

# Human-owned knobs (DRY_RUN, EXECUTION, PYTHON, BOOK, BOOKS_ROOT) live in schedule.env.
# SCHEDULE_ENV lets a test point at a different env file (e.g. /dev/null to force a
# dry run off the caller's env); launchd never sets it, so production uses schedule.env.
ENV_FILE="${SCHEDULE_ENV:-$REPO/ops/schedule/schedule.env}"
# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
PY="${PYTHON:-$PY}"
DRY_RUN="${DRY_RUN:-1}"
EXECUTION="${EXECUTION:-simulator}"
BOOK="${BOOK:-$REPO/ops/books/v2/book_v2_paper.json}"
BOOKS_ROOT="${BOOKS_ROOT:-$REPO/ops/books/v2_live}"

TODAY="$(date +%F)"
LOG="$LOG_DIR/daily_${TODAY}.log"
stamp() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# --- 1. trading-day gate (holidays + weekends + special closures) -----------
if ! "$PY" "$CAL" --check "$TODAY" >> "$LOG" 2>&1; then
    stamp "market closed on $TODAY — no-op (calendar gate; EOM/FOMC phase preserved)"
    exit 0
fi

# --- 2. choose the books-root: live vs throwaway (dry) ----------------------
CLEANUP_ROOT=""
if [ "$DRY_RUN" = "1" ]; then
    RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/quantt_v2_dryrun.XXXXXX")"
    CLEANUP_ROOT="$RUN_ROOT"
    RUN_EXEC="simulator"          # a dry run never attaches a live broker
    stamp "DRY_RUN=1 — throwaway books-root $RUN_ROOT, EXECUTION=simulator; target book logged, NO orders transmitted, live book_status_v2.json untouched"
else
    RUN_ROOT="$BOOKS_ROOT"
    RUN_EXEC="$EXECUTION"
    stamp "DRY_RUN=0 EXECUTION=$RUN_EXEC — advancing the live v2 book at $RUN_ROOT"
fi

# --- 3. catch-up detection: replay any gap since the last real advance ------
# Reads the LIVE status (never the throwaway); a dry run always single-steps today.
REPLAY_ARGS=()
STATUS="$BOOKS_ROOT/book_status_v2.json"
if [ "$DRY_RUN" != "1" ] && [ -f "$STATUS" ]; then
    LAST_ASOF="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("asof",""))' "$STATUS" 2>/dev/null || true)"
    PREV_TD="$("$PY" "$CAL" --prev "$TODAY")"
    if [ -n "$LAST_ASOF" ] && [[ "$LAST_ASOF" < "$PREV_TD" ]]; then
        RESUME="$("$PY" "$CAL" --next "$LAST_ASOF")"
        stamp "gap detected: last book asof=$LAST_ASOF < previous trading day=$PREV_TD — replaying from $RESUME"
        REPLAY_ARGS=(--replay-start "$RESUME")
    fi
fi

# --- 4. run the v2 daily unit ------------------------------------------------
ARGS=(--asof "$TODAY" --book "$BOOK" --books-root "$RUN_ROOT" --source yfinance)

cd "$REPO"
# ${arr[@]+...} form: macOS ships bash 3.2, where "${arr[@]}" on an empty
# array trips `set -u`.
EXECUTION="$RUN_EXEC" "$PY" -m src.deploy.v2.run_book_v2 "${ARGS[@]}" \
    ${REPLAY_ARGS[@]+"${REPLAY_ARGS[@]}"} >> "$LOG" 2>&1
RC=$?
stamp "run_book_v2 exit=$RC (asof=$TODAY dry_run=$DRY_RUN execution=$RUN_EXEC books_root=$RUN_ROOT)"

# --- 5. drop the throwaway dry-run books-root --------------------------------
if [ -n "$CLEANUP_ROOT" ]; then
    rm -rf "$CLEANUP_ROOT"
    stamp "removed throwaway dry-run books-root $CLEANUP_ROOT"
fi
exit "$RC"
