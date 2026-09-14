"""One-off, idempotent: book bench_b6_ew_credit's ANGL fill into its ledger.

    python3 ops/fix_bench_b6_angl_20260909.py          # dry run, prints the change
    python3 ops/fix_bench_b6_angl_20260909.py --commit

WHY
---
bench_b6 placed BUY 87 ANGL MOC on 2026-09-04 (its 60/40-style rebalance). The
benchmark ledgers were re-seeded on 2026-09-07 from a broker snapshot that held
no ANGL yet, so the epoch positions have no ANGL row. The order then filled at
the 2026-09-08 close (broker_fills.csv, execId ...6b43414c, 87 @ 28.80). On
2026-09-09 17:25 `arm()` found the account holding +87 ANGL, bench_b6 the only
owner in its process, ANGL also in another book's universe, and bench_b6's tag
book silent -- so it refused, wrote ops/HALT.md, and that global halt would
have blocked the CEF session too.

A ledger cannot be told about a fill it did not simulate, and reset_epoch's
broker mode would mis-assign the shared ETFs, so the row is added here exactly
as the ledger would have written it: 87 shares at the fill price, cash reduced
by the same amount, NAV unchanged, manifest rewritten from the files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "ops/books/benchmarks_live/_ibkr_shadow/bench_b6_ew_credit"
QTY, PX, DATE = 87.0, 28.80, "2026-09-08"


def main(argv=None) -> int:
    commit = "--commit" in (argv or sys.argv[1:])
    pos = pd.read_csv(ROOT / "positions.csv")
    nav = pd.read_csv(ROOT / "nav.csv")
    if "ANGL" in set(pos["ticker"]):
        print("ANGL already in bench_b6 positions.csv; nothing to do")
        return 0
    mv = QTY * PX
    row = {"date": DATE, "ticker": "ANGL", "shares": QTY, "close": PX,
           "market_value": mv, "weight": mv / float(nav["nav"].iloc[-1])}
    pos2 = (pd.concat([pos, pd.DataFrame([row])], ignore_index=True)
              .sort_values(["date", "ticker"]).reset_index(drop=True))
    nav2 = nav.copy()
    nav2.loc[nav2.index[-1], "cash"] = float(nav["cash"].iloc[-1]) - mv
    nav2.loc[nav2.index[-1], "invested"] = float(nav["invested"].iloc[-1]) + mv
    print(f"bench_b6: + ANGL {QTY:.0f} @ {PX:.2f} = ${mv:,.2f}; cash "
          f"{float(nav['cash'].iloc[-1]):,.2f} -> {float(nav2['cash'].iloc[-1]):,.2f}; "
          f"NAV {float(nav2['nav'].iloc[-1]):,.2f} (unchanged)")
    if not commit:
        print("dry run; add --commit to write")
        return 0
    pos2.to_csv(ROOT / "positions.csv", index=False)
    nav2.to_csv(ROOT / "nav.csv", index=False)
    m = json.loads((ROOT / "manifest.json").read_text())
    for f in ("orders.csv", "trades.csv", "positions.csv", "nav.csv"):
        df = pd.read_csv(ROOT / f)
        m["files"][f] = {"rows": int(len(df)),
                         "last_date": (str(df["date"].max())[:10]
                                       if len(df) and "date" in df else None)}
    m["written_utc"] = pd.Timestamp.utcnow().isoformat()
    m["note_2026-09-09"] = ("ANGL 87 @ 28.80 booked by ops/fix_bench_b6_angl_20260909.py "
                            "(bench_b6's own 09-08 MOC fill, placed pre-epoch)")
    (ROOT / "manifest.json").write_text(json.dumps(m, indent=2))
    sys.path.insert(0, str(REPO))
    from src.deploy.exec_ledger import LongOnlySleeveLedger
    lg = LongOnlySleeveLedger(ROOT)
    held = lg.held_shares() if hasattr(lg, "held_shares") else lg.held()
    print("written; ledger opens; held:", {k: v for k, v in held.items() if k != "CASH"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
