"""Refresh the feeds that were stale for no good reason (runbook Part II).

VIX/VIX3M/VVIX and Treasury futures come from yfinance. The futures are written
to a SEPARATE file and are NOT spliced onto the 1988-2026 history: that history
uses a different roll convention, and naively joining them would manufacture
returns at the join. Keep them as two series with a documented join.
"""
import sys
from pathlib import Path
import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "feeds"
OUT.mkdir(parents=True, exist_ok=True)

VOL = {"^VIX": "VIX", "^VIX3M": "VIX3M", "^VVIX": "VVIX"}
FUT = {"ZN=F": "ZN", "ZF=F": "ZF", "ZT=F": "ZT", "ZB=F": "ZB"}


def grab(tickers: dict, label: str, path: Path) -> None:
    frames = []
    for sym, name in tickers.items():
        try:
            d = yf.Ticker(sym).history(period="max", auto_adjust=False)
            if d.empty:
                print(f"  ERR {name:<6} empty"); continue
            d = d.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
            d.columns = ["date", "open", "high", "low", "close", "volume"]
            d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
            d["ticker"] = name
            frames.append(d)
            print(f"  OK  {name:<6} N={len(d):>6,}  "
                  f"{d.date.min().date()} -> {d.date.max().date()}")
        except Exception as e:
            print(f"  ERR {name:<6} {type(e).__name__}: {e}")
    if frames:
        out = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"])
        out.to_parquet(path, index=False)
        print(f"  wrote {path}  rows={len(out):,}")


def main() -> int:
    print("VIX complex:")
    grab(VOL, "vol", OUT / "vol_indices_daily.parquet")
    print("Treasury futures (yfinance continuous; SEPARATE from the 1988 history "
          "-- different roll convention, do not splice):")
    grab(FUT, "fut", OUT / "ust_futures_yf_daily.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
