"""Re-stage the universe with full OHLC, for microstructure-noise estimation.

The original panel kept only closes. Roll (1984) needs returns; Corwin-Schultz
(2012) needs daily high/low; and a bounce-free mid proxy needs (H+L)/2. All three
are needed to decide whether the lag-1 reversal is real or bid-ask bounce.

Same PIT discipline as stage_universe.py: yfinance `Close` is ALREADY split
adjusted with auto_adjust=False, so the split factor must not be applied again.

RESTORED 2026-10-11 (RESEARCH_PLAN_2026-10-09 item 0.1) from tag
`pre-clean-slate`; `data/rv/etf_ohlc.parquet` had no fetcher. Changes:

  * SOURCE BY DATE. Rows on or before `YF_LAST` (2026-07-29, the old panel's
    last date) are yfinance as before; later rows are Alpaca daily bars (SIP,
    raw OHLC, cash dividends from Alpaca corporate actions;
    `scripts/rv/alpaca_daily.py`), cross-checked against yfinance on
    ret_total AND ret_mid over 2025-01-02..yesterday, gate 5bp, before
    anything is written. The universe (and so EFA, EEM, GLD, DBC, added
    2026-10-11) comes from stage_universe.UNIVERSE as it always did.
  * WHY THE OLD LAST ROW DOES NOT REBUILD. The panel was written 2026-07-29
    10:46 EDT, during the session, so its 2026-07-29 row is an INTRADAY bar
    (TLT close 83.945 against a final 82.85; HYG volume 9.8m against 53.1m).
    The rebuild carries the final bar for that date. Measured 2026-10-11 with
    `scripts/rv/panel_identity.py`; numbers in docs/REFERENCES.md §8.
  * `--out-dir` (default `data/rv`); a fetch failure RAISES instead of
    writing a panel without the ticker.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "rv"

sys.path.insert(0, str(ROOT))
from scripts.rv.stage_universe import UNIVERSE  # noqa: E402

# yfinance on or before this date (the old panel's last date), Alpaca after.
YF_LAST = "2026-07-29"
VALIDATE_FROM = "2025-01-02"


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", type=Path, default=OUT, help="default data/rv")
    out = ap.parse_args(argv).out_dir
    out.mkdir(parents=True, exist_ok=True)
    from scripts.rv import alpaca_daily as ad

    seam = pd.Timestamp(YF_LAST)
    fetched, failed = {}, []
    for t in UNIVERSE:
        d = fetch(t)
        if d is None:
            failed.append(t)
            continue
        prev = d["close"].shift(1)
        d["ret_total"] = (d["close"] + d["dividend"]) / prev - 1.0
        d.loc[d.index[0], "ret_total"] = np.nan
        # bounce-free price proxies
        d["mid_hl"] = (d["high"] + d["low"]) / 2.0
        d["ret_mid"] = d["mid_hl"] / d["mid_hl"].shift(1) - 1.0
        fetched[t] = d
    if failed:
        raise RuntimeError(f"yfinance fetch failed for {failed}; nothing written")

    alp, stats = ad.continue_after(pd.concat(fetched.values(), ignore_index=True),
                                   YF_LAST, VALIDATE_FROM, ohlc=True)
    print("--- alpaca vs yfinance (ret_total, ret_mid; in-house on each side) ---")
    print(stats.to_string(index=False))

    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "dividend",
            "ret_total", "mid_hl", "ret_mid"]
    frames = []
    for t in UNIVERSE:
        d = fetched[t]
        d = d[d["date"] <= seam]
        tail = alp.loc[alp["ticker"] == t, cols]
        d = pd.concat([d, tail], ignore_index=True)
        frames.append(d)
        print(f"  {t:5s} {len(d):>6,} rows  {d['date'].min().date()} -> {d['date'].max().date()}"
              f"  (alpaca after {YF_LAST}: {len(tail)})")
    p = pd.concat(frames, ignore_index=True)
    assert not p.duplicated(["ticker", "date"]).any(), "dup ticker/date"
    p.to_parquet(out / "etf_ohlc.parquet", index=False)
    print(f"\n{p.shape} -> {out/'etf_ohlc.parquet'}")

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
