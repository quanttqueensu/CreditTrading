"""Daily borrow-fee HISTORY for the CEF panel from IBKR's FEE_RATE bars.

    python3 scripts/cef/fetch_borrow_history.py            # 5 years, all 44 names
    python3 scripts/cef/fetch_borrow_history.py --years 1 --tickers NAD,HYT

Writes data/cef/cef_borrow_history.parquet: date, ticker, fee_rate_pct.

WHY THIS CHANGES THE BORROW RESEARCH
------------------------------------
Until 2026-09-10 the programme believed borrow fees existed only as a daily
snapshot (IBKR's public shortstock file), so every borrow number in the repo --
BORROW_NOTE_2026-09-06, the 1.22%/yr drag, P1.1's cap, P1.2's scoring -- applied
ONE day of fees to 21 years of history and said so ("a counterfactual, not a
backtest"). Found while replacing the retired file: `reqHistoricalData(
whatToShow="FEE_RATE", barSizeSetting="1 day")` serves a daily fee series
years deep (NAD: 1,249 bars, 2021-09-13 -> 2026-09-09, 6.78% -> 10.21%). The
values match the file exactly where both exist (09-04: AWF 0.28, NEA 3.06,
NVG 4.23), and they show the file's AWF 0.28% was a one-day dip in a 3.3-3.7%
series -- the number P1.2's worked example was built on.

So borrow drag can be MEASURED over 2021-2026 by name and by group, and every
short-leg decision (P1.1, P1.2, P6.6, P6.2's between sleeve) gets a real panel.
Availability (shares) is still snapshot-only; this file carries fees.

Sequential, one name at a time, two tries, sleeps between requests: IBKR's
historical service throttles bursts and the first request after connecting
routinely times out on its own.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:            # run as a script, not -m
    sys.path.insert(0, str(REPO))
from ops.common import atomic_write      # noqa: E402
OUT = REPO / "data/cef/cef_borrow_history.parquet"
UNIVERSE_CSV = REPO / "data/cef/cef_universe.csv"
SPEC = REPO / "ops/specs/cef_discount.frozen.json"
IB_HOST, IB_PORT, IB_CLIENT_ID = "127.0.0.1", 4002, 78


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--tickers", default="", help="comma list; default: the 44-name panel")
    a = ap.parse_args(argv)

    if a.tickers:
        names = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    elif UNIVERSE_CSV.exists():
        names = sorted(pd.read_csv(UNIVERSE_CSV)["ticker"].unique())
    else:
        names = json.loads(SPEC.read_text())["frozen"]["universe"]

    from ib_async import IB, Stock, util
    util.logToConsole(50)
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, readonly=True, timeout=20)
    frames, failed = [], []
    try:
        for i, t in enumerate(names, 1):
            try:
                c = ib.qualifyContracts(Stock(t, "SMART", "USD"))[0]
            except Exception as e:
                failed.append((t, f"qualify: {type(e).__name__}"))
                continue
            bars = []
            for _ in range(2):
                try:
                    bars = ib.reqHistoricalData(
                        c, endDateTime="", durationStr=f"{a.years} Y",
                        barSizeSetting="1 day", whatToShow="FEE_RATE",
                        useRTH=True, formatDate=1, timeout=90)
                except Exception:
                    bars = []
                if bars:
                    break
                time.sleep(3)
            if not bars:
                failed.append((t, "no FEE_RATE bars"))
                print(f"  {i:>2}/{len(names)} {t:<5} none", flush=True)
                continue
            df = pd.DataFrame({"date": pd.to_datetime([str(b.date) for b in bars]),
                               "ticker": t,
                               "fee_rate_pct": [round(float(b.close) * 100, 4) for b in bars]})
            frames.append(df)
            print(f"  {i:>2}/{len(names)} {t:<5} {len(df):>5} bars  {df.date.min().date()} -> "
                  f"{df.date.max().date()}  last {df.fee_rate_pct.iloc[-1]:.2f}%", flush=True)
            time.sleep(1.5)
    finally:
        ib.disconnect()

    if not frames:
        print("nothing fetched")
        return 1
    new = pd.concat(frames, ignore_index=True)
    if OUT.exists():
        old = pd.read_parquet(OUT)
        new = (pd.concat([old, new], ignore_index=True)
                 .drop_duplicates(subset=["date", "ticker"], keep="last"))
    new = new.sort_values(["ticker", "date"]).reset_index(drop=True)
    atomic_write(new, OUT)
    print(f"wrote {OUT.relative_to(REPO)}: {len(new):,} rows, {new.ticker.nunique()} names, "
          f"{new.date.min().date()} -> {new.date.max().date()}")
    if failed:
        print("failed:", "; ".join(f"{t} ({why})" for t, why in failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
