"""Measure displayed size at the touch, per name, from IBKR historical BID_ASK ticks.

WHY
---
`fetch_ibkr_spreads.py` establishes that these ETFs quote one cent wide. That is
necessary but NOT sufficient to claim the book pays only the half-spread. The cost
model (src/strategies/credit_rv/costs.py §2) assumes impact is a THRESHOLD
function — zero inside the displayed touch, square-root on the excess only. That
assumption is doing real work, and it is unverified.

This measures the other half: how many dollars actually sit at the best bid/offer.
If a $70k clip is small against displayed size, "fills at the quote" is a fair
description and the measured half-spread IS the cost. If it is not, the book pays
more than the spread and the measured-cost result is optimistic.

`reqHistoricalTicks` with whatToShow='BID_ASK' returns tick-level quotes WITH
sizes, up to 1000 per request, which is plenty for a depth distribution.

Usage:
    python3 scripts/rv/measure_touch_depth.py --spec ops/specs/credit_rv.frozen.json
    python3 scripts/rv/measure_touch_depth.py --tickers HYG,JNK,LQD
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "credit_rv"
OUT.mkdir(parents=True, exist_ok=True)


def _ib_module():
    try:
        import ib_async as m
        return m
    except ImportError:
        import ib_insync as m
        return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--client-id", type=int, default=43)
    ap.add_argument("--spec", default=None)
    ap.add_argument("--tickers", default=None)
    ap.add_argument("--clip-usd", type=float, default=70_000.0,
                    help="the per-name dollar clip to judge depth against")
    ap.add_argument("--sessions", type=int, default=3,
                    help="how many recent sessions to sample")
    args = ap.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.spec:
        tickers = list(json.loads(Path(args.spec).read_text())["frozen"]["universe"])
    else:
        print("need --spec or --tickers")
        return 2

    mod = _ib_module()
    ib = mod.IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=25)
    except Exception as exc:
        print(f"FATAL: connect failed: {type(exc).__name__}: {exc}")
        return 2
    print(f"connected: {ib.isConnected()}   clip ${args.clip_usd:,.0f}/name")

    et = ZoneInfo("America/New_York")
    rows = []
    for t in tickers:
        c = mod.Stock(t, "SMART", "USD")
        q = ib.qualifyContracts(c)
        if not q:
            print(f"  {t:5s} !! could not qualify")
            continue
        c = q[0]

        samples = []
        # sample the closing window of the last few sessions
        day = datetime.now(et)
        taken = 0
        while taken < args.sessions and (datetime.now(et) - day).days < 12:
            if day.weekday() < 5:
                end = day.replace(hour=15, minute=59, second=0, microsecond=0)
                try:
                    ticks = ib.reqHistoricalTicks(
                        c, startDateTime="", endDateTime=end,
                        numberOfTicks=1000, whatToShow="BID_ASK",
                        useRth=True, ignoreSize=False)
                except Exception as exc:
                    print(f"  {t:5s} !! ticks failed: {str(exc)[:90]}")
                    ticks = []
                time.sleep(2.0)
                if ticks:
                    taken += 1
                    for k in ticks:
                        bp, ap_ = float(k.priceBid or 0), float(k.priceAsk or 0)
                        bs, as_ = float(k.sizeBid or 0), float(k.sizeAsk or 0)
                        if bp <= 0 or ap_ <= 0 or ap_ <= bp:
                            continue
                        mid = (bp + ap_) / 2.0
                        # IBKR equity tick sizes are in SHARES for these feeds
                        samples.append((mid * bs, mid * as_, (ap_ - bp) / mid * 1e4))
            day -= timedelta(days=1)

        if len(samples) < 50:
            print(f"  {t:5s} only {len(samples)} usable ticks — skipped")
            continue

        arr = np.array(samples)
        bid_usd, ask_usd, spr = arr[:, 0], arr[:, 1], arr[:, 2]
        touch = np.minimum(bid_usd, ask_usd)      # the side we must cross
        med = float(np.median(touch))
        rows.append(dict(
            ticker=t, n_ticks=len(samples),
            median_touch_usd=med,
            p25_touch_usd=float(np.percentile(touch, 25)),
            p10_touch_usd=float(np.percentile(touch, 10)),
            median_spread_bp=float(np.median(spr)),
            clip_usd=args.clip_usd,
            clip_vs_touch=float(args.clip_usd / med) if med > 0 else np.inf,
            pct_ticks_touch_covers_clip=float((touch >= args.clip_usd).mean() * 100),
        ))
        print(f"  {t:5s} n={len(samples):>5d}  median touch ${med:>10,.0f}  "
              f"clip/touch {args.clip_usd/med if med>0 else float('inf'):>6.2f}x  "
              f"covers clip {(touch>=args.clip_usd).mean()*100:>5.1f}% of ticks")

    ib.disconnect()
    if not rows:
        print("\nno depth measured")
        return 3

    df = pd.DataFrame(rows).sort_values("clip_vs_touch")
    df.to_csv(OUT / "touch_depth.csv", index=False)

    print("\n" + "=" * 72)
    print("INTERPRETATION")
    print("=" * 72)
    thin = df[df.clip_vs_touch > 1.0]
    if thin.empty:
        print(f"Every name's median displayed touch exceeds the ${args.clip_usd:,.0f}")
        print("clip. Treating impact as zero inside the touch is supported, and the")
        print("measured half-spread is a fair estimate of the round-trip cost.")
    else:
        print(f"{len(thin)} name(s) show a median touch SMALLER than the clip:")
        for _, r in thin.iterrows():
            print(f"  {r.ticker:5s} touch ${r.median_touch_usd:>10,.0f}  "
                  f"clip is {r.clip_vs_touch:.2f}x displayed size")
        print("\nFor these the zero-impact assumption does NOT hold: the order walks")
        print("the book. Either size them down or drop them — do not report the")
        print("half-spread as their cost.")

    print(f"\nwrote {OUT/'touch_depth.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
