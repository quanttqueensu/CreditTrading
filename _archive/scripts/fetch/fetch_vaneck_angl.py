"""R3 forced-flow staging: VanEck ANGL daily NAV/AUM history.

VanEck publishes a 'Historical Prices' XLSX (Date, NAV, Last Trade, Volume,
Premium/Discount, AUM, Index Level) from fund inception. Shares outstanding are
NOT published directly; we derive shares_outstanding = AUM / NAV and flag it as
derived. The site requires a cookie handshake (first request 302s to a
disabled-cookies page; a second request with the cookie jar succeeds).

Stages:
  data/forced_flow/raw/ANGL_fundhistoprices.xlsx  (raw provenance copy)
  data/forced_flow/angl_nav_aum_daily.parquet

Run: /opt/anaconda3/bin/python3 scripts/forced_flow/fetch_vaneck_angl.py
"""
import http.cookiejar
import sys
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "forced_flow"
RAW_DIR = OUT_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

URL = ("https://www.vaneck.com/us/en/investments/"
       "angel-high-yield-bond-etf-angl/downloads/fundhistoprices/")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch_with_cookies(url: str) -> bytes:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", UA)]
    # first pass sets cookies (may land on the disabled-cookies interstitial)
    try:
        opener.open(url, timeout=120).read()
    except Exception:
        pass
    with opener.open(url, timeout=120) as r:
        blob = r.read()
        ctype = r.headers.get("Content-Type", "")
    if b"PK" != blob[:2]:
        raise RuntimeError(f"expected xlsx, got content-type={ctype}")
    return blob


def main() -> None:
    print("Fetching ANGL historical prices from VanEck ...")
    blob = fetch_with_cookies(URL)
    raw_path = RAW_DIR / "ANGL_fundhistoprices.xlsx"
    raw_path.write_bytes(blob)

    df = pd.read_excel(raw_path, header=1)
    df = df.rename(columns={
        "Date": "date", "NAV": "nav_per_share", "Last Trade": "last_trade",
        "Volume": "volume", "Premium/Discount": "premium_discount",
        "% Premium/Discount": "pct_premium_discount", "AUM": "aum",
        "Index Level": "index_level"})
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    for c in ["nav_per_share", "last_trade", "premium_discount",
              "pct_premium_discount", "aum", "index_level", "volume"]:
        df[c] = pd.to_numeric(
            df[c].astype(str).str.replace(",", ""), errors="coerce")
    # file contains stale weekend rows (repeated Friday NAV) -> drop Sat/Sun
    n_wkend = (df["date"].dt.dayofweek >= 5).sum()
    df = df[df["date"].dt.dayofweek < 5].copy()
    df["shares_outstanding_derived"] = df["aum"] / df["nav_per_share"]
    df["ticker"] = "ANGL"
    df = df.sort_values("date").reset_index(drop=True)

    dups = df["date"].duplicated().sum()
    assert dups == 0, f"ANGL: {dups} duplicate dates"
    bdays = pd.bdate_range(df["date"].min(), df["date"].max())
    missing = bdays.difference(pd.DatetimeIndex(df["date"]))
    print(f"  ANGL: N={len(df)}  {df['date'].min().date()} -> "
          f"{df['date'].max().date()}  dup_dates=0  dropped_weekend_rows={n_wkend}  "
          f"missing_bdays={len(missing)} (holidays incl.)")

    out_path = OUT_DIR / "angl_nav_aum_daily.parquet"
    cols = ["date", "ticker", "nav_per_share", "last_trade", "volume",
            "premium_discount", "pct_premium_discount", "aum", "index_level",
            "shares_outstanding_derived"]
    df[cols].to_parquet(out_path, index=False)
    print(f"Wrote {out_path}  rows={len(df)}")


if __name__ == "__main__":
    sys.exit(main())
