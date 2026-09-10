#!/bin/bash
# Promote a tagged commit into the PROD checkout, with a smoke test and rollback.
#
#   ~/prod/QUANTT/ops/promote.sh v2026.09.09            # normal
#   ~/prod/QUANTT/ops/promote.sh v2026.09.09 --force    # inside the session window (don't)
#
# Run it FROM PROD -- it promotes the tree it lives in. Dev never runs it.
#
# WHY THIS EXISTS (2026-09-08)
# ---------------------------
# Until today the scheduler ran the same working tree every edit and every
# research script ran in. On go-live day fetch_daily.py and launch_job.py were
# changed four hours before the 17:15 session. Tested, but nothing STOPPED an
# untested edit reaching the sleeve, and any script could write into the
# parquets the sleeve prices from. Now: code reaches prod only as a tag, only
# through this script, only outside the session window, and only if the tag
# passes the same steps the session will run.
#
# WHAT IT CHECKS, IN ORDER
#   1. Not 16:30-22:30 local on a trading day (cef waits for NAV until 21:30).
#   2. Prod's tree is clean. Ledgers, data, config and logs are untracked, so
#      "clean" means "no code edited in prod", which is the rule.
#   3. The tag exists on origin. Detached checkout of exactly that tag.
#   4. Smoke test against the LAST trading day, all read-only or idempotent:
#        - ops.doctor           the plumbing (plists, REPO path, gateway, IBC)
#        - wait_for_nav --once  the NAV sources answer for the last session
#        - fetch_daily --require-asof <last>   the panel is complete for it
#        - run_book --dry-run   the sleeve builds targets (scratch dir, no ledger)
#        - dashboard/server.py imports
#      Any failure -> checkout the previous tag again, exit non-zero, and say so.
#   5. Record the promotion (ops/schedule/logs/promotions.log + heartbeat
#      'promote') and restart the dashboard so it serves the new tag.
set -uo pipefail

PROD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-/opt/anaconda3/bin/python3}"
CAL="$PROD/ops/schedule/nyse_calendar.py"
TAG="${1:?usage: promote.sh <tag> [--force]}"
FORCE="${2:-}"
LOGDIR="$PROD/ops/schedule/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/promotions.log"
stamp(){ echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

TODAY="$(date +%Y-%m-%d)"
HHMM="$(date +%H%M)"

# 1. session window -------------------------------------------------------
if "$PY" "$CAL" --check "$TODAY" >/dev/null 2>&1; then
  if [ "$HHMM" -ge 1630 ] && [ "$HHMM" -le 2230 ] && [ "$FORCE" != "--force" ]; then
    stamp "REFUSED $TAG: $HHMM is inside the session window (16:30-22:30) on a trading day"
    exit 2
  fi
fi

# 2. clean prod -----------------------------------------------------------
if [ -n "$(git -C "$PROD" status --porcelain)" ]; then
  stamp "REFUSED $TAG: prod has uncommitted changes -- nobody edits prod:"
  git -C "$PROD" status --short | tee -a "$LOG"
  exit 2
fi
PREV="$(git -C "$PROD" describe --tags --always 2>/dev/null)"

# 3. fetch + checkout -----------------------------------------------------
git -C "$PROD" fetch --tags --quiet origin || { stamp "FAILED $TAG: git fetch"; exit 1; }
if ! git -C "$PROD" rev-parse -q --verify "refs/tags/$TAG^{commit}" >/dev/null; then
  stamp "REFUSED $TAG: no such tag on origin"; exit 2
fi
stamp "promoting $PREV -> $TAG"
git -C "$PROD" checkout --detach --quiet "$TAG" || { stamp "FAILED $TAG: checkout"; exit 1; }

rollback(){
  stamp "SMOKE FAILED at step '$1' -- rolling back to $PREV"
  git -C "$PROD" checkout --detach --quiet "$PREV"
  exit 1
}

# 4. smoke test against the last completed session ------------------------
LAST="$("$PY" "$CAL" --prev "$TODAY" 2>/dev/null | awk '{print $1}')"
[ -n "$LAST" ] || rollback "calendar"
BOOK="$PROD/ops/books/cef_discount_book.json"
SMOKE="$LOGDIR/promote_smoke_${TAG}.log"; : > "$SMOKE"
stamp "smoke test on $LAST -> $SMOKE"

( cd "$PROD" && "$PY" -m ops.doctor >> "$SMOKE" 2>&1 )                       || rollback "doctor"
"$PY" "$PROD/scripts/cef/wait_for_nav.py" --asof "$LAST" --once --book "$BOOK" \
      >> "$SMOKE" 2>&1                                                        || rollback "wait_for_nav"
"$PY" "$PROD/scripts/cef/fetch_daily.py" --require-asof "$LAST" \
      --nav-fallback cefconnect --book "$BOOK" >> "$SMOKE" 2>&1               || rollback "fetch_daily"
SCRATCH="$(mktemp -d)"
( cd "$PROD" && EXECUTION=simulator "$PY" -m src.deploy.run_book --asof "$LAST" \
      --book "$BOOK" --source yfinance --books-root "$SCRATCH" --dry-run \
      >> "$SMOKE" 2>&1 )                                                      || rollback "run_book dry-run"
rm -rf "$SCRATCH"
( cd "$PROD" && "$PY" -c "import dashboard.server" >> "$SMOKE" 2>&1 )         || rollback "dashboard import"

# 5. record + restart the dashboard ---------------------------------------
( cd "$PROD" && "$PY" - "$TAG" "$PREV" <<'EOF'
import sys
sys.path.insert(0, ".")
from ops import halt
halt.beat("promote", "ok", {"tag": sys.argv[1], "prev": sys.argv[2]})
EOF
) || stamp "warning: heartbeat 'promote' not written"
launchctl kickstart -k "gui/$(id -u)/com.quantt.dashboard" 2>/dev/null \
  && stamp "dashboard restarted on $TAG" \
  || stamp "warning: dashboard agent not restarted (is com.quantt.dashboard loaded?)"
stamp "PROMOTED $TAG (was $PREV)"
