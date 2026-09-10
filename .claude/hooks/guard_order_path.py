#!/usr/bin/env python3
"""PreToolUse(Bash) guard: nothing reaches the broker, or a secret, by accident.

WHY THIS EXISTS
---------------
Three properties of this repo make an agent's ordinary "just run it and see"
reflex dangerous, and none of them are visible from a command string alone:

  1. THE TRADE PHASE IS NOT IDEMPOTENT. There is no dedupe at the broker. A
     second armed run stacks a second order set, and because arm() re-seeds
     from ib.positions() -- which do NOT include the still-unfilled MOC orders
     -- both sets fill in the same closing auction and the book DOUBLES.
     (docs/SYSTEM_AND_STRATEGY.md 3.2)

  2. MOC ORDERS CANNOT BE CANCELLED after 15:50 ET. NYSE Rule 7.35(a)(8): not
     even "to correct a legitimate error", absent a Trading Official. So the
     window in which a mistake is reversible is minutes wide, and it closes
     before anyone reads a log.

  3. EXECUTION MODE LIVES IN AN ENV FILE, NOT THE COMMAND. `run_book.py`
     with no flags is a live armed run if ops/schedule/cef.env says
     EXECUTION=ibkr DRY_RUN=0, which it currently does. The command text looks
     identical to a simulator run.

CLAUDE.md can ask for care. Only a hook can guarantee it. This is the
enforcement layer; the rules and skills are the guidance layer.

WHAT IT DOES
------------
Denies the tool call and hands the reason back to Claude, which then has to
put the decision to the human. It never silently rewrites a command. The
human can always run the same thing themselves by typing `! <command>` in the
Claude Code prompt, which is the documented escape hatch and leaves an
explicit human action in the transcript.

Deny is deliberately BROAD and matched against the whole command string,
including every subcommand of a compound command. A false positive costs one
sentence of explanation; a false negative costs a doubled book.

Exit 0 always. A guard that crashes must not also block ordinary work, and a
non-zero exit here would be reported as a hook failure rather than a decision.
"""
from __future__ import annotations

import json
import re
import sys

# --------------------------------------------------------------------------
# 1. Anything that can transmit an order, move live state, or restart the
#    scheduler. Matched case-insensitively anywhere in the command string.
# --------------------------------------------------------------------------
ORDER_PATH = [
    (r"run_book\.py",
     "run_book.py is the live session entry point. With ops/schedule/cef.env "
     "at RUNG-2 (DRY_RUN=0, EXECUTION=ibkr) it TRANSMITS MOC orders. The trade "
     "phase is not idempotent -- a second armed run today stacks a second "
     "order set that fills in the same auction."),
    (r"ops/schedule/run_(cef|phase0|after_close|weekly)\.sh",
     "ops/schedule/*.sh runs a full scheduled session, including the trade "
     "phase. These wrappers are for MANUAL use and they arm."),
    (r"launch_job\.py",
     "launch_job.py is the launchd entry point for the scheduled session. "
     "Running it by hand fires a real session out of schedule."),
    (r"moc_routing_test\.py",
     "scripts/audit/moc_routing_test.py TRANSMITS a live test order to the "
     "closing auction. It is a broker probe, not a unit test."),
    (r"ops/promote\.sh",
     "ops/promote.sh promotes a spec/book into the live path."),
    (r"switch_broker\.py",
     "ops/switch_broker.py rewrites config/.env broker routing. It is what "
     "moved the book between TWS 7497 and Gateway 4002; getting it wrong "
     "silently stops the book trading (that cost 21 sessions in Aug 2026)."),
    (r"reset_epoch\.py",
     "ops/reset_epoch.py rewrites the live ledger epoch. It destroys the "
     "continuity of the paper track record, which IS the deliverable."),
    (r"cancel_open_orders\.py",
     "ops/cancel_open_orders.py cancels working orders at the broker. It is "
     "usually the RIGHT call before a manual re-run -- but it is a live "
     "broker mutation and needs a human to say go."),
    (r"rebuild_ledger\.py",
     "ops/rebuild_ledger.py rewrites the shadow ledger from scratch."),
    (r"\bib(api)?\.(placeOrder|place_order)\b|place_targets\s*\(",
     "This calls the order-placement path directly."),
    (r"launchctl\s+(load|unload|bootstrap|bootout|kickstart)",
     "This starts or stops the launchd agents that drive the book. A stopped "
     "agent is a silently non-trading book; that failure mode has already "
     "cost this project a month."),
    (r"\bops/halt\.py\b|\bops\.halt\b",
     "ops/halt.py writes/clears the durable halt that preflight treats as a "
     "hard gate. Arming or clearing a halt is an operator decision."),
    (r"rm\b[^|;&]*\bHALT\.md",
     "Deleting ops/HALT.md clears the hard gate that stops the money. Halts "
     "are cleared deliberately, with a written record, never with rm."),
]

