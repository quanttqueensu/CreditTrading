"""`<state>/status.json`: the twin's one-file summary for orient and the daily page. Aggregates only.

WHY A FILE ("No phone", team lead 2026-11-25). Nothing on the VM sends an alert. Whether the
Gateway is logged in, how the last send and verify ended, and the side-by-side tally are written
here by every phase, and the read-only readers (`ops/prod_state.py` TWIN, `ops/daily_page.py`)
carry this one file off the VM over their existing ssh call. It holds counts, verdicts and bp
figures only: no symbol, quantity, price, account id or order id, so it may cross the wire and be
pasted into a tracked note (the repository keeps aggregates only, team lead 2026-11-03).
"""
from __future__ import annotations

import json
from pathlib import Path

from quantt.session import records as rec

FILE = "status.json"


def read(state: Path) -> dict:
    p = Path(state) / FILE
    return json.loads(p.read_text()) if p.exists() else {"version": 1}


def update(state: Path, section: str, value: dict, at: str) -> None:
    """Replace one section, stamped. Never raises into the caller's verdict: a status that
    cannot be written is printed by the caller's guard as a FAIL of that write, not swallowed."""
    d = read(state)
    d["version"] = 1
    d[section] = {**value, "at": at}
    d["updated_utc"] = at
    rec.write_json_atomic(Path(state) / FILE, d)
