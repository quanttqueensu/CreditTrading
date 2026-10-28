#!/bin/zsh
# research-loop: one daily research cycle (team lead, 2026-10-27: this laptop, one
# idea per day after the close; docs/SYSTEM.md §5).
#
# INSTALLED BY THE TEAM LEAD, NEVER BY AN AGENT. It starts a headless Claude Code
# session, and the permission flags below decide what that session may run.
# Read them before loading the plist (com.quantt.research-loop.plist.tmpl).
#
# WHAT IT REFUSES, WHATEVER THE MODEL DECIDES (--disallowedTools):
#   python3 -m quantt.session   the order runner, for any book. The loop never sends
#                               an order; lab trading is the runner's own scheduled job.
#   git push, gh pr merge       the loop commits on its own branch, and a human
#                               moves anything to main.
#   ssh                         the VM is prod and is reached only by the team lead.
# The Alpaca MCP order tools are already denied in ~/.claude/settings.json.
#
# WHY AUTO MODE AND NOT bypassPermissions: the classifier still screens every
# command the deny list does not name (it blocked an unloaded prod install on
# 2026-10-19).
#
# THE TRIAL SERIES MUST BE IN THE LOOP WORKTREE. They are gitignored
# (results/research/trials/series/, the repository is public), so a fresh
# worktree has the ledger's lines but none of the files, and no deflated-Sharpe
# bar can be computed after a trial is spent. Once, at install, copy that
# directory from the checkout that recorded them (on 2026-10-28 the backfill
# worktree, .claude/worktrees/research-backfill). The check below refuses a
# cycle until every ledger line loads with a matching sha256.
set -euo pipefail
WT="${QUANTT_LOOP_WORKTREE:?set QUANTT_LOOP_WORKTREE to the loop worktree (branch research-loop)}"
LOGS="${QUANTT_LOOP_LOGS:-$HOME/quantt_state/research-loop}"
mkdir -p "$LOGS"
cd "$WT"
D=$(TZ=America/New_York date +%F)
if ! python3 -c "import sys, datetime as dt; sys.path.insert(0, '.'); from ops.schedule.nyse_calendar import is_trading_day; sys.exit(0 if is_trading_day(dt.date.fromisoformat('$D')) else 3)"; then
  echo "$D not an NYSE session; no cycle" >> "$LOGS/loop.log"; exit 0
fi
# The loop runs under main's rules: bring them in, and stop on any conflict
# rather than resolve it unattended.
git fetch -q origin
if ! git merge -q --no-edit origin/main; then
  git merge --abort || true
  echo "$D merge of origin/main conflicted; no cycle" >> "$LOGS/loop.log"; exit 4
fi
if ! python3 -m scripts.research.registry verify > "$LOGS/$D.series.json"; then
  echo "$D trial series missing or altered in $WT (see $D.series.json); no cycle" >> "$LOGS/loop.log"; exit 5
fi
claude -p "Run the research-loop workflow with args {\"date\": \"$D\"}. When it returns, print its outcome and the report commit." \
  --permission-mode auto \
  --disallowedTools "Bash(python3 -m quantt.session:*)" "Bash(git push:*)" "Bash(gh pr merge:*)" "Bash(ssh:*)" \
  --output-format json > "$LOGS/$D.json" 2>> "$LOGS/loop.log"
echo "$D cycle finished (exit $?)" >> "$LOGS/loop.log"
