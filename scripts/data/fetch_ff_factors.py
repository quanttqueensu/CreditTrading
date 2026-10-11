"""Fetch the Fama-French five factors (2x3) and the momentum factor, daily and
monthly, from Kenneth French's data library -- the primary source.

    python3 scripts/data/fetch_ff_factors.py            # fetch, parse, write the cache
    python3 scripts/data/fetch_ff_factors.py --check-r2 # also compare with the R2 WRDS mirror

WHY THIS EXISTS
---------------
W4 (results/cef/RESEARCH_PLAN_2026-10-09.md item 0.6) attributes the deployed
book's P&L to FF5 + momentum. CLAUDE.md: "never hand-copy a data series --
anything fetched gets a fetcher and a source note in docs/REFERENCES.md". The
R2 WRDS mirror also carries `ff_all.fivefactors_daily` (to 2026-04-30 when
catalogued, results/data/R2_CATALOG.md), but that is a vintage frozen on WRDS's
schedule; French's own files are the primary source and are fetched here.
`--check-r2` compares the two on their overlap and REPORTS any difference. It
never averages them and never substitutes one for the other (data rules).

WHERE IT WRITES
---------------
`results/cef/w4/_cache_w4/ff5_umd_{daily,monthly}.parquet` -- a gitignored
cache (`.gitignore`: `results/**/_cache_*`). Fetched data is not committed:
the repository is public, and the series is re-fetchable by this script.
Columns: date, mktrf, smb, hml, rmw, cma, rf, umd -- DECIMALS (French's files
are in percent; divided by 100 here, once, and nowhere else), plus
`fetched_at_utc` and `crsp_vintage` (French's header line "created using the
YYYYMM CRSP database", parsed, because the library is revised in place and a
regression run on two vintages is two different regressions).

PARSING RULES (no silent fallbacks)
-----------------------------------
* A data row is `<YYYYMMDD or YYYYMM>, v1, v2, ...`. French's monthly files
  append an annual block (`  2024,  19.78, ...`) after a blank line; a 4-digit
  key is that block and is skipped by rule, not by position.
* The header row is read and must name exactly the expected columns, in order.
  A renamed or re-ordered column raises rather than shifting values silently.
* French codes a missing value as -99.99 / -999; any such value raises.
* Daily momentum and daily FF5 must cover the same dates over their overlap;
  a date in one and not the other raises, naming the dates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FILES = {
    "ff5_daily": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "ff5_monthly": "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "mom_daily": "F-F_Momentum_Factor_daily_CSV.zip",
    "mom_monthly": "F-F_Momentum_Factor_CSV.zip",
}
FF5_COLS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
MOM_COLS = ["Mom"]          # French spells it "Mom" (monthly) / "Mom" or "MOM" (daily)


class FactorFetchError(RuntimeError):
    pass


def _download(name: str) -> bytes:
    import requests
    url = BASE + FILES[name]
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        raise FactorFetchError(f"GET {url} -> HTTP {r.status_code}")
    return r.content


def _csv_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise FactorFetchError(f"expected one CSV in the zip, found {names}")
        return z.read(names[0]).decode("latin-1")


def crsp_vintage(text: str) -> str:
    """French's first line names the CRSP vintage the file was built from."""
    m = re.search(r"created (?:by )?using the (\d{6}) CRSP database", text)
    if not m:
        raise FactorFetchError("could not find the 'created using the YYYYMM CRSP "
                               "database' header line; the file format has changed")
    return m.group(1)


def parse_french_csv(text: str, expected: list[str], key_len: int) -> pd.DataFrame:
    """Rows whose first field is a `key_len`-digit date key; header checked.

    `key_len` is 8 for daily (YYYYMMDD) and 6 for monthly (YYYYMM). Values are
    returned in PERCENT, exactly as published; the caller converts once.
    """
    lines = text.splitlines()
    header_idx = None
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.split(",")]
        if len(cells) >= 2 and cells[0] == "" and cells[1:] and all(cells[1:]):
            header_idx = i
            header = cells[1:]
            break
    if header_idx is None:
        raise FactorFetchError("no header row (a row starting with a comma) found")
    norm = [h.upper() for h in header]
    if norm != [e.upper() for e in expected]:
        raise FactorFetchError(f"header {header} != expected {expected}")
    rows = []
    pat = re.compile(r"^\s*(\d+)\s*,")
    for ln in lines[header_idx + 1:]:
        m = pat.match(ln)
        if not m:
            continue
        key = m.group(1)
        if len(key) != key_len:
            continue                    # annual block (4 digits) or other section
        vals = [float(c) for c in ln.split(",")[1:]]
        if len(vals) != len(expected):
            raise FactorFetchError(f"row {key}: {len(vals)} values, expected {len(expected)}")
        rows.append([key] + vals)
    if not rows:
        raise FactorFetchError("no data rows parsed")
    df = pd.DataFrame(rows, columns=["key"] + expected)
    bad = df[expected].isin([-99.99, -999.0, -99.0]).any(axis=1)
    if bad.any():
        raise FactorFetchError(f"missing-value codes in rows {df.loc[bad, 'key'].tolist()[:10]}")
    if df["key"].duplicated().any():
        raise FactorFetchError(f"duplicate keys {df.loc[df.key.duplicated(), 'key'].tolist()[:10]}")
    fmt = "%Y%m%d" if key_len == 8 else "%Y%m"
    df["date"] = pd.to_datetime(df.pop("key"), format=fmt)
    if key_len == 6:
        df["date"] = df["date"] + pd.offsets.MonthEnd(0)   # month-end stamp
    return df.sort_values("date").reset_index(drop=True)


