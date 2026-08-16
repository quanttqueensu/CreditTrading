"""Do our prices agree with the broker's?

WHY THIS EXISTS. On 2026-07-31 the first live fills came in as much as 2.9% away
from the price our signal was computed on. Three things could cause that and they
have completely different implications:

  1. A genuine overnight move          -> nothing is wrong, the market moved
  2. Our price source disagrees with   -> the signal itself is wrong and every
     the broker's                         backtest number is built on bad prices
  3. Paper-account fill fiction        -> the fills are not measuring anything

Until we know which, no slippage number means anything, and slippage is the one
thing the live deployment exists to measure.

This compares our staged closes (yfinance) against the broker's own daily bars
for the same instruments and dates. If they agree, cause 2 is eliminated and the
gap is real market movement or paper fiction. If they disagree, our research
prices are wrong and that is far more serious than any execution problem.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
OUT = REPO / "results/cef"


def main() -> int:
    from src.deploy.broker.ibkr import IBKRBroker

    spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
    uni = spec["frozen"]["universe"]
    ours = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    ours["date"] = pd.to_datetime(ours["date"])

    b = IBKRBroker(verbose=False)
    b.connect()
    rows = []
    try:
        import ib_async as ibi
        for tk in uni:
            try:
                c = ibi.Stock(tk, "SMART", "USD")
                b.ib.qualifyContracts(c)
                bars = b.ib.reqHistoricalData(
                    c, endDateTime="", durationStr="10 D", barSizeSetting="1 day",
                    whatToShow="TRADES", useRTH=True, formatDate=1)
                if not bars:
                    rows.append(dict(ticker=tk, note="no broker bars"))
                    continue
                ib_df = pd.DataFrame(
                    [{"date": pd.Timestamp(x.date), "ib_close": x.close,
                      "ib_vol": x.volume} for x in bars])
                mine = ours[ours.ticker == tk][["date", "close", "volume"]]
                j = ib_df.merge(mine, on="date", how="inner")
                if j.empty:
                    rows.append(dict(ticker=tk, note="no overlapping dates"))
                    continue
                j["diff_pct"] = 100.0 * (j["close"] - j["ib_close"]) / j["ib_close"]
                last = j.sort_values("date").iloc[-1]
                rows.append(dict(
                    ticker=tk, n_days=len(j),
                    last_date=str(last["date"].date()),
                    ours=float(last["close"]), broker=float(last["ib_close"]),
                    last_diff_pct=float(last["diff_pct"]),
                    max_abs_diff_pct=float(j["diff_pct"].abs().max()),
                    median_abs_diff_pct=float(j["diff_pct"].abs().median()),
                    note=""))
            except Exception as e:
                rows.append(dict(ticker=tk, note=f"{type(e).__name__}: {e}"))
            b.ib.sleep(0.4)
    finally:
        b.disconnect()

    r = pd.DataFrame(rows)
    r.to_csv(OUT / "price_reconciliation.csv", index=False)
    ok = r[r.note == ""] if "note" in r else r
    print("=" * 88)
    print("OUR PRICES vs THE BROKER'S, same instrument, same dates")
    print("=" * 88)
    if ok.empty:
        print("  no comparable data returned")
        print(r.to_string(index=False))
        return 1
    print(f"{'tkr':<6}{'days':>6}{'last date':>13}{'ours':>9}{'broker':>9}"
          f"{'last diff':>11}{'median':>9}{'worst':>9}")
    for _, x in ok.sort_values("max_abs_diff_pct", ascending=False).iterrows():
        flag = "  <-- CHECK" if x.max_abs_diff_pct > 0.5 else ""
        print(f"{x.ticker:<6}{x.n_days:>6.0f}{x.last_date:>13}{x.ours:>9.2f}"
              f"{x.broker:>9.2f}{x.last_diff_pct:>10.2f}%{x.median_abs_diff_pct:>8.2f}%"
              f"{x.max_abs_diff_pct:>8.2f}%{flag}")
    med = ok.median_abs_diff_pct.median()
    worst = ok.max_abs_diff_pct.max()
    print(f"\n  median disagreement across funds : {med:.3f}%")
    print(f"  worst single day                 : {worst:.2f}%")
    print()
    if med < 0.05 and worst < 0.5:
        print("  VERDICT: our prices match the broker's. The fill gap is NOT a data")
        print("  problem -- it is real overnight movement or paper-fill fiction.")
    else:
        print("  VERDICT: our price source DISAGREES with the broker. This is more")
        print("  serious than any execution issue: the signal is computed off these")
        print("  prices, so the research itself rests on them.")
    bad = r[r.note != ""] if "note" in r else pd.DataFrame()
    if len(bad):
        print(f"\n  {len(bad)} funds returned no comparable data:")
        for _, x in bad.iterrows():
            print(f"    {x.ticker:<6} {x.note}")
    print(f"\nwrote {OUT/'price_reconciliation.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
