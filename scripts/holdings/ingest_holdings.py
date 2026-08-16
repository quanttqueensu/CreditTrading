"""Daily ETF holdings ingester -> data/holdings/etf_holdings_daily.parquet

The ETF is not a ticker, it is a portfolio whose exact contents are published
every day for free. This pulls each fund's own holdings file and normalizes the
issuers' differing layouts to one schema, so that a fund's NAV can be rebuilt
from its own contents and so that the same CUSIP priced by two different issuers
on the same day can be compared (that disagreement is a staleness measurement).

Issuers
  iShares : /us/products/<pid>/<anything>/latest-holdings.csv  (the URL slug is
            ignored by the server; only <pid> matters).  Publishes a clean Price
            column directly, plus Duration / YTM / YTW / Sector.
  SSGA    : holdings-daily-us-en-<ticker>.xlsx.  No Price column -> clean price
            is derived as 100 * MarketValue / Par.  Identifier is ISIN for bonds
            and a LoanX "LX....." code for loans (loans therefore never join to
            CUSIP-keyed data such as TRACE).

Schema
  fund, asof_dt, cusip, isin, name, sector, weight_pct, par, market_value,
  price, coupon, maturity_dt, ytm, ytw, duration, issuer, price_src, ingest_ts

Idempotent: re-running for a date already present replaces that (fund, asof_dt)
block rather than duplicating it. Run daily after ~18:00 ET.
"""
from __future__ import annotations

import io
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data" / "holdings"
RAW_DIR = OUT_DIR / "raw"
OUT_PATH = OUT_DIR / "etf_holdings_daily.parquet"
RAW_DIR.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# ---- fund table -------------------------------------------------------------
# role: 'credit' = the hunt; 'ust' = negative control (Test 2); 'agg' = mixed.
# Every portfolioId below was verified by reading the fund name out of the
# returned file (see EXPECT_NAME). Two initial guesses were WRONG -- 271054 is
# the Low Carbon MSCI ACWI equity fund, not FALN, and 239453 is TLH, not SLQD --
# so the name assertion is load-bearing, not decoration. Do not add an id here
# without an EXPECT_NAME fragment for it.
ISHARES = {  # ticker: (portfolioId, role)
    "HYG":  ("239565", "credit"), "LQD":  ("239566", "credit"),
    "SHYG": ("258100", "credit"), "IGSB": ("239451", "credit"),
    "IGIB": ("239463", "credit"), "EMB":  ("239572", "credit"),
    "AGG":  ("239458", "agg"),
    "GOVT": ("239468", "ust"),    "SHY":  ("239452", "ust"),
    "IEI":  ("239455", "ust"),    "IEF":  ("239456", "ust"),
    "TLT":  ("239454", "ust"),    "TLH":  ("239453", "ust"),
}
EXPECT_NAME = {
    "HYG": "high yield corporate", "LQD": "investment grade corporate",
    "SHYG": "0-5 year high yield", "IGSB": "1-5 year investment grade",
    "IGIB": "5-10 year investment grade", "EMB": "emerging markets bond",
    "AGG": "core u.s. aggregate", "GOVT": "u.s. treasury bond",
    "SHY": "1-3 year treasury", "IEI": "3-7 year treasury",
    "IEF": "7-10 year treasury", "TLT": "20+ year treasury",
    "TLH": "10-20 year treasury",
}
SSGA = {"JNK": "credit", "SRLN": "credit"}

ISHARES_URL = "https://www.ishares.com/us/products/{pid}/x/latest-holdings.csv"
SSGA_URL = ("https://www.ssga.com/us/en/intermediary/library-content/products/"
            "fund-data/etfs/us/holdings-daily-us-en-{tk}.xlsx")

COLUMNS = ["fund", "asof_dt", "cusip", "isin", "name", "sector", "weight_pct",
           "par", "market_value", "price", "coupon", "maturity_dt", "ytm",
           "ytw", "duration", "issuer", "role", "price_src", "ingest_ts"]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def _num(s):
    """Parse '1,234.56' / '-' / '--' / '' -> float."""
    return pd.to_numeric(
        pd.Series(s, dtype="object").astype(str)
          .str.replace(",", "", regex=False).str.strip()
          .replace({"-": None, "--": None, "": None, "nan": None}),
        errors="coerce")


