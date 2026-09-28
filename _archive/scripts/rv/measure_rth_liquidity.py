"""Measure REAL RTH spread and depth-at-touch for the credit universe.

Why this exists
---------------
The whole credit-RV verdict turns on one number: market impact for a ~$1m order.
My backtest used a square-root law calibrated on single stocks, which charged
~3.5bp per trade and turned a +0.56 gross Sharpe into -0.62 net.  ETFs are not
single stocks - authorised participants supply elastic inventory - so that model
may be badly wrong.

Depth at the touch settles it empirically.  If HYG shows $4m on the bid, a $1m
order crosses the spread and is done: impact is ~0, not 3.5bp.  If it shows
$200k, the square-root model is right and the strategy is dead.

Run this DURING regular trading hours (09:30-16:00 ET).  It takes repeated
snapshots and reports, per instrument:

  * quoted half-spread in bp        -> replaces the tick-floor estimates
  * dollar depth at bid and ask     -> how much trades with no impact
  * $1m order as a multiple of touch depth -> the impact question, answered

Usage:
    python3 scripts/rv/measure_rth_liquidity.py --snapshots 12 --interval 20
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "credit_rv"
OUT.mkdir(parents=True, exist_ok=True)

TICKERS = [
    "HYG", "JNK", "USHY", "SPHY", "SHYG", "SJNK", "HYGH",
    "FALN", "ANGL", "LQD", "VCSH", "VCIT", "VCLT", "IGSB", "LQDH",
    "BKLN", "SRLN", "JAAA", "JBBB", "EMB", "PFF", "CWB",
    "SHY", "IEI", "IEF", "TLT", "GOVT", "BIL", "SPY", "AGG",
]
ORDER_USD = 1_000_000.0


def in_rth(ts: datetime) -> bool:
    et = ts.astimezone(ZoneInfo("America/New_York"))
    return et.weekday() < 5 and dtime(9, 30) <= et.time() <= dtime(16, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", type=int, default=12)
    ap.add_argument("--interval", type=float, default=20.0, help="seconds between snapshots")
    ap.add_argument("--client-id", type=int, default=32)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--force", action="store_true", help="run even outside RTH")
    args = ap.parse_args()

    now = datetime.now(ZoneInfo("America/New_York"))
    rth = in_rth(now)
    if not rth and not args.force:
        print(f"NOT RTH ({now:%Y-%m-%d %H:%M %Z}). Quotes would be stale and wide.")
        print("Re-run between 09:30 and 16:00 ET, or pass --force to record anyway.")
        return 1

    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("FATAL: ib_insync not importable")
        return 2

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=20)
    except Exception as exc:
        print(f"FATAL: connect failed: {type(exc).__name__}: {exc}")
        return 2
    print(f"connected {now:%Y-%m-%d %H:%M:%S %Z}  RTH={rth}  "
          f"{args.snapshots} snapshots @ {args.interval}s")

    ib.reqMarketDataType(1 if rth else 3)      # live if we can, delayed otherwise

    contracts = {}
    for t in TICKERS:
        try:
            c = Stock(t, "SMART", "USD")
            ib.qualifyContracts(c)
            contracts[t] = c
        except Exception as exc:
            print(f"  qualify failed {t}: {exc}")

    tickers = {t: ib.reqMktData(c, "", False, False) for t, c in contracts.items()}
    ib.sleep(3)

    rows = []
    for snap in range(args.snapshots):
        ib.sleep(args.interval)
        stamp = datetime.now(ZoneInfo("America/New_York"))
        for t, tk in tickers.items():
            bid, ask = tk.bid, tk.ask
            bs, asz = tk.bidSize, tk.askSize
            if not (bid and ask and bid > 0 and ask > 0):
                continue
            mid = (bid + ask) / 2
            rows.append({
                "snapshot": snap, "ts": stamp.isoformat(), "ticker": t,
                "bid": bid, "ask": ask, "mid": mid,
                "half_spread_bp": (ask - bid) / 2 / mid * 1e4,
                "bid_depth_usd": (bs or 0) * 100 * bid,   # IB sizes are in lots
                "ask_depth_usd": (asz or 0) * 100 * ask,
            })
        print(f"  snapshot {snap+1}/{args.snapshots} at {stamp:%H:%M:%S}")

    for c in contracts.values():
        ib.cancelMktData(c)
    ib.disconnect()

    if not rows:
        print("no quotes captured")
        return 1

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "rth_liquidity_raw.csv", index=False)

    g = df.groupby("ticker").agg(
        n=("half_spread_bp", "size"),
        half_spread_bp=("half_spread_bp", "median"),
        half_spread_bp_p90=("half_spread_bp", lambda x: x.quantile(0.9)),
        bid_depth_usd=("bid_depth_usd", "median"),
        ask_depth_usd=("ask_depth_usd", "median"),
    ).reset_index()
    g["touch_depth_usd"] = g[["bid_depth_usd", "ask_depth_usd"]].min(axis=1)
    g["order_vs_touch"] = ORDER_USD / g["touch_depth_usd"].replace(0, np.nan)
    g["impact_free"] = g["order_vs_touch"] <= 1.0
    g = g.sort_values("order_vs_touch")
    g.to_csv(OUT / "rth_liquidity.csv", index=False)

    print("\n=== RTH SPREAD AND DEPTH ===")
    print(g.round(2).to_string(index=False))
    print(f"\n$1m order fits inside the touch for "
          f"{int(g.impact_free.sum())}/{len(g)} instruments.")
    print("If most credit legs are impact-free, the backtest's square-root impact "
          "charge (~3.5bp/trade) is wrong and the strategy deserves a re-run.")

    old = pd.read_csv(OUT / "cost_model.csv") if (OUT / "cost_model.csv").exists() else None
    if old is not None:
        cmp = old.merge(g[["ticker", "half_spread_bp"]], on="ticker",
                        suffixes=("_modelled", "_measured"))
        cmp["ratio"] = cmp.half_spread_bp_measured / cmp.half_spread_bp_modelled
        print("\n=== MODELLED vs MEASURED half-spread ===")
        print(cmp[["ticker", "half_spread_bp_modelled",
                   "half_spread_bp_measured", "ratio"]].round(2).to_string(index=False))
        cmp.to_csv(OUT / "cost_model_vs_measured.csv", index=False)

    (OUT / "rth_liquidity_meta.json").write_text(json.dumps(
        {"ts": now.isoformat(), "rth": rth, "snapshots": args.snapshots,
         "interval_s": args.interval, "order_usd": ORDER_USD}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
