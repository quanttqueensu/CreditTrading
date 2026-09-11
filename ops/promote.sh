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
# THE END OF THE WINDOW IS DERIVED FROM THE SESSION'S OWN DEADLINE, NOT WRITTEN
# HERE. It was the literal 2230 until 2026-09-10, and `ops/schedule/cef.env`
# has carried `NAV_DEADLINE=23:30` since 09-08 -- so there was a full hour,
# 22:30 to 23:30, in which this gate said "not in the session window" while the
# cef session was still polling for NAV and had not yet placed its orders.
# Promoting there is exactly what the window exists to prevent: `git checkout`
# swapping the tree under a running session. Measured 2026-09-10: the 17:15 run
# logged `deadline 23:30, poll every 900s`, and cef.env's own comment records
# that yfinance publishes the day's NAVs at ~22:45 ET.
#
# Deriving it means the two can never drift apart again. A missing or
# unparseable NAV_DEADLINE REFUSES rather than falling back to a literal: the
# whole defect was a literal that stopped matching reality, and a default here
# would rebuild it.
CEF_ENV="$PROD/ops/schedule/cef.env"
if [ ! -f "$CEF_ENV" ]; then
  stamp "REFUSED $TAG: $CEF_ENV is missing, so the session window cannot be derived"
  exit 2
fi
NAV_DEADLINE="$(sed -n 's/^NAV_DEADLINE=//p' "$CEF_ENV" | tr -d ' \r' | tail -1)"
case "$NAV_DEADLINE" in
  [0-2][0-9]:[0-5][0-9]) : ;;
  *) stamp "REFUSED $TAG: NAV_DEADLINE=${NAV_DEADLINE:-<unset>} in $CEF_ENV is not HH:MM;"
     stamp "  refusing rather than guessing a window end."
     exit 2 ;;
esac
WINDOW_END="${NAV_DEADLINE%%:*}${NAV_DEADLINE##*:}"

if "$PY" "$CAL" --check "$TODAY" >/dev/null 2>&1; then
  if [ "$HHMM" -ge 1630 ] && [ "$HHMM" -le "$WINDOW_END" ] && [ "$FORCE" != "--force" ]; then
    stamp "REFUSED $TAG: $HHMM is inside the session window (16:30-$NAV_DEADLINE) on a trading day"
    exit 2
  fi
fi

# 1b. A LIVE SESSION PROCESS REFUSES, CLOCK OR NO CLOCK -- and `--force` does
# NOT bypass this one. The window above is a proxy for "is a session running";
# this is the question itself, and it is the honest guard. A session that
# overran its deadline, was kicked by hand, or is still writing its ledger and
# capturing fills is just as unsafe to check out from under, and no hour of the
# day proves it is not. `--force` exists for the clock, never for this.
for job in cef benchmarks phase0; do
  pid="$(launchctl list 2>/dev/null | awk -v L="com.quantt.$job.daily" '$3==L{print $1}')"
  if [ -n "$pid" ] && [ "$pid" != "-" ]; then
    stamp "REFUSED $TAG: com.quantt.$job.daily is RUNNING (pid $pid) -- a checkout"
    stamp "  would swap the tree under a live session. Wait for it to exit."
    exit 2
  fi
done

# 2. clean prod -----------------------------------------------------------
# The question is "did anyone edit prod CODE", not "did the book trade". The
# live ledgers, the heartbeat and the halt files are still tracked, and they
# change on every session -- so a bare `status --porcelain` would refuse every
# promotion after the first evening. Excluded by pathspec rather than by
# untracking, because git history is currently their only off-machine backup
# (ops/backup_state.sh is the replacement; untrack them once it runs nightly).
# Anything else dirty in prod is a human editing production, and still refuses.
#
# THE `/**` IS LOAD-BEARING, MEASURED 2026-09-10. These were written as
# ':!ops/books/*_live' and ':!ops/halts', and those two exclusions matched
# NOTHING: a git pathspec `*` does not cross `/`, and no TRACKED path is
# literally named `…_live` -- the tracked paths are `ops/books/cef_live/…`.
# So the live ledgers were never excluded, and this gate REFUSED every
# promotion the moment a session wrote one. Measured that morning: prod was
# dirty with two phase0 ledger files, `status --porcelain -- . <excludes>`
# returned 3 lines, and the same call with `/**` returned 1 (the untracked
# halt file, which ':!ops/HALT_*.md' then excludes). That one is the reason
# this was hard to see: four of the six exclusions DO work, because they name
# a real single-segment path. Only the two directory patterns were inert.
#
# An exclusion that matches nothing is indistinguishable from one that matched
# and found nothing clean, which is why ops/tests/test_promote_gate.py now
# pins the pathspecs against a fixture repo rather than trusting this comment.
#
# `_dryruns` IS STATE TOO, AND LEAVING IT OUT STILL REFUSED EVERY PROMOTION.
# Measured 2026-09-11 against prod: with the corrected pathspecs above the gate
# still saw two dirty lines, both `ops/books/_dryruns/phase0/`. Eighteen files
# under that directory are TRACKED, and a session that does not arm rewrites
# them -- which is most sessions, the book having armed on 5 of 29. So the
# `/**` fix alone bought nothing in practice: it moved the refusal from the live
# ledgers to the dry-run artefacts. They are output, not code, and a human has
# not edited production by producing one.
STATE_EXCLUDES=(':!ops/books/*_live/**' ':!ops/books/_dryruns/**'
                ':!ops/heartbeat.json' ':!ops/HALT.md'
                ':!ops/HALT_*.md' ':!ops/halts/**' ':!ops/schedule/logs/**')