def _date(s, fmts=("%b %d, %Y", "%m/%d/%Y", "%d-%b-%Y")):
    out = pd.Series(pd.NaT, index=range(len(s)), dtype="datetime64[ns]")
    s = pd.Series(list(s), dtype="object").astype(str)
    for f in fmts:
        m = out.isna()
        if not m.any():
            break
        out[m] = pd.to_datetime(s[m.values], format=f, errors="coerce")
    return out


# ---- iShares ----------------------------------------------------------------
def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Column by name, or an all-NA Series of the right length if absent.

    Necessary because the issuers' layouts genuinely differ: AGG, for one,
    publishes no Price column at all. df.get() returns None for a missing
    column, which silently produces a length-1 Series and a shape error.
    """
    if name in df.columns:
        return df[name]
    return pd.Series([pd.NA] * len(df), index=df.index, dtype="object")


def parse_ishares(blob: bytes, tk: str, role: str) -> pd.DataFrame:
    text = blob.decode("utf-8-sig", "replace")
    lines = text.splitlines()
    fund_name = lines[0].strip().strip('"') if lines else ""
    frag = EXPECT_NAME.get(tk)
    if frag and frag not in fund_name.lower():
        raise RuntimeError(f"portfolioId points at the wrong fund: got "
                           f"{fund_name!r}, expected to contain {frag!r}")

    asof, hdr_i = None, None
    for i, ln in enumerate(lines[:40]):
        bare = ln.strip().strip('"')
        if bare.lower().startswith("fund holdings as of"):
            asof = pd.to_datetime(ln.split(",", 1)[1].strip().strip('"'),
                                  format="%b %d, %Y", errors="coerce")
        if ln.startswith("Name,") and "CUSIP" in ln:
            hdr_i = i
            break
    if hdr_i is None:
        raise RuntimeError("no holdings header row")
    if pd.isna(asof):
        raise RuntimeError("could not parse 'Fund Holdings as of' date")
    df = pd.read_csv(io.StringIO("\n".join(lines[hdr_i:])), thousands=",")
    df = df[df["Name"].notna()]

    par = _num(_col(df, "Par Value")).values
    mv = _num(_col(df, "Market Value")).values
    price = _num(_col(df, "Price")).values
    # iShares Market Value is dirty (par x (clean + accrued)/100). Where no
    # Price column is published, MV/par is therefore a DIRTY price and must be
    # labelled as such so it is never silently compared to a clean quote.
    if "Price" in df.columns:
        price_src = "published_clean"
    else:
        with np.errstate(divide="ignore", invalid="ignore"):
            price = 100.0 * mv / par
        price_src = "derived_dirty_mv_over_par"

    return pd.DataFrame({
        "fund": tk,
        "asof_dt": asof,
        "cusip": _col(df, "CUSIP").astype(str).str.strip(),
        "isin": _col(df, "ISIN").astype(str).str.strip(),
        "name": df["Name"].astype(str).str.strip(),
        "sector": _col(df, "Sector").astype(str).str.strip(),
        "weight_pct": _num(_col(df, "Weight (%)")).values,
        "par": par,
        "market_value": mv,
        "price": price,
        "coupon": _num(_col(df, "Coupon (%)")).values,
        "maturity_dt": _date(_col(df, "Maturity")).values,
        "ytm": _num(_col(df, "YTM (%)")).values,
        "ytw": _num(_col(df, "Yield to Worst (%)")).values,
        "duration": _num(_col(df, "Duration")).values,
        "issuer": "iShares",
        "role": role,
        "price_src": price_src,
    })


# ---- SSGA -------------------------------------------------------------------
def parse_ssga(blob: bytes, tk: str, role: str) -> pd.DataFrame:
    head = pd.read_excel(io.BytesIO(blob), header=None, nrows=12)
    asof, hdr_i = None, None
    for i, row in head.iterrows():
        cells = [str(x) for x in row.tolist() if str(x) != "nan"]
        joined = " ".join(cells)
        if "As of" in joined:
            asof = pd.to_datetime(joined.split("As of")[-1].strip(),
                                  format="%d-%b-%Y", errors="coerce")
        if "Name" in cells and any(c in cells for c in ("Identifier", "Weight")):
            hdr_i = i
            break
    if hdr_i is None:
        raise RuntimeError("no holdings header row")
    df = pd.read_excel(io.BytesIO(blob), header=hdr_i)
    df = df[df["Name"].notna()]
    df = df[~df["Name"].astype(str).str.strip().str.lower()
            .isin(["", "nan", "total", "cash"])]

    ident = df["Identifier"].astype(str).str.strip()
    is_isin = ident.str.match(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
    # US ISIN -> CUSIP is characters 3..11
    cusip = ident.where(is_isin & ident.str.startswith("US")).str[2:11]

    par = _num(_col(df, "Par Value")).values
    mv = _num(_col(df, "Market Value")).values
    # SSGA Market Value excludes accrued interest, so MV/par is a CLEAN price
    # directly comparable to the iShares published Price. Verified on bonds held
    # by both HYG and JNK; reconcile_issuers.py re-checks this every run.
    with np.errstate(divide="ignore", invalid="ignore"):
        price = 100.0 * mv / par
    price = pd.Series(price).replace([float("inf"), -float("inf")], pd.NA).values

    return pd.DataFrame({
        "fund": tk,
        "asof_dt": asof,
        "cusip": cusip.values,
        "isin": ident.where(is_isin).values,
        "name": df["Name"].astype(str).str.strip().values,
        "sector": pd.NA,
        "weight_pct": _num(_col(df, "Weight")).values,
        "par": par,
        "market_value": mv,
        "price": price,
        "coupon": _num(_col(df, "Coupon")).values,
        "maturity_dt": _date(_col(df, "Maturity")).values,
        "ytm": pd.NA, "ytw": pd.NA, "duration": pd.NA,
        "issuer": "SSGA",
        "role": role,
        "price_src": "derived_clean_mv_over_par",
    })


def main() -> int:
    ingest_ts = datetime.now(timezone.utc)
    stamp = ingest_ts.strftime("%Y%m%d")
    frames, failed = [], []

    jobs = ([(tk, "iShares", ISHARES_URL.format(pid=pid), role)
             for tk, (pid, role) in ISHARES.items()] +
            [(tk, "SSGA", SSGA_URL.format(tk=tk.lower()), role)
             for tk, role in SSGA.items()])

    for tk, issuer, url, role in jobs:
        try:
            blob = fetch(url)
            ext = "csv" if issuer == "iShares" else "xlsx"
            (RAW_DIR / f"{tk}_{stamp}.{ext}").write_bytes(blob)
            df = (parse_ishares(blob, tk, role) if issuer == "iShares"
                  else parse_ssga(blob, tk, role))
            df["ingest_ts"] = ingest_ts
            bonds = df.price.notna().sum()
            print(f"OK  {tk:<5s} {issuer:<8s} asof={str(df.asof_dt.iloc[0])[:10]} "
                  f"rows={len(df):>5,}  priced={bonds:>5,}  "
                  f"cusips={df.cusip.replace('-', pd.NA).nunique():>5,}")
            frames.append(df[COLUMNS])
        except Exception as e:
            print(f"ERR {tk:<5s} {issuer:<8s} {type(e).__name__}: {e}")
            failed.append(tk)
        time.sleep(0.8)

    if not frames:
        print("no funds ingested")
        return 1
    new = pd.concat(frames, ignore_index=True)

    if OUT_PATH.exists():
        old = pd.read_parquet(OUT_PATH)
        key = set(zip(new.fund, new.asof_dt))
        keep = ~pd.Series(list(zip(old.fund, old.asof_dt))).isin(key)
        new = pd.concat([old[keep.values], new], ignore_index=True)
    new = new.sort_values(["asof_dt", "fund", "cusip"]).reset_index(drop=True)
    new.to_parquet(OUT_PATH, index=False)

    print(f"\nwrote {OUT_PATH}")
    print(f"  rows={len(new):,}  funds={new.fund.nunique()}  "
          f"dates={new.asof_dt.nunique()}  failed={failed or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
