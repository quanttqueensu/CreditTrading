"""Fetch Alpaca's historical closing-auction prints for the deployed CEFs,
2016-01-01 .. 2022-12-31, into a gitignored cache. Read-only market data.

    QUANTT_ENV_FILE=<path to config/.env> python3 scripts/data/fetch_alpaca_auction_history.py

WHY THIS EXISTS
---------------
W4's bid-ask-bounce test (results/cef/RESEARCH_PLAN_2026-10-09.md item 0.6)
asks whether the measured IC survives on a closing-AUCTION price rather than a
last-trade close. The book fills MOC, i.e. at the primary exchange's closing
auction; the backtest prices everything at yfinance's daily close. If the two
are the same number on (almost) every name-day, the "last trade vs auction"
question is closed for the fit period; if not, the disagreement is the size of
the problem. Alpaca's SIP history starts in 2016, so 2016-2022 is all the fit
period this source can speak to (2023+ is the sealed time holdout and is not
requested).

WHAT IS RECORDED
----------------
Every CLOSING print Alpaca returns (`c` array of each auction day), from every
exchange and with every condition code, one row each: date, ticker, exchange
(SIP code), condition, price, t. Nothing is chosen here. The analysis picks
the primary listing's print and states the rule it used; in 2016 Alpaca's
NYSE prints carry condition "6" (Market Center Closing Trade) and later ones
also "M" (Official Close) [V: probe of PDI/HYT 2016-03-01..03, 2026-10-11].

HOW
---
`GET {DATA_BASE}/v2/stocks/auctions`, feed=sip (the only valid feed for
auctions), through `AlpacaClient._get` -- the client's read-only GET with
bounded retry, which never sends anything to the trading endpoint and scrubs
the keys from any error text. One calendar year per request, every page. The
keys are read by `AlpacaClient` from the file QUANTT_ENV_FILE names; this
script never reads, prints or copies them (CLAUDE.md order-path rule 5).

Output: `results/cef/w4/_cache_w4/alpaca_closing_prints_2016_2022.parquet`.
Not committed: vendor data, and the repository is public.

`--side open` (added 2026-10-12, core-signal candidates note): records the
OPENING prints (`o` array) instead, to
`results/cef/w4/_cache_w4/alpaca_opening_prints_2016_2022.parquet`. W4 section 2
found the largest single-day IC on day t+1, which no MOC book decided at t can
earn; whether it lives in the overnight gap or in the t+1 session, measured on
a TRANSACTABLE open (the opening-auction print, not yfinance's first-trade
"open"), decides whether an opening-auction entry is worth a trial. The default
(no flag) is byte-for-byte the closing fetch W4 used.

`--sizes` (same date) adds the print's SIZE in shares (`s`) as a column and
writes `alpaca_{opening,closing}_prints_sized_2016_2022.parquet`, so that the
depth of the opening auction can be compared with the closing auction the book
trades in. A print with no `s` field raises (no default size).

`--holdout` (added 2026-10-14, trial C5, PREREG_C5_OPEN_AUCTION_2026-10-13
DG-C5-6): the OPENING prints of C5's sealed holdout, 2023-01-03 -> 2026-09-30
(the fixed end), to `alpaca_opening_prints_holdout_2023_2026.parquet`. It
REFUSES unless C5's fit verdict is committed: `results/cef/c5/C5_FIT_VERDICT.json`
must exist at HEAD, be tracked, and be unmodified in the working tree
(`fit_verdict_committed`). So the holdout's prices cannot be read before the
fit verdict that they may only kill is on the record. Opening side only.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
OUT = CACHE / "alpaca_closing_prints_2016_2022.parquet"
OUT_OPEN = CACHE / "alpaca_opening_prints_2016_2022.parquet"
OUT_SIZED = {"close": CACHE / "alpaca_closing_prints_sized_2016_2022.parquet",
             "open": CACHE / "alpaca_opening_prints_sized_2016_2022.parquet"}
YEARS = range(2016, 2023)          # 2023+ is the sealed holdout: never requested (except --holdout)
MAX_PAGES = 200
OUT_HOLDOUT = CACHE / "alpaca_opening_prints_holdout_2023_2026.parquet"
HOLDOUT_FIRST, HOLDOUT_END = "2023-01-03", "2026-09-30"   # PREREG_C5 §7: fixed, never moved
FIT_VERDICT = Path("results") / "cef" / "c5" / "C5_FIT_VERDICT.json"


def fit_verdict_committed(repo: Path = REPO, rel: Path = FIT_VERDICT) -> tuple[bool, str]:
    """(ok, reason): is C5's fit verdict on the record? True only if `rel`
    exists in HEAD's tree, is tracked, and the working copy does not differ
    from HEAD. Any git failure is a refusal, never a pass."""
    import subprocess

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)

    if not (repo / rel).exists():
        return False, f"{rel} does not exist"
    if git("cat-file", "-e", f"HEAD:{rel.as_posix()}").returncode != 0:
        return False, f"{rel} is not in HEAD (commit the fit verdict first)"
    if git("diff", "--quiet", "HEAD", "--", rel.as_posix()).returncode != 0:
        return False, f"{rel} differs from HEAD (uncommitted changes)"
    return True, "committed"


class AuctionFetchError(RuntimeError):
    pass


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=("close", "open"), default="close")
    ap.add_argument("--sizes", action="store_true")
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args(argv)
    key, out = ("c", OUT) if a.side == "close" else ("o", OUT_OPEN)
    if a.sizes:
        out = OUT_SIZED[a.side]
    years = list(YEARS)
    if a.holdout:
        if a.side != "open" or a.sizes:
            raise AuctionFetchError("--holdout fetches the opening prints only (--side open, no --sizes)")
        ok, why = fit_verdict_committed()
        if not ok:
            raise AuctionFetchError(f"--holdout refused: C5's fit verdict is not committed ({why})")
        out, years = OUT_HOLDOUT, list(range(2023, 2027))
    from quantt.broker.alpaca import AlpacaClient, DATA_BASE
    from scripts.cef.spec import UNIVERSE
    c = AlpacaClient.from_environment("cef")
    syms = sorted(UNIVERSE)
    rows = []
    for y in years:
        start = f"{y}-01-01T00:00:00Z"
        end = f"{y + 1}-01-01T00:00:00Z" if y < years[-1] else (
            "2022-12-31T23:59:59Z" if not a.holdout else f"{HOLDOUT_END}T23:59:59Z")
        token, pages = None, 0
        while True:
            params = {"symbols": ",".join(syms), "start": start, "end": end,
                      "feed": "sip", "limit": 10000}
            if token:
                params["page_token"] = token
            body = c._get(DATA_BASE, "/v2/stocks/auctions", params)
            if not isinstance(body, dict) or "auctions" not in body:
                raise AuctionFetchError(f"{y}: response has no 'auctions' key")
            for sym, days in (body["auctions"] or {}).items():
                if sym not in syms:
                    raise AuctionFetchError(f"unrequested symbol {sym}")
                for day in days:
                    for p in day.get(key) or []:
                        row = {"date": day["d"][:10], "ticker": sym,
                               "exchange": p["x"], "condition": p["c"],
                               "price": float(p["p"]), "t": p["t"]}
                        if a.sizes:
                            if "s" not in p:
                                raise AuctionFetchError(f"{sym} {day['d'][:10]}: print has no size field")
                            row["size"] = float(p["s"])
                        rows.append(row)
            pages += 1
            nxt = body.get("next_page_token")
            if not nxt:
                break
            if nxt == token or pages >= MAX_PAGES:
                raise AuctionFetchError(f"{y}: paging did not terminate")
            token = nxt
        print(f"{y}: {pages} page(s), cumulative {len(rows)} {a.side} prints")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    if a.holdout:
        if df.date.min() < pd.Timestamp(HOLDOUT_FIRST) or df.date.max() > pd.Timestamp(HOLDOUT_END):
            raise AuctionFetchError(f"a print outside {HOLDOUT_FIRST}..{HOLDOUT_END} was fetched")
    elif df.date.max() >= pd.Timestamp("2023-01-01"):
        raise AuctionFetchError("holdout leak: a 2023+ print was fetched")
    df["fetched_at_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"{len(df)} prints, {df.ticker.nunique()} tickers, {df.date.min().date()}.."
          f"{df.date.max().date()} -> {out.relative_to(REPO)}")
    print(df.groupby(["exchange", "condition"]).size().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
