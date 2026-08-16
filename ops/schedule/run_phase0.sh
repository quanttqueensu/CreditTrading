#!/bin/bash
# Phase 0 null-trader daily unit — fired after the US close on trading days.
#
# This deliberately does NOT reuse run_after_close.sh: that wrapper targets
# src.deploy.v2.run_book_v2 and ops/books/v2/book_v2_ff.json, neither of which
# survived the project wipe. Pointing a live scheduler at a dead module would
# fail silently every day.
#
# Rung ladder, same discipline as the old wrapper — a HUMAN raises it, never the
# script:
#   RUNG-0  DRY_RUN=1  EXECUTION=simulator   compute + log targets, throwaway root
#   RUNG-1  DRY_RUN=0  EXECUTION=simulator   live shadow ledger, no orders sent
#   RUNG-2  DRY_RUN=0  EXECUTION=ibkr        real orders to the IBKR PAPER account
#
# CURRENT RUNG is whatever phase0.env says. Nothing here decides to trade.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"
CAL="$REPO/ops/schedule/nyse_calendar.py"
LOG_DIR="$REPO/ops/schedule/logs"
mkdir -p "$LOG_DIR"

ENV_FILE="${SCHEDULE_ENV:-$REPO/ops/schedule/phase0.env}"
# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
PY="${PYTHON:-$PY}"
DRY_RUN="${DRY_RUN:-1}"
EXECUTION="${EXECUTION:-simulator}"
BOOK="${BOOK:-$REPO/ops/books/phase0_book.json}"
BOOKS_ROOT="${BOOKS_ROOT:-$REPO/ops/books/phase0_live}"

TODAY="$(date +%F)"
LOG="$LOG_DIR/phase0_${TODAY}.log"
stamp() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# --- trading-day gate -------------------------------------------------------
if ! "$PY" "$CAL" --check "$TODAY" >> "$LOG" 2>&1; then
    stamp "market closed on $TODAY — no-op"
    exit 0
fi

# --- asof = PRIOR trading day ----------------------------------------------
# This unit fires in the morning execution window (workflow §8: 09:35 snapshot,
# 09:40-10:15 execute). Today's session high/low do not exist yet, so the book
# must be computed from the last COMPLETE bar. Using today's date here would
# hand the sleeve a partial bar and silently change what it trades.
ASOF="$("$PY" "$CAL" --prev "$TODAY" 2>>"$LOG")"
if [ -z "$ASOF" ]; then
    stamp "could not resolve prior trading day for $TODAY — aborting"
    exit 1
fi
stamp "asof=$ASOF (prior trading day; today=$TODAY is the execution session)"

ARGS=(--asof "$ASOF" --book "$BOOK" --source yfinance)

if [ "$DRY_RUN" = "1" ]; then
    SCRATCH="$(mktemp -d)"
    stamp "RUNG-0 dry run -> $SCRATCH (nothing transmitted, live state untouched)"
    EXECUTION=simulator "$PY" "$REPO/src/deploy/run_book.py" \
        "${ARGS[@]}" --books-root "$SCRATCH" --dry-run >> "$LOG" 2>&1
    rc=$?
    rm -rf "$SCRATCH"
else
    stamp "EXECUTION=$EXECUTION books-root=$BOOKS_ROOT"
    EXECUTION="$EXECUTION" "$PY" "$REPO/src/deploy/run_book.py" \
        "${ARGS[@]}" --books-root "$BOOKS_ROOT" >> "$LOG" 2>&1
    rc=$?
fi

if [ $rc -ne 0 ]; then
    stamp "FAILED rc=$rc — see $LOG"
else
    stamp "ok"
fi
exit $rc
