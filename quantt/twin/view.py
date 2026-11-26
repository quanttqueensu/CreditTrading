"""The one public read of the twin's ledger, for the per-book switch (a later build on top of this one).

    from quantt.twin import ledger_view
    ledger_view(state_dir) -> {slug: {"shares": {symbol: int}, "cash": float}}

SLUGS, spelled exactly so (the switch build depends on them): "cef", "c4", "events/<sleeve-slug>"
for each events sleeve, and "legacy", the account's positions at the twin's epoch (seeded with
shares and no cost, flattened by the first session, so its cash is proceeds, never a P&L).

Cash starts at zero for every slug and moves by -(shares booked x price), so a slug's P&L at any
marks is cash + sum(shares x marks) (`quantt/sleeves/ledger.py`, whose format this reads). Raises,
naming what is missing, when the file is absent or not a version-1 ledger: a book switched to IBKR
must never size from an empty answer to an unreadable file.
"""
from __future__ import annotations

import json
from pathlib import Path


def ledger_view(state_dir) -> dict:
    from quantt.sleeves import ledger as led
    p = Path(state_dir) / "ledger.json"
    if not p.is_file():
        raise FileNotFoundError(f"{p} is missing: the twin has no ledger (record its epoch once: "
                                "`python3 -m quantt.twin epoch`)")
    d = json.loads(p.read_text())
    if not isinstance(d, dict) or d.get("version") != 1 or not isinstance(d.get("sleeves"), dict):
        raise led.LedgerError(f"{p} is not a version-1 ledger (no version 1 or no sleeves table)")
    out = {}
    for slug, r in sorted(d["sleeves"].items()):
        sh = r.get("shares") if isinstance(r, dict) else None
        if not isinstance(sh, dict):
            raise led.LedgerError(f"{p}: slug {slug!r} has no shares table")
        bad = sorted(s for s, q in sh.items() if type(q) is not int)
        if bad:
            raise led.LedgerError(f"{p}: slug {slug!r} holds non-whole shares in {bad}")
        cash = r.get("cash")
        if isinstance(cash, bool) or not isinstance(cash, (int, float)):
            raise led.LedgerError(f"{p}: slug {slug!r} has no cash figure")
        out[slug] = {"shares": {s: q for s, q in sorted(sh.items()) if q}, "cash": float(cash)}
    return out
