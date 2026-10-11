"""Fetch the Pastor-Stambaugh liquidity factors from Lubos Pastor's data page --
the primary source.

    python3 scripts/data/fetch_pastor_liquidity.py            # fetch, parse, write the cache
    python3 scripts/data/fetch_pastor_liquidity.py --check-r2 # also compare with the R2 WRDS mirror

WHY THIS EXISTS
---------------
W4 attributes the deployed book's monthly P&L to the Pastor-Stambaugh TRADED
liquidity factor (LIQ_V, the value-weighted 10-1 portfolio on historical
liquidity betas). The file is linked from
https://faculty.chicagobooth.edu/lubos-pastor/data ; its name carries the last
year it covers (`liq_data_1962_2025.txt` when this was written), so the script
reads the data page and follows the link it finds rather than hard-coding a
year that goes stale every January. Exactly one matching link is required.

WHAT IS PARSED
--------------
Comment lines start with `%`. Data rows are `YYYYMM  level  innovation  traded`.
The traded factor is -99 before 1968 (Pastor's missing code); those rows keep
NaN in `liq_v` and are NEVER filled. Any other -99 raises. Values are decimals
as published (monthly returns / innovations), not percent.

`--check-r2` compares with `ff_all.liq_ps` on the R2 WRDS mirror (columns
ps_level, ps_innov, ps_vwf) and REPORTS differences; never averaged.

Output: `results/cef/w4/_cache_w4/ps_liquidity_monthly.parquet` (gitignored
cache): date (month-end), agg_liq, innov_liq, liq_v, fetched_at_utc,
source_url, header_through (Pastor's own "UPDATED THROUGH ..." line).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
PAGE = "https://faculty.chicagobooth.edu/lubos-pastor/data"
HOST = "https://faculty.chicagobooth.edu"
LINK_RE = re.compile(r'href="(/-/media/faculty/lubos-pastor/data/liq_data_(\d{4})_(\d{4})\.txt)"')


class LiquidityFetchError(RuntimeError):
    pass


def find_link(html: str) -> str:
    hits = sorted(set(m.group(1) for m in LINK_RE.finditer(html)))
    if len(hits) != 1:
        raise LiquidityFetchError(f"expected exactly one liq_data_YYYY_YYYY.txt link on "
                                  f"{PAGE}, found {hits}")
    return HOST + hits[0]


def parse(text: str) -> tuple[pd.DataFrame, str]:
    m = re.search(r"UPDATED THROUGH ([A-Z]{3} \d{4})", text)
    if not m:
        raise LiquidityFetchError("no 'UPDATED THROUGH <MON YYYY>' header line")
    through = m.group(1)
    rows = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("%"):
            continue
        parts = s.split()
        if len(parts) != 4 or not re.fullmatch(r"\d{6}", parts[0]):
            raise LiquidityFetchError(f"unparseable data row: {ln!r}")
        rows.append([parts[0]] + [float(x) for x in parts[1:]])
    df = pd.DataFrame(rows, columns=["key", "agg_liq", "innov_liq", "liq_v"])
    if (df[["agg_liq", "innov_liq"]] == -99).any().any():
        raise LiquidityFetchError("missing code -99 in the level/innovation columns")
    miss = df["liq_v"] == -99
    # The traded factor starts in 1968; -99 is legitimate only before it starts.
    first = df.loc[~miss, "key"].min()
    if (miss & (df["key"] > first)).any():
        raise LiquidityFetchError("liq_v is -99 after the traded factor has started")
    df["liq_v"] = df["liq_v"].where(~miss, np.nan)
    if df["key"].duplicated().any():
        raise LiquidityFetchError("duplicate months")
    df["date"] = pd.to_datetime(df.pop("key"), format="%Y%m") + pd.offsets.MonthEnd(0)
    return df.sort_values("date").reset_index(drop=True), through


def check_r2(df: pd.DataFrame) -> str:
    from src.data import r2
    cfg = r2.load_config()
    con = r2.connect(cfg)
    w = con.execute(f"SELECT * FROM read_parquet('{r2.r2_path('ff_all', 'liq_ps', cfg)}')").df()
    w["date"] = pd.to_datetime(w["date"]) + pd.offsets.MonthEnd(0)
    w["ps_vwf"] = w["ps_vwf"].where(w["ps_vwf"] != -99, np.nan)
    j = df.merge(w, on="date")
    out = [f"overlap {len(j)} months {j.date.min().date()}..{j.date.max().date()} "
           f"(mirror last {w.date.max().date()})"]
    for a, b in [("agg_liq", "ps_level"), ("innov_liq", "ps_innov"), ("liq_v", "ps_vwf")]:
        d = (j[a] - j[b]).abs()
        out.append(f"  {a:9s} vs {b:8s} max|diff| {d.max():.6f}  rows >1e-6 {(d > 1e-6).sum()}"
                   f"  (n both present {d.notna().sum()})")
    return "\n".join(out)


def main(argv=None) -> int:
    import requests
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check-r2", action="store_true")
    args = ap.parse_args(argv)
    r = requests.get(PAGE, timeout=60)
    if r.status_code != 200:
        raise LiquidityFetchError(f"GET {PAGE} -> HTTP {r.status_code}")
    url = find_link(r.text)
    f = requests.get(url, timeout=60)
    if f.status_code != 200:
        raise LiquidityFetchError(f"GET {url} -> HTTP {f.status_code}")
    df, through = parse(f.text)
    df["fetched_at_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    df["source_url"] = url
    df["header_through"] = through
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "ps_liquidity_monthly.parquet"
    df.to_parquet(path, index=False)
    print(f"{len(df)} months {df.date.min().date()}..{df.date.max().date()} "
          f"(header: updated through {through}); liq_v from "
          f"{df.loc[df.liq_v.notna(), 'date'].min().date()} -> {path.relative_to(REPO)}")
    print(f"source {url}")
    if args.check_r2:
        print(check_r2(df))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    raise SystemExit(main())
