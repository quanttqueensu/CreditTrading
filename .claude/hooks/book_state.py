#!/usr/bin/env python3
"""The one reader of "is anything trading?" for the SessionStart banner and the
status line.

REWRITTEN 2026-09-28. Until then this read the IBKR prod tree: broker-confirmed
fills, halts, heartbeats, the shadow ledger. IBKR was retired that day
and the IBKR reader is at git tag `pre-clean-slate`
(`_archive/claude_layer/hooks/book_state_2026-09-28.py`).

WHAT IT PRESERVES. The old reader existed because a 21-session outage went
unnoticed while every surface read "ok". The property that matters is that
SILENCE NEVER READS AS SUCCESS. While no Alpaca book trades, the honest state
is "no live book", and this reports exactly that. It never says "ok" because
nothing complained.

WHAT IT READS. Only files: git, and the read-only Alpaca probe's snapshots in
`results/ops/alpaca_probe/`. No network, no keys. The SessionStart hook runs
this on every session, and a hook that reached a broker would be a broker
connection nobody asked for.

    python3 .claude/hooks/book_state.py -p     # the state as JSON
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROBE_DIR = REPO / "results" / "ops" / "alpaca_probe"
BOOKS = ("cef", "b6")          # quantt.broker.alpaca_probe.BOOK_SPECS; not imported,
                               # so this hook stays stdlib-only and fast.


def _git(*args) -> str:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                       text=True, timeout=5)
    return r.stdout.strip()


def probes() -> dict:
    """{book: latest snapshot file name, or None}."""
    out = {}
    for b in BOOKS:
        snaps = sorted(PROBE_DIR.glob(f"*_{b}.json"))
        out[b] = snaps[-1].name if snaps else None
    return out


def collect() -> dict:
    return {
        # No Alpaca book trades yet. When the adapter lands, this becomes a
        # measurement of broker-confirmed Alpaca fills -- never a constant True.
        "live_book": None,
        "probes": probes(),
        "git": {"branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                "dirty": len([l for l in _git("status", "--porcelain").splitlines()
                              if l.strip()])},
    }


if __name__ == "__main__":
    json.dump(collect(), sys.stdout, indent=2 if "-p" in sys.argv else None)
    print()
