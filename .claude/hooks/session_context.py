#!/usr/bin/env python3
"""SessionStart hook: open every session knowing whether the book is trading.

Prints a short plain-text block, which Claude Code shows to Claude on
SessionStart. Deliberately under ~15 lines: this cost is paid on every single
session, so it carries only what changes and only what changes a decision.

The one line that justifies the whole file is `LAST BROKER-CONFIRMED FILL`.
Everything else in this repo -- heartbeats, logs, ledgers, reports -- can read
"ok" while the book has silently not traded for a month, and once did.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from book_state import collect
except Exception:
    sys.exit(0)


def main() -> int:
    try:
        s = collect()
    except Exception:
        return 0

    out = ["QUANTT live-book state (.claude/hooks/session_context.py):"]

    halt = s.get("halt") or {}
    if halt.get("active"):
        out.append(f"  HALT ACTIVE — ops/HALT.md: {halt.get('reason')}")
        out.append("  Preflight treats this as a hard gate. Nothing trades "
                   "until it is cleared deliberately.")

    f = s.get("fills") or {}
    gap, last = f.get("gap_sessions"), f.get("date")
    if last is None:
        out.append("  LAST BROKER-CONFIRMED FILL: none on record.")
    else:
        gap_txt = f"{gap} trading day(s) ago" if gap is not None else "unknown gap"
        flag = "  <-- STALE, the book may not be trading" if (gap or 0) >= 3 else ""
        out.append(f"  LAST BROKER-CONFIRMED FILL: {last} ({gap_txt}); "
                   f"{f.get('n_sessions', 0)} session(s) with real fills, "
                   f"{f.get('n_fills', 0)} executions total.{flag}")

    hb = s.get("heartbeat") or {}
    bad = [f"{k}:{v.get('status')}" for k, v in hb.items()
           if v.get("status") not in (None, "ok")]
    out.append("  Heartbeat: " + (", ".join(bad) if bad else "all jobs ok")
               + f" (cef last beat {hb.get('cef', {}).get('date')}).")

    t = s.get("today") or {}
    if t.get("blockers"):
        out.append(f"  Last CEF session {t.get('date')} blockers: "
                   + "; ".join(t["blockers"][:2]))

    led = s.get("ledger") or {}
    if led.get("nav"):
        out.append(f"  Shadow-ledger NAV ${led['nav']:,.0f} as of "
                   f"{led.get('date')} — NOTE the ledger disagrees with the "
                   "broker on all 17 positions; treat P&L as indicative only.")

    g = s.get("git") or {}
    out.append(f"  git {g.get('branch')}, {g.get('dirty')} file(s) uncommitted.")
    out.append("  Run /book-status for the full readout, /preflight to test "
               "the gate without trading.")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
