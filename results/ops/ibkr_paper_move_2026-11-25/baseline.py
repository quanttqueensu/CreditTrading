"""The Alpaca baseline the IBKR twins must match or beat (team lead, 2026-11-25: "it needs to be
able to trade all our books equaly as good if not better").

WHY A SCRIPT. The figures in results/ops/IBKR_PAPER_MOVE_2026-11-25.md come from the books' own
verify records on the VM, which are not in this repository: scores.csv (one row per session,
written by quantt/session/verify.py) and tca.csv (fills against the primary exchange's official
close, condition M, notional-weighted). This reads LOCAL COPIES of those two files and prints
aggregates only (.claude/rules/report.md): counts, dollar totals and bp summaries, no names.

Usage: python3 baseline.py ROOT   where ROOT/<book>/scores.csv and ROOT/<book>/tca.csv exist for
book in cef, c4. Writes baseline.csv next to this script. Sign: + bp is worse for us.
"""
from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path


def _rows(p: Path) -> list[dict]:
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def _num(x: str) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def book_baseline(root: Path, book: str) -> dict:
    sc = _rows(root / book / "scores.csv")
    tca = _rows(root / book / "tca.csv")
    if not sc or not tca:
        raise SystemExit(f"{book}: scores.csv or tca.csv is empty under {root}")
    traded = [r for r in sc if r["traded"] == "True"]
    bp = [v for v in (_num(r["fill_vs_auction_bp"]) for r in traded) if v is not None]
    return {
        "book": book,
        "scores_first": sc[0]["date"], "scores_last": sc[-1]["date"],
        "sessions_scored": len(sc), "sessions_traded": len(traded),
        "tca_first": tca[0]["date"], "tca_sessions": len(tca),
        "tca_orders": sum(int(r["n_orders"]) for r in tca),
        "tca_orders_filled_in_full": sum(int(r["n_full"]) for r in tca),
        "fill_vs_close_bp_session_median": round(statistics.median(bp), 2),
        "fill_vs_close_bp_session_mean": round(statistics.fmean(bp), 2),
        "fill_pnl_usd": round(sum(_num(r["auction_fill_pnl_usd"]) or 0.0 for r in traded), 2),
        "hold_pnl_usd": round(sum(_num(r["auction_hold_pnl_usd"]) or 0.0 for r in traded), 2),
    }


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    root = Path(argv[1])
    out = [book_baseline(root, b) for b in ("cef", "c4")]
    dest = Path(__file__).with_name("baseline.csv")
    with dest.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(r)


if __name__ == "__main__":
    main(sys.argv)
