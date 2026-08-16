"""Re-stage the universe with full OHLC, for microstructure-noise estimation.

The original panel kept only closes. Roll (1984) needs returns; Corwin-Schultz
(2012) needs daily high/low; and a bounce-free mid proxy needs (H+L)/2. All three
are needed to decide whether the lag-1 reversal is real or bid-ask bounce.

Same PIT discipline as stage_universe.py: yfinance `Close` is ALREADY split
adjusted with auto_adjust=False, so the split factor must not be applied again.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "rv"
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
from scripts.rv.stage_universe import UNIVERSE  # noqa: E402


def fetch(tkr: str, tries: int = 3):
    for a in range(tries):
        try:
            h = yf.Ticker(tkr).history(period="max", auto_adjust=False, actions=True)
            if h is None or h.empty:
                raise ValueError("empty")
            h = h.reset_index()
            d = pd.DataFrame({
                "date": pd.to_datetime(h["Date"]).dt.tz_localize(None).dt.normalize(),
                "ticker": tkr,
                "open": h["Open"].astype(float),
                "high": h["High"].astype(float),
                "low": h["Low"].astype(float),
                "close": h["Close"].astype(float),
                "volume": h["Volume"].astype(float),
                "dividend": h.get("Dividends", pd.Series(0.0, index=h.index)).astype(float),
            })
            return d.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        except Exception as exc:
            if a == tries - 1:
                print(f"  !! {tkr}: {exc}")
                return None
            time.sleep(1.5 * (a + 1))


def main() -> int:
    frames = []
    for t in UNIVERSE:
        d = fetch(t)
        if d is None:
            continue
        prev = d["close"].shift(1)
        d["ret_total"] = (d["close"] + d["dividend"]) / prev - 1.0
        d.loc[d.index[0], "ret_total"] = np.nan
        # bounce-free price proxies
        d["mid_hl"] = (d["high"] + d["low"]) / 2.0
        d["ret_mid"] = d["mid_hl"] / d["mid_hl"].shift(1) - 1.0
        frames.append(d)
        print(f"  {t:5s} {len(d):>6,} rows  {d['date'].min().date()} -> {d['date'].max().date()}")
    p = pd.concat(frames, ignore_index=True)
    p.to_parquet(OUT / "etf_ohlc.parquet", index=False)
    print(f"\n{p.shape} -> {OUT/'etf_ohlc.parquet'}")

    # sanity: mid-based returns must track close-based returns closely
    piv_c = p.pivot(index="date", columns="ticker", values="ret_total")
    piv_m = p.pivot(index="date", columns="ticker", values="ret_mid")
    common = piv_c.notna() & piv_m.notna()
    corr = {c: piv_c[c][common[c]].corr(piv_m[c][common[c]]) for c in piv_c.columns}
    s = pd.Series(corr).sort_values()
    print("\ncorr(close-ret, mid-ret) — lowest 6:")
    print(s.head(6).round(4).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
