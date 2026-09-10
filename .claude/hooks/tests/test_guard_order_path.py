"""Tests for the order-path guard.

The guard is safety-critical: it is the only thing standing between an agent's
"just run it and see" reflex and an uncancellable MOC order. It is also the only
piece of this configuration whose failure is silent in the dangerous direction —
a guard that stops matching is a guard nobody notices is gone.

So it is tested three ways:

  BLOCKED   commands that must be denied
  PASSES    ordinary commands that must not be
  HEREDOC   a written heredoc body naming a forbidden path is documentation,
            not an invocation; an EXECUTED one is code and must be scanned

Run with the repo suite (`python3 -m pytest`) or standalone:

    python3 .claude/hooks/tests/test_guard_order_path.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "guard_order_path.py"


def decide(command: str) -> str | None:
    """Run the hook exactly as Claude Code does. Returns the deny reason, or None."""
    p = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, (
        f"the guard must always exit 0 — a crashing guard is reported as a hook "
        f"failure rather than a decision. Got {p.returncode}: {p.stderr[:400]}")
    if not p.stdout.strip():
        return None
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


BLOCKED = [
    # order path — anything that can transmit
    "python3 src/deploy/run_book.py --asof 2026-09-10 --book ops/books/cef_discount_book.json",
    "bash ops/schedule/run_cef.sh",
    "bash ops/schedule/run_after_close.sh",
    "python3 ~/Library/Application\\ Support/quantt/launch_job.py",
    "python3 scripts/audit/moc_routing_test.py",
    "bash ops/promote.sh",
    "python3 ops/cancel_open_orders.py --book ops/books/cef_discount_book.json",
    "python3 ops/switch_broker.py --to gateway",
    "python3 ops/reset_epoch.py",
    "python3 ops/rebuild_ledger.py",
    "launchctl unload ~/Library/LaunchAgents/com.quantt.cef.plist",
    "launchctl kickstart -k gui/501/com.quantt.cef",
    "python3 -m ops.halt --clear",
    "rm ops/HALT.md",
    # compound commands: a deny must match ANY subcommand
    "echo starting && python3 src/deploy/run_book.py --asof 2026-09-10",
    "cd /tmp; bash ops/schedule/run_cef.sh",
    # credentials
    "cat config/.env",
    "head -5 config/.env.pre_alerts",
    "python3 -c \"print(open('config/.env').read())\"",
    "cat ~/ibc/config.ini",
    "env | grep IBKR",
    "printenv | rg PASSWORD",
    # live state
    "rm -rf ops/books/cef_live/_ibkr_shadow",
    "git checkout -- ops/books/",
    "git clean -fd ops/books",
    "> ops/books/cef_live/_ibkr_shadow/cef_discount/nav.csv",
]

PASSES = [
    # research
    "python3 scripts/cef/band_frontier.py",
    "python3 scripts/cef/plan_diagnostics.py",
    "python3 scripts/cef/borrow_capacity.py",
    "python3 scripts/audit/live_pnl_attribution.py",
    # tests
    "python3 -m pytest",
    "python3 -m pytest -q src/deploy/tests -k band",
    # ops, read-only
    "python3 -m ops.doctor --quick",
    "python3 -m ops.preflight --book ops/books/cef_discount_book.json --no-live",
    "python3 ops/monitor.py",
    "python3 ops/reconcile_orders.py",
    "python3 ops/capture_fills.py --book ops/books/cef_discount_book.json "
    "--books-root ops/books/cef_live --slippage",
    # explicit read-only flags rescue an order-path match
    "python3 src/deploy/run_book.py --help",
    "python3 src/deploy/run_book.py --asof 2026-09-10 --book x.json --dry-run",
    # dashboard and inspection
    "python3 dashboard/server.py",
    "curl -s http://127.0.0.1:8787/api/factors | jq .",
    "python3 .claude/hooks/book_state.py -p",
    "rg 'shift\\(2\\)' scripts/ src/",
    "git status --short",
    "git add -A && git commit -m 'wip'",
    "head -50 docs/PLAN.md",
    "tail -30 ops/schedule/logs/cef_2026-09-09.log",
    "cat ops/specs/cef_discount.frozen.json | jq .frozen",
    # a presence check that never prints the value
    "python3 -c \"import os; print('IBKR_PORT' in os.environ)\"",
]

HEREDOC_WRITTEN = [
    "cat > CLAUDE.md <<'EOF'\nNever print config/.env values.\nEOF",
    "cat > docs/x.md <<'EOF'\nDo not run run_book.py yourself.\nEOF",
    "tee .claude/rules/x.md <<'EOF'\nconfig/.env holds credentials\nEOF",
]

HEREDOC_EXECUTED = [
    "python3 - <<'EOF'\nprint(open('config/.env').read())\nEOF",
    "bash <<'EOF'\ncat config/.env\nEOF",
    "python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['python3', 'src/deploy/run_book.py'])\nEOF",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocked(command):
    assert decide(command) is not None, f"guard let a dangerous command through: {command}"


@pytest.mark.parametrize("command", PASSES)
def test_passes(command):
    reason = decide(command)
    assert reason is None, (
        f"guard blocked ordinary work: {command}\n  -> {(reason or '').splitlines()[0]}")


@pytest.mark.parametrize("command", HEREDOC_WRITTEN)
def test_written_heredoc_body_is_documentation(command):
    assert decide(command) is None, (
        "a heredoc body being WRITTEN to disk is content, not an invocation — "
        f"documentation that names a forbidden path must not be blocked: {command}")


@pytest.mark.parametrize("command", HEREDOC_EXECUTED)
def test_executed_heredoc_body_is_scanned(command):
    assert decide(command) is not None, (
        f"a heredoc body piped to an interpreter IS executed and must be scanned: {command}")


def test_guard_survives_garbage_input():
    """A guard that crashes on malformed input would block all Bash use."""
    p = subprocess.run([sys.executable, str(HOOK)], input="not json at all",
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0
    assert p.stdout.strip() == ""


def test_empty_command_is_not_a_decision():
    assert decide("") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