DIRTY="$(git -C "$PROD" status --porcelain -- . "${STATE_EXCLUDES[@]}")"
if [ -n "$DIRTY" ]; then
  stamp "REFUSED $TAG: prod has uncommitted CODE changes -- nobody edits prod:"
  echo "$DIRTY" | tee -a "$LOG"
  exit 2
fi
# Live state that moved since the last promotion is expected; record it so the
# promotion log says what the book had done, and so `checkout` below is never
# a surprise.
# Same `/**` trap as STATE_EXCLUDES above, in the INCLUSIVE direction, so it
# failed the other way round: measured 2026-09-10, this returned 0 where the
# corrected pathspec returns 2, so the note below had never once fired and the
# promotion log silently claimed no live state had moved on every promotion.
STATE_MOVED="$(git -C "$PROD" status --porcelain -- 'ops/books/*_live/**' \
              'ops/heartbeat.json' | wc -l | tr -d ' ')"
[ "$STATE_MOVED" != "0" ] && stamp "note: $STATE_MOVED live-state file(s) have advanced since the last promotion (expected)"
PREV="$(git -C "$PROD" describe --tags --always 2>/dev/null)"

# 3. fetch + checkout -----------------------------------------------------
git -C "$PROD" fetch --tags --quiet origin || { stamp "FAILED $TAG: git fetch"; exit 1; }
if ! git -C "$PROD" rev-parse -q --verify "refs/tags/$TAG^{commit}" >/dev/null; then
  stamp "REFUSED $TAG: no such tag on origin"; exit 2
fi

# ALWAYS archive live state before touching the tree. While the ledgers are
# still TRACKED, `git checkout` between two tags whose committed ledger
# contents differ would overwrite the running book's record with a snapshot
# from whenever dev last committed -- and that record is the only evidence the
# paper track record rests on. The archive costs ~160KB and a second.
#
# EXIT 2 IS NOT A FAILURE HERE. ops/backup_state.sh exits 2 for "archive
# written, but a file it wanted was unreadable" -- in practice the borrow panel,
# on the far side of the TCC boundary when `data/` is a symlink into ~/Desktop.
# Treating that as a refusal would block every promotion over a file that has
# nothing to do with what the checkout below can destroy: the LEDGERS are in the
# archive either way, and they are the irreplaceable part. So warn loudly and
# continue. Only a missing-or-empty archive (exit 1) refuses.
if [ -x "$PROD/ops/backup_state.sh" ]; then
  "$PROD/ops/backup_state.sh" >> "$LOG" 2>&1; brc=$?
  if [ "$brc" = "2" ]; then
    stamp "WARNING $TAG: state archived but INCOMPLETE (backup_state.sh rc=2) --"
    stamp "  the ledgers are in it; something under data/ was unreadable. See above."
  elif [ "$brc" != "0" ]; then
    stamp "REFUSED $TAG: could not archive live state before checkout (rc=$brc)"
    exit 1
  fi
else
  stamp "REFUSED $TAG: ops/backup_state.sh missing -- refusing to checkout over live state"
  exit 1
fi

stamp "promoting $PREV -> $TAG"
# `--merge` carries local modifications to files that are identical across the
# two commits (the normal case for live state) instead of refusing, and stops
# loudly on a genuine conflict rather than clobbering. Once the ledgers are
# untracked this is a plain checkout and the flag is inert.
#
# ONE-TIME HAZARD, WHEN THE UNTRACKING TAG IS EVENTUALLY PROMOTED. Promoting the
# tag that performs `git rm --cached` on the ledgers, onto a prod tree that still
# TRACKS them, DELETES them: git removes files the target commit does not
# contain, and on a clean tree there is no local modification for `--merge` to
# protect. Measured 2026-09-10 in a scratch worktree -- checkout returned rc=0,
# said nothing, and left ops/books/*_live empty. The smoke test does not catch it
# either: a missing ops/heartbeat.json is only a WARN, so doctor still exits 0
# and the promotion reports success. Restore from the archive taken immediately
# above, BEFORE the next session:
#   tar -xzf <archive> -C $PROD ops/books/cef_live ops/books/benchmarks_live \
#                               ops/books/phase0_live ops/heartbeat.json
# Restore ONLY those paths -- `tar -xzf <archive> -C $PROD ops/books` also
# rewinds the book JSONs and puts retired books back on disk, and
# `_foreign_book_claims` globs that directory from DISK, so it would silently
# undo the retirement the promotion was carrying. (That is not hypothetical:
# retiring credit_rv_book.json is what stops a dead book claiming ANGL.)
# Every promotion after that one transition is unaffected.
# As of 2026-09-10 the ledgers are STILL TRACKED -- `git ls-files
# ops/books/cef_live` returns 30 -- so this hazard is documented, not yet live.
if ! git -C "$PROD" checkout --detach --merge --quiet "$TAG"; then
  stamp "FAILED $TAG: checkout conflicted with live state. The archive above has "
  stamp "  it; untrack the ledgers (git rm -r --cached ops/books/*_live ops/heartbeat.json)"
  stamp "  so state and code stop sharing a version-control system, then retry."
  exit 1
fi

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
