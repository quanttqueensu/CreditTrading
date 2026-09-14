"""R3 forced-flow staging: iShares daily shares-outstanding history.

Downloads the fund-download XLS (SpreadsheetML) from the BlackRock product-data
API for HYG and LQD, parses the 'Historical' worksheet (As Of, NAV per Share,
Ex-Dividends, Shares Outstanding), and stages:
  data/forced_flow/ishares_so_daily.parquet   (long: date, ticker, nav_per_share, shares_outstanding)
  data/forced_flow/raw/<TICKER>_fund_download.xls   (raw provenance copy)

ANGL is VanEck, not iShares — handled separately / noted in manifest.
Run: /opt/anaconda3/bin/python3 scripts/forced_flow/fetch_ishares_so.py
"""
import io
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "forced_flow"
RAW_DIR = OUT_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

API = ("https://www.blackrock.com/varnish-api/blk-one01-product-data/"
       "product-data/api/v1/get-fund-document?appType=PRODUCT_PAGE"
       "&appSubType=ISHARES&targetSite=us-ishares&locale=en_US"
       "&portfolioId={pid}&component=fundDownload&userType=individual")

FUNDS = {"HYG": "239565", "LQD": "239566"}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def parse_historical(raw_text: str, ticker: str) -> pd.DataFrame:
    # iShares XLS export contains unescaped '&' in hyperlink attributes -> fix.
    raw_text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)",
                      "&amp;", raw_text)
    root = ET.fromstring(raw_text)
    ws = [w for w in root.findall("ss:Worksheet", NS)
          if w.get("{urn:schemas-microsoft-com:office:spreadsheet}Name") == "Historical"]
    if not ws:
        raise RuntimeError(f"{ticker}: no 'Historical' worksheet found")
    rows = ws[0].findall(".//ss:Row", NS)
    recs = []
    header = None
    for r in rows:
        cells = [(c.find("ss:Data", NS).text if c.find("ss:Data", NS) is not None else None)
                 for c in r.findall("ss:Cell", NS)]
        if header is None:
            header = cells
            continue
        recs.append(cells)
    df = pd.DataFrame(recs, columns=header)
    df = df.rename(columns={"As Of": "date", "NAV per Share": "nav_per_share",
                            "Ex-Dividends": "ex_dividend",
                            "Shares Outstanding": "shares_outstanding"})
    df["date"] = pd.to_datetime(df["date"], format="%b %d, %Y")
    df["nav_per_share"] = pd.to_numeric(df["nav_per_share"], errors="coerce")
    df["ex_dividend"] = pd.to_numeric(df["ex_dividend"].replace("--", None),
                                      errors="coerce")
    df["shares_outstanding"] = pd.to_numeric(df["shares_outstanding"],
                                             errors="coerce")
    df["ticker"] = ticker
    return df.sort_values("date").reset_index(drop=True)


def main() -> None:
    frames = []
    for ticker, pid in FUNDS.items():
        url = API.format(pid=pid)
        print(f"Fetching {ticker} (portfolioId {pid}) ...")
        blob = fetch(url)
        raw_path = RAW_DIR / f"{ticker}_fund_download.xls"
        raw_path.write_bytes(blob)
        df = parse_historical(blob.decode("utf-8"), ticker)
        # validation: duplicates and gaps
        dups = df["date"].duplicated().sum()
        assert dups == 0, f"{ticker}: {dups} duplicate dates"
        bdays = pd.bdate_range(df["date"].min(), df["date"].max())
        missing = bdays.difference(pd.DatetimeIndex(df["date"]))
        print(f"  {ticker}: N={len(df)}  {df['date'].min().date()} -> "
              f"{df['date'].max().date()}  dup_dates=0  "
              f"missing_bdays={len(missing)} (holidays incl.)")
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out = out[["date", "ticker", "nav_per_share", "ex_dividend",
               "shares_outstanding"]]
    out_path = OUT_DIR / "ishares_so_daily.parquet"
    out.to_parquet(out_path, index=False)
    print(f"Wrote {out_path}  rows={len(out)}")


if __name__ == "__main__":
    sys.exit(main())
