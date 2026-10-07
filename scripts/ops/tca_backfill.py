"""Read-only TCA backfill for sessions verify could not score.

    QUANTT_ENV_FILE=<key file> python3 scripts/ops/tca_backfill.py 2026-09-30 2026-10-01 2026-10-07

WHY. verify crashed on 2026-09-30 and 10-01 (Alpaca reports short-opening fills
as side "sell_short"; fixed 415eb59) and cannot be re-run for a past day by
design (it derives the book held into the close from positions read after it).
Slippage does not need that: it is each fill against the day's official
closing print. This script reads Alpaca's FILL activities and orders for each
date and the primary-exchange official close (condition M, verify.fetch_prints
-- the same function and rule verify uses), and prints one table per day plus
a summary. It never writes to the broker, data/ or the state dir; output goes
to stdout (redirect it into results/ops/ if keeping it).

SIGN: + = worse than the official close (buy paid more, sell received less).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from quantt.broker.alpaca import AlpacaClient          # noqa: E402
from quantt.session.verify import fetch_prints, parse_fill   # noqa: E402


def day_report(c, day: dt.date) -> dict:
    fills = [parse_fill(a) for a in c.activities_fills(day)]
    nxt = day + dt.timedelta(days=1)
    orders = c._get(c._base, "/v2/orders", {"status": "all", "limit": 500,
                                            "after": f"{day}T00:00:00Z", "until": f"{nxt}T04:00:00Z"})
    orders = [o for o in orders if o["client_order_id"].startswith(f"cef-{day:%Y%m%d}-")]
    prints = fetch_prints(c, sorted({f.symbol for f in fills}), day, condition="M")
    by = {}
    for f in fills:
        k = (f.symbol, f.side)
        q, v = by.get(k, (0, 0.0))
        by[k] = (q + f.qty, v + f.qty * f.price)
    rows, wsum = [], {"buy": [0.0, 0.0], "sell": [0.0, 0.0]}
    for (sym, side), (q, v) in sorted(by.items()):
        vwap, a = v / q, prints.prices.get(sym)
        bp = None if a is None else ((vwap - a) / a if side == "buy" else (a - vwap) / a) * 1e4
        rows.append((sym, side, q, vwap, a, bp, prints.gaps.get(sym, "")))
        if bp is not None:
            wsum[side][0] += q * a * bp
            wsum[side][1] += q * a
    ordered = sum(int(o["qty"]) for o in orders)
    filled = sum(int(float(o["filled_qty"])) for o in orders)
    first = min((o["submitted_at"] for o in orders), default="")
    agg = {s: (w[0] / w[1] if w[1] else None) for s, w in wsum.items()}
    tot_w = wsum["buy"][1] + wsum["sell"][1]
    agg["all"] = (wsum["buy"][0] + wsum["sell"][0]) / tot_w if tot_w else None
    return {"day": day, "rows": rows, "orders": len(orders), "ordered": ordered,
            "filled": filled, "first_submit": first, "agg": agg,
            "tifs": sorted({o["time_in_force"] for o in orders})}


def main(argv) -> int:
    days = [dt.date.fromisoformat(x) for x in argv]
    if not days:
        print(__doc__)
        return 2
    c = AlpacaClient.from_environment("cef")
    f = lambda x: "UNMEASURED" if x is None else f"{x:+.1f}"
    for d in days:
        r = day_report(c, d)
        print(f"\n## {d}  orders {r['orders']} ({','.join(r['tifs'])}), first submit "
              f"{r['first_submit'][11:19]}Z, shares filled {r['filled']}/{r['ordered']}")
        print("| symbol | side | qty | vwap | official close | bp (+ worse) |")
        print("|---|---|---:|---:|---:|---:|")
        for sym, side, q, vwap, a, bp, gap in r["rows"]:
            print(f"| {sym} | {side} | {q} | {vwap:.4f} | {'' if a is None else f'{a:.4f}'} | "
                  f"{f(bp)}{' ' + gap if gap else ''} |")
        print(f"\nnotional-weighted: buy {f(r['agg']['buy'])}bp, sell {f(r['agg']['sell'])}bp, "
              f"all {f(r['agg']['all'])}bp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