# --------------------------------------------------------------------------
# 2. Credentials. Read/Edit deny rules in settings.json already cover the file
#    tools and the Bash commands Claude Code recognises (cat/head/tail/sed).
#    These patterns catch the ways a script can read a file without naming it
#    to those checks.
# --------------------------------------------------------------------------
SECRETS = [
    (r"(config/\.env|deploy/ibgw/\.env|~/?\.?ibc/config\.ini|ibc/config\.ini)",
     "config/.env holds IBKR and R2 credentials; ~/ibc/config.ini holds "
     "IbLoginId/IbPassword. Never read, print, copy or transmit them. If you "
     "need to know whether a KEY is set, check `key in os.environ` and print "
     "only the boolean."),
    (r"\b(env|printenv|set)\b[^|;&]*\|[^|;&]*\b(grep|rg|awk|sed)\b[^|;&]*"
     r"(IBKR|IB_|PASSWORD|PASSWD|SECRET|TOKEN|R2_|AWS_|API_KEY)",
     "This dumps the environment and filters it for credentials."),
]

# --------------------------------------------------------------------------
# 3. Live state that is not reconstructable. The broker ledgers and the fill
#    record are the only evidence this project has; ib.fills() serves the
#    current TWS session only, so a lost fill is lost permanently.
# --------------------------------------------------------------------------
LIVE_STATE = [
    (r"rm\b[^|;&]*\bops/books\b|rm\b[^|;&]*_ibkr_shadow",
     "ops/books/**/_ibkr_shadow holds the ONLY record of real executions. "
     "TWS forgets fills at its daily restart and there is no historical "
     "execution endpoint, so a deleted broker_fills.csv row is gone forever."),
    (r"git\s+(checkout|restore|clean)\b[^|;&]*\bops/books\b",
     "This discards live ledger state that was written by real sessions."),
    (r">\s*ops/books/[^\s]*\.(csv|json)",
     "This truncates a live ledger file in place."),
]

ALL = ([(re.compile(p, re.I), why, "ORDER PATH") for p, why in ORDER_PATH]
       + [(re.compile(p, re.I), why, "CREDENTIALS") for p, why in SECRETS]
       + [(re.compile(p, re.I), why, "LIVE STATE") for p, why in LIVE_STATE])

# Read-only invocations that would otherwise trip a broad pattern above.
# Each is verified read-only: --no-live skips the broker probe, --dry-run
# transmits nothing, --help prints usage.
EXEMPT = re.compile(
    r"(--help|-h\b|--dry-run|--no-live|--quick|--collect-only)", re.I)


# Interpreters that EXECUTE a heredoc body. For those the body is code and is
# scanned. For everything else (`cat > file <<EOF`, `tee file <<EOF`, ...) the
# body is content being written to disk -- a document, a skill file, a test
# fixture -- and scanning it is a false positive: a CLAUDE.md that merely NAMES
# the credentials file is not a command that reads it. This distinction was
# added after the guard blocked the write of its own project documentation.
_INTERPRETER = re.compile(
    r"\b(ba|z|k|da)?sh\b|\bpython3?\b|\bperl\b|\bruby\b|\bnode\b|\beval\b")
_HEREDOC = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def strip_heredoc_bodies(command: str) -> str:
    """Drop heredoc bodies that are written to disk rather than executed.

    Conservative in the direction that matters: if the line introducing the
    heredoc names an interpreter, the body IS executed, so it is left in place
    and scanned normally.
    """
    lines = command.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = _HEREDOC.search(line)
        if m:
            executed = bool(_INTERPRETER.search(line.split("<<")[0]))
            terminator = m.group(1)
            j, body = i + 1, []
            while j < len(lines) and lines[j].strip() != terminator:
                body.append(lines[j])
                j += 1
            if executed:
                out.extend(body)
            if j < len(lines):
                out.append(lines[j])
            i = j + 1
            continue
        i += 1
    return "\n".join(out)


def decide(command: str):
    """Return (reason, category) if the command must be denied, else None."""
    if not command:
        return None
    command = strip_heredoc_bodies(command)
    for rx, why, category in ALL:
        if rx.search(command):
            # An explicit read-only flag rescues an order-path match only.
            # Nothing rescues a credential or live-state match.
            if category == "ORDER PATH" and EXEMPT.search(command):
                continue
            return why, category
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0                      # unparseable input is not a decision
    try:
        command = str(payload.get("tool_input", {}).get("command", ""))
        verdict = decide(command)
        if verdict is None:
            return 0
        why, category = verdict
        reason = (
            f"BLOCKED BY PROJECT GUARD [{category}] "
            f"(.claude/hooks/guard_order_path.py)\n\n{why}\n\n"
            "Do not work around this by rewriting the command. Tell the user "
            "what you want to run and why, and let them run it themselves by "
            "typing `! <command>` at the Claude Code prompt -- that keeps the "
            "decision, and the record of it, with the human."
        )
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}, sys.stdout)
    except Exception:
        return 0                      # never let the guard break the session
    return 0


if __name__ == "__main__":
    sys.exit(main())
