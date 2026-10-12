"""CEFConnect's dated NAV (and price) history for the C4 family CEFs: the second NAV source.

    python3 scripts/data/fetch_cef_families_cefconnect.py            # uses the raw cache where present
    python3 scripts/data/fetch_cef_families_cefconnect.py --refresh

Writes data/cef_families/cef_nav_cefconnect.parquet:

    date nav ticker close_cc discount_cc window

ENDPOINT. `GET https://www.cefconnect.com/api/v3/pricinghistory/{TICKER}/{WINDOW}`,
unauthenticated, rows `{"DataDate", "NAVData", "Data", "DiscountData"}`
(docs/REFERENCES.md §8, [V]). Measured on GAB, 2026-10-12, the windows are not
all daily:

    1Y   daily (246 rows, 2025-10-13 .. 2026-10-09; some sessions absent)
    3Y, 5Y, YTD, 3M, 1M   weekly, Fridays only
    All  weekly, Fridays only, from 1998-02-20 (or the fund's first NAV)
    6M, 2Y, 10Y, Max      no rows

So this fetcher takes `1Y` (the daily check) and `All` (the long weekly
check), keeps the window on every row, and never merges the two: a date in
both is two observations from two responses, and if they ever differ that is
itself a finding (`cef_families_quality.py` counts it).

WHY A SECOND SOURCE AND NOT A FILL. The standing NAV rule is "free channels
only; agreement to the cent, or the name is incomplete" (`docs/SYSTEM.md` §5,
2026-09-08). CEFConnect carries a dated row per observation, so staleness and
date alignment are checkable. It is used to CHECK the yfinance NAV panel, and
is never written into it: the panel has one source per row, as the live one
does (the live fetcher's CEFConnect fill is a logged, same-day exception for
trading, not a research convention).

Raw JSON per (ticker, window) is cached under raw/cefconnect/ with the fetch
time. A non-200 or a body without `Data.PriceHistory` raises for that name and
is recorded in the fetch log, never treated as "no history".

ZERO TRIALS. Data only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.data.cef_families_common import (  # noqa: E402
    NAV_CEFCONNECT, FamiliesDataError, assert_no_universe_names, cef_universe_names, included,
    load_universe, out_path, write_frame)

URL = "https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/{window}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}   # as scripts/cef/fetch_daily.py
WINDOWS = ("1Y", "All")
PAUSE_S = 0.3


def fetch(ticker: str, window: str, refresh: bool) -> dict:
    p = out_path(f"raw/cefconnect/{ticker}_{window}.json")
    if p.exists() and not refresh:
        return json.loads(p.read_text())
    import requests
    url = URL.format(ticker=ticker, window=window)
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise FamiliesDataError(f"GET {url} -> HTTP {r.status_code}")
    body = r.json()
    try:
        rows = body["Data"]["PriceHistory"]
    except (KeyError, TypeError) as e:
        raise FamiliesDataError(f"GET {url}: no Data.PriceHistory in the response") from e
    out = {"url": url, "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "rows": rows}
    p.write_text(json.dumps(out) + "\n")
    time.sleep(PAUSE_S)
    return out


def parse(payload: dict, ticker: str, window: str) -> tuple[pd.DataFrame, dict]:
    """Rows with a NAV; counts of rows without one. Nothing filled."""
    rows = payload["rows"] or []
    d = pd.DataFrame(rows, columns=["DataDate", "NAVData", "Data", "DiscountData"])
    log = {f"{window}_rows": len(d)}
    if d.empty:
        return pd.DataFrame(columns=["date", "nav", "ticker", "close_cc", "discount_cc", "window"]), log
    d["date"] = pd.to_datetime(d["DataDate"]).dt.normalize()
    bad = d["NAVData"].isna()
    log[f"{window}_rows_without_nav"] = int(bad.sum())
    d = d[~bad]
    dup = d.duplicated("date", keep=False)
    if dup.any():
        raise FamiliesDataError(f"CEFConnect {ticker} {window}: {int(dup.sum())} rows share a date")
    out = pd.DataFrame({"date": d["date"], "nav": d["NAVData"].astype(float), "ticker": ticker,
                        "close_cc": d["Data"].astype(float), "discount_cc": d["DiscountData"].astype(float),
                        "window": window})
    return out.sort_values("date").reset_index(drop=True), log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    u = included(load_universe())
    the44 = cef_universe_names()
    assert_no_universe_names(u["ticker"], the44)
    out, LOG = [], []
    for tk in u["ticker"]:
        log = {"ticker": tk}
        for w in WINDOWS:
            try:
                payload = fetch(tk, w, args.refresh)
            except Exception as e:                    # recorded per name, never swallowed
                log[f"{w}_error"] = f"{type(e).__name__}: {e}"
                continue
            d, lg = parse(payload, tk, w)
            log.update(lg)
            log[f"{w}_fetched_at_utc"] = payload["fetched_at_utc"]
            if len(d):
                log[f"{w}_first"], log[f"{w}_last"] = str(d.date.min().date()), str(d.date.max().date())
                out.append(d)
        LOG.append(log)
        print(f"  {tk:<6} 1Y {log.get('1Y_rows', 'ERR')!s:>4}  All {log.get('All_rows', 'ERR')!s:>5}  "
              f"{log.get('All_first', '')}")
    D = pd.concat(out, ignore_index=True)
    assert_no_universe_names(D["ticker"].unique(), the44)
    write_frame(D, NAV_CEFCONNECT)
    write_frame(pd.DataFrame(LOG), "cefconnect_fetch_log.csv")
    print(f"\nCEFConnect NAV rows {len(D):,} for {D.ticker.nunique()} names; last {D.date.max().date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
