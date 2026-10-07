"""Daily transaction-cost analysis: one row per verified session in <state>/tca.csv.

WHY (execution-desk review, 2026-10-07). The book now sends market `day` orders
at 15:52 on paper (docs/RUNNER.md "Paper execution"), and the questions an
execution desk asks every day were answered nowhere: did everything fill, how
far from the official close (the backtest's shift(2) execution price) did it
fill, and did the book end where the plan said. `scores.csv` carries P&L and
one blended bp figure under a header guard that must not change, so this is a
separate file. Every figure is read from what verify already measured (order
rows, fills scored against the primary-exchange official close, positions
after the close, the plan's targets); nothing is estimated here.

SIGN: slippage bp is positive when we did WORSE than the official close
(score.py convention): buy (vwap - A)/A, sell (A - vwap)/A, x 1e4.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

COLUMNS = ("date", "book", "n_orders", "n_full", "shares_ordered", "shares_filled",
           "fill_rate_shares", "slip_bp_buy", "slip_bp_sell", "slip_bp_all", "slip_unmeasured",
           "residual_gross_usd", "residual_net_usd", "residual_names", "basis")
BASIS = ("fills vs primary-exchange official close (condition M), notional-weighted; "
         "residual = positions after the close vs the plan's ORDER targets at the official close")


def _wavg(rows) -> float | None:
    w = sum(n for n, _ in rows)
    return None if w <= 0 else sum(n * b for n, b in rows) / w


def tca_row(date: str, book: str, detail: dict, per_symbol: list, plan: dict | None) -> dict:
    """The row for one day. `detail` and `per_symbol` are verify's own records."""
    orders = detail.get("orders") or []
    ordered = sum(int(o.get("qty") or 0) for o in orders)
    filled = sum(int(float(o.get("filled_qty") or 0)) for o in orders)
    n_full = sum(1 for o in orders if o.get("qty") and
                 int(float(o.get("filled_qty") or 0)) == int(o["qty"]))
    by_side, unmeasured = {"buy": [], "sell": []}, []
    for ps in per_symbol:
        a = ps.get("auction_d")
        for sd in ps.get("sides") or []:
            if sd.get("bp_vs_auction") is None or a is None:
                unmeasured.append(f"{ps.get('symbol')} {sd.get('side')}")
                continue
            by_side[sd["side"]].append((sd["qty"] * a, sd["bp_vs_auction"]))
    buy, sell = _wavg(by_side["buy"]), _wavg(by_side["sell"])
    allb = _wavg(by_side["buy"] + by_side["sell"])
    res_g = res_n = None
    names = []
    prices = (detail.get("auction_prints_d") or {}).get("prices") or {}
    if plan and plan.get("targets"):
        after = detail.get("positions_after") or {}
        # Intended = what the SENT plan's orders aimed at (a deliberate bp_shortfall
        # scale-down is not a fill shortfall; review 2026-10-07), else unchanged.
        intended = {s: int(t["current"]) for s, t in plan["targets"].items()}
        for o in plan.get("orders") or []:
            intended[o["symbol"]] = int(o["target"])
        res_g = res_n = 0.0
        for s, tgt in intended.items():
            gap = int(after.get(s, 0)) - tgt
            if not gap:
                continue
            # Official close when verify fetched one; otherwise the plan's as-of
            # close, TAGGED (review 2026-10-07): never passed off as today's print.
            tag = ""
            px = prices.get(s)
            if px is None:
                px = (plan.get("closes") or {}).get(s)
                tag = "(prior close)"
            if px is None:
                names.append(f"{s}:{gap:+d}(unpriced)")
                continue
            res_g += abs(gap) * px
            res_n += gap * px
            names.append(f"{s}:{gap:+d}{tag}")
    f = lambda x: "" if x is None else f"{x:.2f}"
    return {"date": date, "book": book, "n_orders": len(orders), "n_full": n_full,
            "shares_ordered": ordered, "shares_filled": filled,
            "fill_rate_shares": "" if not ordered else f"{filled / ordered:.4f}",
            "slip_bp_buy": f(buy), "slip_bp_sell": f(sell), "slip_bp_all": f(allb),
            "slip_unmeasured": " | ".join(unmeasured),
            "residual_gross_usd": f(res_g), "residual_net_usd": f(res_n),
            "residual_names": " ".join(names), "basis": BASIS}


def append(path: Path, row: dict) -> None:
    """Append, header on a new file; a file with someone else's header raises."""
    new = not path.exists() or path.stat().st_size == 0
    if not new:
        with path.open(newline="") as fh:
            header = next(csv.reader(fh), None)
        if tuple(header or ()) != COLUMNS:
            raise ValueError(f"{path} header {header} is not {list(COLUMNS)}")
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)


def plan_for(state_dir: Path, date: str) -> dict | None:
    p = state_dir / date / "plan.json"
    return json.loads(p.read_text()) if p.exists() else None