def build(freq: str) -> pd.DataFrame:
    key_len = 8 if freq == "daily" else 6
    t5 = _csv_text(_download(f"ff5_{freq}"))
    tm = _csv_text(_download(f"mom_{freq}"))
    v5, vm = crsp_vintage(t5), crsp_vintage(tm)
    f5 = parse_french_csv(t5, FF5_COLS, key_len)
    fm = parse_french_csv(tm, MOM_COLS, key_len)
    lo, hi = max(f5.date.min(), fm.date.min()), min(f5.date.max(), fm.date.max())
    a = set(f5.date[(f5.date >= lo) & (f5.date <= hi)])
    b = set(fm.date[(fm.date >= lo) & (fm.date <= hi)])
    if a != b:
        raise FactorFetchError(
            f"{freq}: FF5 and momentum disagree on dates inside their overlap: "
            f"only FF5 {sorted(a - b)[:5]}, only MOM {sorted(b - a)[:5]}")
    df = f5.merge(fm, on="date", how="inner")
    df = df.rename(columns={"Mkt-RF": "mktrf", "SMB": "smb", "HML": "hml", "RMW": "rmw",
                            "CMA": "cma", "RF": "rf", "Mom": "umd"})
    for c in ["mktrf", "smb", "hml", "rmw", "cma", "rf", "umd"]:
        df[c] = df[c] / 100.0           # percent -> decimal, the ONE conversion
    df["fetched_at_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if v5 != vm:
        raise FactorFetchError(f"{freq}: FF5 vintage {v5} != momentum vintage {vm}")
    df["crsp_vintage"] = v5
    return df


def check_r2(df: pd.DataFrame, freq: str) -> str:
    """Compare with the R2 WRDS mirror on the overlap. Report only."""
    from src.data import r2
    cfg = r2.load_config()
    con = r2.connect(cfg)
    table = "fivefactors_daily" if freq == "daily" else "fivefactors_monthly"
    w = con.execute(f"SELECT * FROM read_parquet('{r2.r2_path('ff_all', table, cfg)}')").df()
    w["date"] = pd.to_datetime(w["date"])
    if freq == "monthly":
        w["date"] = w["date"] + pd.offsets.MonthEnd(0)
    j = df.merge(w, on="date", suffixes=("_kf", "_wrds"))
    out = [f"{freq}: overlap {len(j)} rows {j.date.min().date()}..{j.date.max().date()} "
           f"(French vintage {df.crsp_vintage.iloc[0]}; mirror last {w.date.max().date()})"]
    for c in ["mktrf", "smb", "hml", "rmw", "cma", "rf", "umd"]:
        d = (j[f"{c}_kf"] - j[f"{c}_wrds"].astype(float)).abs()
        out.append(f"  {c:6s} max|diff| {d.max() * 1e4:8.2f}bp  mean {d.mean() * 1e4:6.3f}bp  "
                   f"rows >0.5bp {(d > 0.5e-4).sum()}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check-r2", action="store_true")
    args = ap.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    for freq in ("daily", "monthly"):
        df = build(freq)
        path = CACHE / f"ff5_umd_{freq}.parquet"
        df.to_parquet(path, index=False)
        print(f"{freq}: {len(df)} rows {df.date.min().date()}..{df.date.max().date()} "
              f"vintage {df.crsp_vintage.iloc[0]} -> {path.relative_to(REPO)}")
        if args.check_r2:
            sys.path.insert(0, str(REPO))
            print(check_r2(df, freq))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
