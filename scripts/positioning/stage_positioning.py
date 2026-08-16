"""Stage credit-ETF POSITIONING data (short interest + short volume).

A signal family untested in this repo. Two REAL, free, no-auth sources:

1. FINRA Consolidated Short Interest  (bi-monthly, per ticker)
   POST https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest
   Public Query API, no registration/key required. Gives shares short,
   prior-period shares short, average daily volume and days-to-cover per
   settlement date. HYG is the market's primary credit hedging vehicle, so its
   short interest is a direct read on institutional hedging demand.
   -> data/positioning/short_interest_finra.parquet

2. FINRA Reg SHO Daily Short Sale Volume, consolidated NMS ("CNMS")
   https://cdn.finra.org/equity/regsho/daily/CNMSshvol<YYYYMMDD>.txt
   Daily per-ticker short volume / total volume. Much denser than (1) and
   available from 2018-08-01. Pre-2018 only per-venue OFF-exchange files
   (FNSQ/FNYX/FNRA) exist, which are NOT definitionally comparable to CNMS,
   so they are deliberately not spliced on.
   -> data/positioning/short_volume_daily_finra.parquet

NOTE on normalisation: neither source carries ETF shares outstanding, and no
shares-outstanding history exists in this repo (data/etf_daily.parquet has
price/volume only). ETF share counts swing with creation/redemption, so RAW
shares-short is not comparable across time. Use the self-normalising measures:
days-to-cover (shares short / ADV) from (1) and short-volume share
(short / total volume) from (2).

Usage:  /opt/anaconda3/bin/python3 scripts/positioning/stage_positioning.py
"""

from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "data" / "positioning"

TICKERS = [
    # credit
    "HYG", "JNK", "LQD", "USHY", "SHYG", "EMB", "ANGL", "BKLN", "PFF", "MBB",
    # duration / negative controls
    "TLT", "IEF", "SHY",
]

SI_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
SHVOL_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d}.txt"
CNMS_START = "2018-08-01"           # earliest CNMS file that exists
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
      "Content-Type": "application/json"}


# ---------------------------------------------------------------- short interest
def fetch_short_interest() -> pd.DataFrame:
    """Page the FINRA Query API for every target ticker's full SI history."""
    rows: list[dict] = []
    offset = 0
    while True:
        body = {
            "limit": 5000,
            "offset": offset,
            "domainFilters": [{"fieldName": "symbolCode", "values": TICKERS}],
            "dateRangeFilters": [{"fieldName": "settlementDate",
                                  "startDate": "1990-01-01",
                                  "endDate": "2026-12-31"}],
        }
        r = requests.post(SI_URL, headers=UA, data=json.dumps(body), timeout=120)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        print(f"  short interest: fetched {len(batch)} (total {offset})")
        if len(batch) < 5000:
            break

    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "symbolCode": "ticker",
        "settlementDate": "settlement_date",
        "currentShortPositionQuantity": "shares_short",
        "previousShortPositionQuantity": "shares_short_prev",
        "averageDailyVolumeQuantity": "adv_shares",
        "daysToCoverQuantity": "days_to_cover",
        "changePercent": "change_pct",
        "changePreviousNumber": "change_shares",
        "issueName": "issue_name",
        "marketClassCode": "market_class",
        "stockSplitFlag": "split_flag",
        "revisionFlag": "revision_flag",
    })
    df["settlement_date"] = pd.to_datetime(df["settlement_date"])
    for c in ["shares_short", "shares_short_prev", "adv_shares",
              "days_to_cover", "change_pct", "change_shares"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # FINRA FLOORS the published days_to_cover at 1.0 (~24% of rows sit exactly
    # at 1.0 with a true ratio well below it), which destroys the low end of the
    # crowding distribution. Keep the raw, unfloored ratio alongside it.
    df["days_to_cover_raw"] = df["shares_short"] / df["adv_shares"]

    df = (df[["settlement_date", "ticker", "shares_short", "shares_short_prev",
              "change_shares", "change_pct", "adv_shares", "days_to_cover",
              "days_to_cover_raw",
              "issue_name", "market_class", "split_flag", "revision_flag"]]
          .sort_values(["ticker", "settlement_date"])
          .drop_duplicates(["ticker", "settlement_date"], keep="last")
          .reset_index(drop=True))
    return df


# ------------------------------------------------------------- daily short volume
def _fetch_one_shvol(day: str) -> pd.DataFrame | None:
    """One CNMS daily file, filtered to target tickers. 403 => non-trading day."""
    try:
        r = requests.get(SHVOL_URL.format(d=day),
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    except Exception:
        return None
    if r.status_code != 200 or not r.text.startswith("Date|"):
        return None
    df = pd.read_csv(io.StringIO(r.text), sep="|")
    df = df[df["Symbol"].isin(TICKERS)]
    return df if len(df) else None


def fetch_short_volume() -> pd.DataFrame:
    days = pd.bdate_range(CNMS_START, pd.Timestamp.today()).strftime("%Y%m%d").tolist()
    print(f"  short volume: probing {len(days)} business days from {CNMS_START}")
    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(16) as ex:
        for i, out in enumerate(ex.map(_fetch_one_shvol, days)):
            if out is not None:
                frames.append(out)
            if (i + 1) % 500 == 0:
                print(f"    {i + 1}/{len(days)} days probed, {len(frames)} with data")

    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={
        "Date": "date", "Symbol": "ticker", "ShortVolume": "short_volume",
        "ShortExemptVolume": "short_exempt_volume", "TotalVolume": "total_volume",
        "Market": "market",
    })
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    for c in ["short_volume", "short_exempt_volume", "total_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # self-normalising crowding measure: fraction of tape printed short
    df["short_volume_pct"] = df["short_volume"] / df["total_volume"]
    return (df[["date", "ticker", "short_volume", "short_exempt_volume",
                "total_volume", "short_volume_pct", "market"]]
            .sort_values(["ticker", "date"])
            .drop_duplicates(["ticker", "date"], keep="last")
            .reset_index(drop=True))


def _report(df: pd.DataFrame, datecol: str, path: Path) -> None:
    print(f"\n=== VERIFY {path}")
    back = pd.read_parquet(path)
    print(f"  shape={back.shape}  {datecol}: {back[datecol].min().date()} -> "
          f"{back[datecol].max().date()}")
    print(back.head(3).to_string())
    print("  obs per ticker:")
    print(back.groupby("ticker").size().to_string())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/2] FINRA consolidated short interest (bi-monthly)")
    si = fetch_short_interest()
    si_path = OUT_DIR / "short_interest_finra.parquet"
    si.to_parquet(si_path, index=False)
    _report(si, "settlement_date", si_path)

    print("\n[2/2] FINRA Reg SHO daily short volume (CNMS)")
    sv = fetch_short_volume()
    sv_path = OUT_DIR / "short_volume_daily_finra.parquet"
    sv.to_parquet(sv_path, index=False)
    _report(sv, "date", sv_path)


if __name__ == "__main__":
    main()
