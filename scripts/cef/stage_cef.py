"""Credit closed-end funds: price and NAV history.

WHY CEFs, AFTER THE ETF PREMIUM/DISCOUNT TRADE DIED. An ETF has authorised
participants who can create and redeem shares against the underlying basket, and
that machine is exactly what compressed the HYG/JNK dislocation from 188bp in
2008 to 3.8bp today. We measured the corpse.

A closed-end fund has NO such machine. Its share count is fixed at IPO. Nothing
mechanically pulls the price toward net asset value, so credit CEFs trade at
discounts of 5-20% -- hundreds of times wider than any ETF gap -- and those
discounts persist and revert. Same asset class, same economic question, entirely
different plumbing, and the specific force that killed the ETF version does not
exist here.

Yahoo carries CEF NAVs under the legacy NASDAQ convention X<TICKER>X (NVG -> XNVGX).

Universe is credit ONLY: municipal, high yield, bank loan, EM debt, and
multi-sector credit. No equity CEFs, no covered-call funds.
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
OUT.mkdir(parents=True, exist_ok=True)

UNIVERSE = {
    "muni":  ["NVG", "NEA", "NAD", "NZF", "MYD", "MQY", "VKQ", "VMO", "NAN",
              "NXP", "MUE", "MHD", "MFM", "BFK", "BTA", "MVF", "NIM", "PMM"],
    "hy":    ["HYT", "HIO", "HIX", "DHY", "AWF", "ISD", "EAD", "GHY", "HYB",
              "PHD", "BGH", "HNW"],
    "loan":  ["BGT", "EFT", "EFR", "JFR", "JRO", "VVR", "NSL", "FCT", "BSL"],
    "emd":   ["EMD", "MSD", "TEI", "EDD", "EDF", "EDI"],
    "multi": ["PDI", "PTY", "PCN", "PFN", "PFL", "DSL", "DBL", "JPS", "PHK",
              "PDO", "PCI", "PKO", "BIT", "BGB", "HFRO"],
}
MIN_DAYS = 750          # ~3 years of price history
MIN_NAV = 200           # a NAV series short of this is not usable


def grab(tk: str):
    px = yf.Ticker(tk).history(period="max", auto_adjust=False)
    if len(px) < MIN_DAYS:
        return None, None
    nav = yf.Ticker(f"X{tk}X").history(period="max", auto_adjust=False)
    if len(nav) < MIN_NAV:
        return px, None
    return px, nav


def main() -> int:
    rows, navs, meta = [], [], []
    for grp, tickers in UNIVERSE.items():
        for tk in tickers:
            try:
                px, nav = grab(tk)
            except Exception as e:
                print(f"  ERR {tk:<6} {type(e).__name__}")
                continue
            if px is None:
                print(f"  skip {tk:<6} price history too short")
                continue
            if nav is None:
                print(f"  skip {tk:<6} no usable NAV feed")
                continue
            p = px.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
            p.columns = ["date", "open", "high", "low", "close", "volume"]
            p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None).dt.normalize()
            p["ticker"], p["grp"] = tk, grp
            n = nav.reset_index()[["Date", "Close"]]
            n.columns = ["date", "nav"]
            n["date"] = pd.to_datetime(n["date"]).dt.tz_localize(None).dt.normalize()
            n["ticker"] = tk
            rows.append(p); navs.append(n)
            adv = (p.close * p.volume).tail(21).mean()
            meta.append(dict(ticker=tk, grp=grp, n_px=len(p), n_nav=len(n),
                             start=p.date.min().date(), adv_musd=adv / 1e6,
                             last=p.close.iloc[-1]))
            print(f"  OK  {tk:<6} {grp:<6} px={len(p):>5,} nav={len(n):>5,} "
                  f"from {p.date.min().date()}  ADV ${adv/1e6:>6.1f}M")
    if not rows:
        print("nothing staged"); return 1
    P = pd.concat(rows, ignore_index=True)
    N = pd.concat(navs, ignore_index=True)
    P.to_parquet(OUT / "cef_prices.parquet", index=False)
    N.to_parquet(OUT / "cef_nav.parquet", index=False)
    M = pd.DataFrame(meta).sort_values("adv_musd", ascending=False)
    M.to_csv(OUT / "cef_universe.csv", index=False)
    print(f"\n  staged {len(M)} credit CEFs, {len(P):,} price rows, {len(N):,} NAV rows")
    print(f"  tradable at $640k (ADV > $3M): {(M.adv_musd > 3).sum()}")
    print(f"  wrote {OUT}/cef_prices.parquet, cef_nav.parquet, cef_universe.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
