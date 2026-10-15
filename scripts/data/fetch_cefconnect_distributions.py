"""CEFConnect's published distribution history, per fund, for trial C4's holdout ruling.

    python3 scripts/data/fetch_cefconnect_distributions.py --c4-universe --start 2024-12-01 --end 2026-10-14
    python3 scripts/data/fetch_cefconnect_distributions.py TY IGR --start 2024-12-01 --end 2026-10-14

WHY THIS EXISTS (2026-10-14, trial C4)
--------------------------------------
Stage 0 found 71 ex-dates in 11 of C4's 74 funds on which yfinance's
distributions (the declared holdout source) disagree with Alpaca's
(`results/cef/C4_RESULT_2026-10-14.md` §4). The team lead ruled on 2026-10-14
(amendment block in `results/cef/PREREG_C4_FAMILIES_2026-10-13.md`) that
Alpaca's amount is used only where a third source confirms it, CEFConnect's
distribution history first. This fetches that history.

ENDPOINT. `GET https://www.cefconnect.com/api/v3/distributionhistory/fund/{TICKER}/{MM-DD-YYYY}/{MM-DD-YYYY}`,
unauthenticated, JSON `{"Data": [...]}`. Each record carries `TotDiv` (the
total per share), its parts (`Income`, `CapitalReturn`, `CapitalLT`,
`CapitalST`, `Special`) and `ExDivDateDisplay`, `PayDateDisplay`,
`DeclaredDateDisplay` as M/D/YYYY strings [V: read 2026-10-14]. A fund can
carry two records on one ex-date (TY books its regular and its capital-gains
distribution separately); `parse` keeps every record and `per_ex_date` sums
them, naming how many were summed. CEFConnect restates its history on the
current share basis for some funds (REFERENCES §12h; IGR after its 2026-09-08
1:3 reverse split shows 0.18 where 0.06 per old share was paid), so a
CEFConnect amount is a check, not a raw record.

NO SILENT FALLBACK. A record with no ex-date or no total raises; an empty
`Data` is a fund with no distributions in the window, written as zero rows
and counted, never filled. Raw responses are cached under the gitignored
`results/cef/c4/_cache_c4/cefconnect_dist/` with the fetch time.
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

URL = "https://www.cefconnect.com/api/v3/distributionhistory/fund/{ticker}/{start}/{end}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}   # as fetch_cef_families_cefconnect.py
CACHE = REPO / "results" / "cef" / "c4" / "_cache_c4" / "cefconnect_dist"
PARSED = REPO / "results" / "cef" / "c4" / "_cache_c4" / "cefconnect_distributions.parquet"
PAUSE_S = 0.4


class CefConnectDistError(RuntimeError):
    pass


def parse(payload: dict, ticker: str) -> pd.DataFrame:
    """One fund's response -> one row per record (not yet summed). Pure."""
    if not isinstance(payload, dict) or "Data" not in payload:
        raise CefConnectDistError(f"{ticker}: response has no 'Data'")
    rows = []
    for i, x in enumerate(payload["Data"] or []):
        if not x.get("ExDivDateDisplay") or x.get("TotDiv") is None:
            raise CefConnectDistError(f"{ticker}[{i}]: record without an ex-date or a total: {x}")
        rows.append(dict(ticker=ticker, ex_date=pd.to_datetime(x["ExDivDateDisplay"], format="%m/%d/%Y"),
                         tot=float(x["TotDiv"]), income=x.get("Income"), capital_return=x.get("CapitalReturn"),
                         capital_lt=x.get("CapitalLT"), capital_st=x.get("CapitalST"), special=x.get("Special"),
                         pay_date=x.get("PayDateDisplay"), declared_date=x.get("DeclaredDateDisplay")))
    cols = ["ticker", "ex_date", "tot", "income", "capital_return", "capital_lt", "capital_st", "special",
            "pay_date", "declared_date"]
    return pd.DataFrame(rows, columns=cols)


def per_ex_date(recs: pd.DataFrame) -> pd.DataFrame:
    """Records summed per (fund, ex-date), with the number of records summed."""
    return (recs.groupby(["ticker", "ex_date"]).agg(cc_amount=("tot", "sum"), cc_records=("tot", "size"))
            .reset_index())


def fetch(ticker: str, start: dt.date, end: dt.date) -> dict:
    import requests
    url = URL.format(ticker=ticker, start=start.strftime("%m-%d-%Y"), end=end.strftime("%m-%d-%Y"))
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise CefConnectDistError(f"{ticker}: HTTP {r.status_code} from {url}")
    return r.json()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--c4-universe", action="store_true", help="the 74 funds of C4's frozen universe")
    ap.add_argument("--start", required=True, type=dt.date.fromisoformat)
    ap.add_argument("--end", required=True, type=dt.date.fromisoformat)
    a = ap.parse_args(argv)
    syms = list(a.symbols)
    if a.c4_universe:
        syms = sorted(pd.read_csv(REPO / "results" / "cef" / "c4" / "c4_universe_frozen_2026-10-14.csv")["ticker"])
    if not syms:
        raise SystemExit("name the symbols, or pass --c4-universe")
    CACHE.mkdir(parents=True, exist_ok=True)
    t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    frames, empty = [], []
    for s in syms:
        js = fetch(s, a.start, a.end)
        (CACHE / f"{s}.json").write_text(json.dumps({"fetched_utc": t, "start": str(a.start), "end": str(a.end),
                                                     "payload": js}))
        f = parse(js, s)
        if f.empty:
            empty.append(s)
        frames.append(f)
        time.sleep(PAUSE_S)
    out = pd.concat(frames, ignore_index=True).assign(fetched_utc=t, window=f"{a.start}..{a.end}")
    out.to_parquet(PARSED, index=False)
    s = per_ex_date(out)
    print(f"fetched {t}: {len(syms)} funds, {len(out)} records, {len(s)} (fund, ex-date) pairs; "
          f"funds with no distribution in the window: {empty or 'none'}; ex-dates with more than one record: "
          f"{s[s['cc_records'] > 1][['ticker', 'ex_date', 'cc_records']].assign(ex_date=lambda x: x['ex_date'].dt.date).values.tolist()}")
    print(f"-> {PARSED.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
