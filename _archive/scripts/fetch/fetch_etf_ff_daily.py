"""R3 forced-flow staging: yfinance daily adjusted closes for the FF universe.

Tickers: HYG JNK LQD ANGL FALN BKLN SRLN JBBB JAAA BIL VWEHX IGSB SLQD
Full available history per ticker (period='max', auto_adjust=True -> Close is
the adjusted close). Long format so short-history funds don't NaN-pad others.

Stages: data/forced_flow/etf_ff_daily.parquet
  columns: date, ticker, adj_close, volume

Run: /opt/anaconda3/bin/python3 scripts/forced_flow/fetch_etf_ff_daily.py
"""
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "forced_flow"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TICKERS = ["HYG", "JNK", "LQD", "ANGL", "FALN", "BKLN", "SRLN", "JBBB",
           "JAAA", "BIL", "VWEHX", "IGSB", "SLQD"]


def main() -> None:
    frames = []
    failed = []
    for t in TICKERS:
        try:
            h = yf.Ticker(t).history(period="max", auto_adjust=True)
        except Exception as e:
            print(f"  {t}: FETCH FAILED ({e})")
            failed.append(t)
            continue
        if h is None or h.empty:
            print(f"  {t}: FETCH FAILED (empty)")
            failed.append(t)
            continue
        df = h.reset_index()[["Date", "Close", "Volume"]].rename(
            columns={"Date": "date", "Close": "adj_close", "Volume": "volume"})
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        df["ticker"] = t
        df = df.dropna(subset=["adj_close"]).sort_values("date")
        dups = df["date"].duplicated().sum()
        assert dups == 0, f"{t}: {dups} duplicate dates"
        bdays = pd.bdate_range(df["date"].min(), df["date"].max())
        missing = bdays.difference(pd.DatetimeIndex(df["date"]))
        print(f"  {t}: N={len(df)}  {df['date'].min().date()} -> "
              f"{df['date'].max().date()}  dup_dates=0  "
              f"missing_bdays={len(missing)} (holidays incl.)")
        frames.append(df[["date", "ticker", "adj_close", "volume"]])
    if failed:
        print(f"FAILED tickers: {failed}")
    out = pd.concat(frames, ignore_index=True)
    out_path = OUT_DIR / "etf_ff_daily.parquet"
    out.to_parquet(out_path, index=False)
    print(f"Wrote {out_path}  rows={len(out)}  tickers={out['ticker'].nunique()}")


if __name__ == "__main__":
    sys.exit(main())
