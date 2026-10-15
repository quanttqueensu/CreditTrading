"""CEFConnect's dated closing PRICE for the 13 spec names: the second source for
trial C5's holdout bad-close check in 2025-26. Read-only, unauthenticated.

    python3 scripts/data/fetch_cefconnect_closes.py      # refuses until C5's fit verdict is committed

WHY. The team lead's ruling of 2026-10-14 on C5's holdout: a panel close is
replaced only when two independent sources agree that it is wrong. For 2023-24
those are CRSP `prc` and the NYSE closing print. R2's CRSP ends 2024-12-31, so
for 2025-26 the second source is CEFConnect's close. One source alone never
replaces anything.

ENDPOINT. `GET https://www.cefconnect.com/api/v3/pricinghistory/{TICKER}/{WINDOW}`
(docs/REFERENCES.md §8 and §12g, [V]). Only `1Y` is daily. `All` is weekly
(Fridays) from the fund's first NAV, and CEFConnect's long history is
restated for some reverse splits, so it is a check, not a raw record (§12g).
Both windows are kept and labelled per row, never merged: a date in both is
two observations, and the trial treats a date on which they disagree as having
no usable CEFConnect close.

WHERE. `results/cef/c5/_cache_cefconnect/` (gitignored: vendor data, public
repository): the raw JSON per (ticker, window) with its fetch time, and
`cefconnect_closes.parquet` (date, ticker, close_cc, nav_cc, window). Unlike
the C4 family fetcher's parse, a row with a price and no NAV is KEPT: this is a
price check.

GATE. 2025-26 closes are holdout-period prices, so this refuses until
`results/cef/c5/C5_FIT_VERDICT.json` is committed (the auction fetcher's
`fit_verdict_committed`).

NO SILENT FALLBACK. A non-200, or a body without `Data.PriceHistory`, raises for
that name. Two rows on one date in one window raise.
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

URL = "https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/{window}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}   # as scripts/cef/fetch_daily.py
WINDOWS = ("1Y", "All")
CACHE = REPO / "results" / "cef" / "c5" / "_cache_cefconnect"
OUT = CACHE / "cefconnect_closes.parquet"
PAUSE_S = 0.3


class CloseFetchError(RuntimeError):
    pass


def parse(payload: dict, ticker: str, window: str) -> pd.DataFrame:
    """Every row with a price, labelled with its window. Nothing filled."""
    d = pd.DataFrame(payload["rows"] or [], columns=["DataDate", "NAVData", "Data", "DiscountData"])
    d = d[d["Data"].notna()].copy()
    d["date"] = pd.to_datetime(d["DataDate"]).dt.normalize()
    dup = d.duplicated("date", keep=False)
    if dup.any():
        raise CloseFetchError(f"CEFConnect {ticker} {window}: {int(dup.sum())} rows share a date")
    return pd.DataFrame({"date": d["date"], "ticker": ticker, "close_cc": d["Data"].astype(float),
                         "nav_cc": pd.to_numeric(d["NAVData"], errors="raise").astype(float),
                         "window": window}).sort_values("date").reset_index(drop=True)


def fetch(ticker: str, window: str) -> dict:
    import requests
    url = URL.format(ticker=ticker, window=window)
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise CloseFetchError(f"GET {url} -> HTTP {r.status_code}")
    body = r.json()
    try:
        rows = body["Data"]["PriceHistory"]
    except (KeyError, TypeError) as e:
        raise CloseFetchError(f"GET {url}: no Data.PriceHistory in the response") from e
    out = {"url": url, "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "rows": rows}
    (CACHE / "raw").mkdir(parents=True, exist_ok=True)
    (CACHE / "raw" / f"{ticker}_{window}.json").write_text(json.dumps(out) + "\n")
    time.sleep(PAUSE_S)
    return out


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n")[0]).parse_args(argv)
    from scripts.data.fetch_alpaca_auction_history import fit_verdict_committed
    ok, why = fit_verdict_committed()
    if not ok:
        raise CloseFetchError(f"refused: C5's fit verdict is not committed ({why})")
    from scripts.cef.spec import UNIVERSE
    frames = []
    for tk in sorted(UNIVERSE):
        for w in WINDOWS:
            d = parse(fetch(tk, w), tk, w)
            print(f"  {tk:<5} {w:<4} {len(d):>5} price rows, {d.date.min().date() if len(d) else '-'}.."
                  f"{d.date.max().date() if len(d) else '-'}")
            frames.append(d)
    D = pd.concat(frames, ignore_index=True)
    D.to_parquet(OUT, index=False)
    print(f"{len(D):,} rows, {D.ticker.nunique()} names -> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
