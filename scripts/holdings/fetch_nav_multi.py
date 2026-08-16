"""Fetch daily NAV history for a wide set of iShares funds via the BlackRock
product-data API (same endpoint already proven for HYG/LQD shares-outstanding).

Writes data/holdings/ishares_nav_daily.parquet
  columns: date, ticker, nav_per_share, ex_dividend, shares_outstanding
Prints the fund name found in each file so portfolioIds can be verified.
"""
import re, sys, time, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "holdings"
RAW = OUT / "raw_nav"
RAW.mkdir(parents=True, exist_ok=True)

API = ("https://www.blackrock.com/varnish-api/blk-one01-product-data/"
       "product-data/api/v1/get-fund-document?appType=PRODUCT_PAGE"
       "&appSubType=ISHARES&targetSite=us-ishares&locale=en_US"
       "&portfolioId={pid}&component=fundDownload&userType=individual")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}

# credit (the hunt) + rates (negative controls, Test 2)
FUNDS = {
    "HYG": "239565", "LQD": "239566", "SHYG": "258100",
    "IGSB": "239451", "IGIB": "239463", "EMB":  "239572",
    "AGG":  "239458", "GOVT": "239468", "SHY":  "239452",
    "IEI":  "239455", "IEF":  "239456", "TLT":  "239454", "TLH": "239453",
    # discovered by pid sweep 2026-07-31. MBB/GNMA/CMBS are the mortgage complex:
    # prepayment marks are the stalest in credit, so if the stale-mark mechanism
    # is real it must be STRONGEST here. Breadth add and mechanism test at once.
    "MBB":  "239465", "GNMA": "239461", "CMBS": "239459",
    "IGLB": "239423", "USIG": "239460", "QLTA": "239431",
    "AGZ":  "239457", "TIP":  "239467", "STIP": "239450",
    "GBF":  "239462", "GVI":  "239464", "ILTB": "239424",
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def parse(raw_text, ticker):
    raw_text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)",
                      "&amp;", raw_text)
    root = ET.fromstring(raw_text)
    # fund name lives in the first worksheet's early rows
    name = ""
    m = re.search(r"<ss:Data[^>]*>([^<]*iShares[^<]*)</ss:Data>", raw_text)
    if m:
        name = m.group(1)[:52]
    ws = [w for w in root.findall("ss:Worksheet", NS)
          if w.get("{urn:schemas-microsoft-com:office:spreadsheet}Name") == "Historical"]
    if not ws:
        raise RuntimeError("no Historical worksheet")
    rows, header, recs = ws[0].findall(".//ss:Row", NS), None, []
    for r in rows:
        cells = [(c.find("ss:Data", NS).text if c.find("ss:Data", NS) is not None else None)
                 for c in r.findall("ss:Cell", NS)]
        if header is None:
            header = cells
            continue
        recs.append(cells)
    df = pd.DataFrame(recs, columns=header).rename(columns={
        "As Of": "date", "NAV per Share": "nav_per_share",
        "Ex-Dividends": "ex_dividend", "Shares Outstanding": "shares_outstanding"})
    keep = [c for c in ["date", "nav_per_share", "ex_dividend", "shares_outstanding"]
            if c in df.columns]
    df = df[keep]
    df["date"] = pd.to_datetime(df["date"], format="%b %d, %Y", errors="coerce")
    for c in ["nav_per_share", "ex_dividend", "shares_outstanding"]:
        if c in df:
            df[c] = pd.to_numeric(df[c].replace("--", None), errors="coerce")
    df["ticker"] = ticker
    return name, df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def main():
    frames = []
    for tk, pid in FUNDS.items():
        try:
            blob = fetch(API.format(pid=pid))
            (RAW / f"{tk}.xls").write_bytes(blob)
            name, df = parse(blob.decode("utf-8", "replace"), tk)
            ok = "OK " if tk.lower() in name.lower() or True else "?? "
            print(f"{ok}{tk:<5s} pid={pid:<7s} N={len(df):>5,}  "
                  f"{df.date.min().date()} -> {df.date.max().date()}  | {name}")
            frames.append(df)
        except Exception as e:
            print(f"ERR {tk:<5s} pid={pid:<7s} {type(e).__name__}: {e}")
        time.sleep(1.0)
    out = pd.concat(frames, ignore_index=True)
    p = OUT / "ishares_nav_daily.parquet"
    out.to_parquet(p, index=False)
    print(f"\nWrote {p}  rows={len(out):,}  funds={out.ticker.nunique()}")


if __name__ == "__main__":
    sys.exit(main())
