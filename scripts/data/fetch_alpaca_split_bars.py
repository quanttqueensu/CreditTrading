"""Read-only Alpaca daily bars, SPLIT-ADJUSTED and raw, for a few named symbols.

    export QUANTT_ENV_FILE=<absolute path to the env file>   # cef paper key; never printed
    python3 scripts/data/fetch_alpaca_split_bars.py --c4-pool --start 2024-12-02 --end 2026-09-30
    python3 scripts/data/fetch_alpaca_split_bars.py IGR --start 2026-08-17 --end 2026-09-30

WHY THIS EXISTS (2026-10-14, trial C4)
--------------------------------------
yfinance serves no close for IGR on 2026-09-08, the ex-date of its 1:3
reverse split, so IGR has no return on 09-08 or 09-09 in C4's declared
holdout source (`results/cef/C4_RESULT_2026-10-14.md`). The team lead
ruled on 2026-10-14 (amendment block in
`results/cef/PREREG_C4_FAMILIES_2026-10-13.md`) that those two days are filled
from **Alpaca's split-adjusted daily bars**, a fetched second source, and that
Alpaca's adjacent bars are cross-checked against the panel.

WHAT IT FETCHES
---------------
* `GET https://data.alpaca.markets/v2/stocks/bars`, `timeframe=1Day`,
  `feed=sip`, once with `adjustment=split` (the fill) and once with
  `adjustment=raw` (to see the print on each side of the split as it traded),
  through `scripts/rv/alpaca_daily.py`'s pager and bar parser, which refuse a
  bar not stamped at New York midnight, a duplicate, or a non-positive price.
* `GET https://data.alpaca.markets/v1/corporate-actions` for the window: the
  split ratio and any cash dividend, REPORTED (this module does not raise on a
  split; finding one is the point).
* `GET /v2/calendar` (paper API): the sessions in the window, so a session with
  no bar is named, never skipped.

`--c4-pool` fetches the same for all 105 C4 pool funds
(`scripts/cef/c4_feasibility.declare_pool`) over the yfinance leg of C4's returns
(2025-01-02 onward), so `scripts/cef/c4_families.py stage0` can cross-check
that leg's closes and distributions against a second source. The comparison
is reported, never averaged.

Everything is written to the gitignored `results/cef/c4/_cache_c4/` with the
fetch time. Nothing is filled, interpolated or averaged here: a missing bar is
a missing bar, and the C4 script halts the holdout on it (the ruling).

READ-ONLY. `AlpacaClient._get` issues GET only. No order endpoint is named in
this file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CACHE = REPO / "results" / "cef" / "c4" / "_cache_c4"


def bars(client, symbols, start: dt.date, end: dt.date, adjustment: str) -> pd.DataFrame:
    from scripts.rv.alpaca_daily import (BARS_LIMIT, DATA_BASE, FEED, AlpacaLegError, _ny, _paged,  # noqa: F401
                                         parse_bars)
    if adjustment not in ("raw", "split"):
        raise ValueError(f"adjustment {adjustment!r}: only raw and split are used here")
    symbols = sorted(set(symbols))
    rows = []
    for i in range(0, len(symbols), 20):
        chunk = symbols[i:i + 20]
        params = {"symbols": ",".join(chunk), "timeframe": "1Day", "feed": FEED,
                  "adjustment": adjustment, "start": _ny(start, 0), "end": _ny(end, 20),
                  "limit": BARS_LIMIT, "sort": "asc"}
        for page in _paged(client, "/v2/stocks/bars", params, "bars"):
            rows.extend(parse_bars(page, set(chunk)))
    df = pd.DataFrame(rows)
    if df.empty:
        raise AlpacaLegError(f"no {adjustment} bars for {symbols} on {start}..{end}")
    if df.duplicated(["ticker", "date"]).any():
        raise AlpacaLegError("duplicate (ticker, date) bars")
    return df.sort_values(["ticker", "date"]).reset_index(drop=True).assign(adjustment=adjustment)


def corporate_actions(client, symbols, start: dt.date, end: dt.date) -> list:
    from scripts.rv.alpaca_daily import CA_LIMIT, _paged
    symbols = sorted(set(symbols))
    pages = []
    for i in range(0, len(symbols), 20):
        params = {"symbols": ",".join(symbols[i:i + 20]),
                  "types": "cash_dividend,capital_gains_distribution,forward_split,reverse_split,unit_split",
                  "start": start.isoformat(), "end": (end + dt.timedelta(days=60)).isoformat(),
                  "limit": CA_LIMIT}
        pages += list(_paged(client, "/v1/corporate-actions", params, "corporate_actions"))
    return pages


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--c4-pool", action="store_true", help="the 105 C4 pool funds")
    ap.add_argument("--start", required=True, type=dt.date.fromisoformat)
    ap.add_argument("--end", required=True, type=dt.date.fromisoformat)
    a = ap.parse_args(argv)
    if a.c4_pool:
        from scripts.cef.c4_feasibility import NAMES_CSV, declare_pool
        a.symbols = declare_pool(pd.read_csv(NAMES_CSV))[0]
    if not a.symbols:
        raise SystemExit("name the symbols, or pass --c4-pool")
    from scripts.rv.alpaca_daily import make_client
    c = make_client()
    t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    b = pd.concat([bars(c, a.symbols, a.start, a.end, "split"), bars(c, a.symbols, a.start, a.end, "raw")])
    b["fetched_utc"] = t
    cal = [pd.Timestamp(r["date"]) for r in c.calendar(a.start, a.end)]
    ca = corporate_actions(c, a.symbols, a.start, a.end)
    CACHE.mkdir(parents=True, exist_ok=True)
    stem = f"alpaca_bars_{'c4pool' if a.c4_pool else '_'.join(sorted(a.symbols))}_{a.start}_{a.end}"
    b.to_parquet(CACHE / f"{stem}.parquet", index=False)
    (CACHE / f"{stem}_meta.json").write_text(json.dumps(
        {"fetched_utc": t, "sessions": [str(d.date()) for d in cal], "corporate_actions": ca}, default=str))
    for sym in (a.symbols if not a.c4_pool else ["IGR"]):
        x = b[b["ticker"] == sym]
        have = set(x[x["adjustment"] == "split"]["date"])
        miss = [str(d.date()) for d in cal if d not in have]
        print(f"{sym}: {len(have)} split-adjusted bars on {len(cal)} sessions {a.start}..{a.end}; "
              f"sessions with no bar: {miss or 'none'}")
    for page in ca:
        for typ, items in page.items():
            for it in items or []:
                if typ != "cash_dividends" or not a.c4_pool:
                    print(f"corporate action {typ}: {it}")
    print(f"fetched {t} -> {(CACHE / stem).relative_to(REPO)}.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
