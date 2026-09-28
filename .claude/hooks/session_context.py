#!/usr/bin/env python3
"""SessionStart hook: open every session knowing whether anything is trading.

Prints a short plain-text block, which Claude Code shows to Claude on
SessionStart. Deliberately a few lines: this cost is paid on every session.

REWRITTEN 2026-09-28 for the Alpaca migration. The IBKR-era banner (last
broker-confirmed fill, halts, heartbeats) is at
at git tag `pre-clean-slate`. Its one principle
stands: say plainly when nothing is trading, rather than printing nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from book_state import collect
except Exception:
    sys.exit(0)


POINTER = ("  Numbers: python3 -m ops.orient · what the system is and has decided: "
           "docs/SYSTEM.md · the plan to prod: docs/ROADMAP.md · anything older is "
           "git tag pre-clean-slate (docs/HISTORY.md), never current state.")


def main() -> int:
    try:
        s = collect()
    except Exception:
        s = {}

    out = ["QUANTT state (.claude/hooks/session_context.py):"]
    if not s.get("live_book"):
        out.append("  NO LIVE BOOK. IBKR retired 2026-09-28; the Alpaca system "
                   "(quantt/) is being built. Nothing trades.")
    probes = s.get("probes") or {}
    if probes:
        out.append("  Alpaca probe snapshots: " + ", ".join(
            f"{b} {p or 'NONE'}" for b, p in probes.items()))
    g = s.get("git") or {}
    if g:
        out.append(f"  git {g.get('branch')}, {g.get('dirty')} file(s) uncommitted.")
    # The one pointer every session needs before it reads anything. Six
    # documents once each claimed to be where to start; the answer now has two
    # owners and a folder that is explicitly not one (docs/INDEX.md).
    out.append(POINTER)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
