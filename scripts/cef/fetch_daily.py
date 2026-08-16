"""Daily refresh of the credit CEF price and NAV panels.

Run after the US close. Appends only new dates, so it is safe to run repeatedly.

NAV is the load-bearing input here -- the entire strategy is the gap between price
and NAV, so a stale or missing NAV silently turns the signal into noise. The
freshness of every fund's NAV is therefore checked and reported, and any fund
whose NAV has not updated in three business days is flagged so the sleeve can
drop it rather than trade on a stale number.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "cef"
PX_PATH = OUT / "cef_prices.parquet"
NAV_PATH = OUT / "cef_nav.parquet"
STALE_BD = 3


def refresh(period: str = "6mo") -> int:
    if not PX_PATH.exists():
        print("no staged panel; run scripts/cef/stage_cef.py first")
        return 1
    P, N = pd.read_parquet(PX_PATH), pd.read_parquet(NAV_PATH)
    tickers = sorted(P.ticker.unique())
    grp = P.drop_duplicates("ticker").set_index("ticker")["grp"].to_dict()

    newp, newn, stale = [], [], []
    for tk in tickers:
        try:
            px = yf.Ticker(tk).history(period=period, auto_adjust=False)
            nav = yf.Ticker(f"X{tk}X").history(period=period, auto_adjust=False)
        except Exception as e:
            print(f"  ERR {tk:<6} {type(e).__name__}")
            continue
        if len(px):
            p = px.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
            p.columns = ["date", "open", "high", "low", "close", "volume"]
            p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None).dt.normalize()
            p["ticker"], p["grp"] = tk, grp.get(tk, "?")
            newp.append(p)
        if len(nav):
            n = nav.reset_index()[["Date", "Close"]]
            n.columns = ["date", "nav"]
            n["date"] = pd.to_datetime(n["date"]).dt.tz_localize(None).dt.normalize()
            n["ticker"] = tk
            newn.append(n)
            age = len(pd.bdate_range(n.date.max(), pd.Timestamp.today().normalize())) - 1
            if age > STALE_BD:
                stale.append((tk, str(n.date.max().date()), age))

    P = (pd.concat([P] + newp, ignore_index=True)
           .drop_duplicates(subset=["date", "ticker"], keep="last")
           .sort_values(["ticker", "date"]))
    N = (pd.concat([N] + newn, ignore_index=True)
           .drop_duplicates(subset=["date", "ticker"], keep="last")
           .sort_values(["ticker", "date"]))
    P.to_parquet(PX_PATH, index=False)
    N.to_parquet(NAV_PATH, index=False)

    print(f"  prices {len(P):,} rows -> {P.date.max().date()}")
    print(f"  NAV    {len(N):,} rows -> {N.date.max().date()}")
    if stale:
        print(f"  STALE NAV ({len(stale)} funds, >{STALE_BD} business days old) — "
              f"the sleeve must not trade these:")
        for tk, d, age in sorted(stale, key=lambda x: -x[2]):
            print(f"    {tk:<6} last NAV {d}  ({age} bd old)")
    else:
        print(f"  all {N.ticker.nunique()} NAV series fresh within {STALE_BD} bd")
    return 0


if __name__ == "__main__":
    sys.exit(refresh())
