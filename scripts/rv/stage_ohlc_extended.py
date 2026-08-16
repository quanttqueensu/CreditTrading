"""Stage the EXTENDED tradeable universe (~57 tickers) with full OHLC.

Breadth expansion for Grinold IR = IC * sqrt(BR): the core panel
(data/rv/etf_ohlc.parquet, 30 tickers) is left untouched; this writes a parallel
panel at data/rv/etf_ohlc_extended.parquet in the IDENTICAL schema.

Schema/convention parity with scripts/rv/stage_ohlc.py (verified numerically
against the existing parquet, max abs diff 0.0):
    ret_total = (close + dividend) / close.shift(1) - 1      # SIMPLE return
    mid_hl    = (high + low) / 2
    ret_mid   = mid_hl / mid_hl.shift(1) - 1                 # SIMPLE return
First row of each ticker is NaN for both return columns.

PIT / split discipline (see stage_universe.total_return): with
auto_adjust=False yfinance still returns a SPLIT-adjusted Close and Dividends in
those same split-adjusted units, so the split factor must NOT be applied again.

Also writes results/universe/coverage.csv (one row per ticker, sorted by median
21d dollar volume desc) for tradability screening at the current book size.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "rv"
RES_DIR = ROOT / "results" / "universe"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RES_DIR.mkdir(parents=True, exist_ok=True)

OUT_PARQUET = OUT_DIR / "etf_ohlc_extended.parquet"
OUT_COVERAGE = RES_DIR / "coverage.csv"

# ticker -> asset-class group (group is reported, not written to the parquet,
# which must stay schema-identical to etf_ohlc.parquet)
GROUPS: dict[str, list[str]] = {
    "preferred":  ["PFF", "PGX", "PFFD", "PFFA", "FPE"],
    "muni":       ["HYD", "HYMB", "MUB", "SUB", "SHM", "TFI"],
    "intl_em":    ["HYXU", "IBND", "EMHY", "VWOB", "EMLC", "PCY"],
    "loan_clo":   ["BKLN", "SRLN", "JAAA", "JBBB", "CLOI", "SEIX"],
    "ig_bucket":  ["IGSB", "IGIB", "IGLB", "SPSB", "SPIB", "SPLB",
                   "VCSH", "VCIT", "VCLT"],
    "mbs":        ["MBB", "VMBS", "SPMB", "GNMA", "CMBS"],
    "hy":         ["HYG", "JNK", "USHY", "SHYG", "SJNK", "SPHY",
                   "ANGL", "FALN", "HYGH", "FLHY"],
    "rates":      ["SHY", "IEI", "IEF", "TLT", "TLH", "GOVT", "AGG", "BND"],
    "equity":     ["SPY", "QQQ"],
}
TICKER_GROUP = {t: g for g, ts in GROUPS.items() for t in ts}
UNIVERSE = list(TICKER_GROUP)  # insertion-ordered, already de-duplicated


# A ticker returning fewer bars than this is a broken Yahoo series, not a short
# history: it is rejected loudly instead of polluting the panel. (HYXU returns a
# single 2026-07-17 bar under every fetch mode -- period=max/10y/1y, start=...,
# yf.download -- even though the fund is live with ~$69M AUM.)
MIN_ROWS = 60


def fetch(tkr: str, tries: int = 4) -> pd.DataFrame | None:
    """Full daily history, unadjusted-for-dividends OHLC + distributions."""
    for attempt in range(tries):
        try:
            h = yf.Ticker(tkr).history(period="max", auto_adjust=False,
                                       actions=True)
            if h is None or h.empty:
                raise ValueError("empty frame returned")
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
            d["split_f"] = h.get("Stock Splits", pd.Series(0.0, index=h.index)).astype(float)
            d = d.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
            if d.empty:
                raise ValueError("all-NaN closes")
            if len(d) < MIN_ROWS:
                # not a flake -- retrying will not help; fail immediately
                raise RuntimeError(
                    f"only {len(d)} bar(s) available "
                    f"({d['date'].min().date()}..{d['date'].max().date()}) "
                    f"< MIN_ROWS={MIN_ROWS}: broken Yahoo series")
        except RuntimeError as exc:
            print(f"  !! FAILED {tkr}: {exc}")
            return None
        except Exception as exc:
            if attempt == tries - 1:
                print(f"  !! FAILED {tkr}: {type(exc).__name__}: {exc}")
                return None
            time.sleep(2.0 * (attempt + 1))
            continue
        return d
    return None


def main() -> int:
    frames: list[pd.DataFrame] = []
    failed: list[tuple[str, str]] = []
    print(f"--- fetching {len(UNIVERSE)} tickers (yfinance, period=max) ---")
    for t in UNIVERSE:
        d = fetch(t)
        if d is None:
            failed.append((t, TICKER_GROUP[t]))
            continue
        prev = d["close"].shift(1)
        d["ret_total"] = (d["close"] + d["dividend"]) / prev - 1.0
        d["mid_hl"] = (d["high"] + d["low"]) / 2.0
        d["ret_mid"] = d["mid_hl"] / d["mid_hl"].shift(1) - 1.0
        d.loc[d.index[0], ["ret_total", "ret_mid"]] = np.nan
        splits = d.loc[d["split_f"].fillna(0) > 0, ["date", "split_f"]]
        note = ""
        if not splits.empty:
            note = "  SPLITS: " + ",".join(
                f"{r.date.date()}@{r.split_f:g}" for r in splits.itertuples())
        big = d["ret_total"].abs().max()
        flag = f"  MAXRET {big:.1%}" if big > 0.15 else ""
        print(f"  {t:5s} {TICKER_GROUP[t]:10s} {len(d):>6,} rows  "
              f"{d['date'].min().date()} -> {d['date'].max().date()}{note}{flag}")
        frames.append(d.drop(columns=["split_f"]))
        time.sleep(0.4)

    if not frames:
        print("FATAL: nothing fetched")
        return 1

    cols = ["date", "ticker", "open", "high", "low", "close", "volume",
            "dividend", "ret_total", "mid_hl", "ret_mid"]
    panel = (pd.concat(frames, ignore_index=True)[cols]
             .sort_values(["ticker", "date"]).reset_index(drop=True))
    assert not panel.duplicated(["ticker", "date"]).any(), "dup ticker/date"
    panel.to_parquet(OUT_PARQUET, index=False)
    print(f"\nwrote {OUT_PARQUET}  shape={panel.shape}  "
          f"{panel.date.min().date()} -> {panel.date.max().date()}")

    # ---- coverage / tradability ----
    rows = []
    for t, g in panel.groupby("ticker", sort=False):
        g = g.sort_values("date")
        dv = (g["close"] * g["volume"])
        rows.append({
            "ticker": t,
            "group": TICKER_GROUP[t],
            "n_days": int(len(g)),
            "start_date": g["date"].min().date().isoformat(),
            "end_date": g["date"].max().date().isoformat(),
            "years": round(len(g) / 252.0, 2),
            "last_close": round(float(g["close"].iloc[-1]), 4),
            "median_dollar_volume_21d": round(float(dv.tail(21).median()), 2),
            "pct_days_with_volume": round(float((g["volume"] > 0).mean()), 4),
        })
    cov = (pd.DataFrame(rows)
           .sort_values("median_dollar_volume_21d", ascending=False)
           .reset_index(drop=True))
    cov.to_csv(OUT_COVERAGE, index=False)
    print(f"wrote {OUT_COVERAGE}  ({len(cov)} tickers)")

    if failed:
        print(f"\nFAILED ({len(failed)}): {[f'{t} [{g}]' for t, g in failed]}")
    else:
        print("\nFAILED (0): none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
