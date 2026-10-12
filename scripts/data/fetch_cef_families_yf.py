"""Daily price, volume and NAV history for the C4 family CEFs, from yfinance.

    python3 scripts/data/fetch_cef_families_yf.py            # uses the raw cache where present
    python3 scripts/data/fetch_cef_families_yf.py --refresh  # re-fetch every symbol

Writes, under data/cef_families/ only (never data/cef/, landmine 9):

    cef_prices.parquet   date open high low close volume ticker grp    (grp = family)
    cef_nav.parquet      date nav ticker
    cef_actions.parquet  date ticker dividends stock_splits             (of the PRICE ticker)

The first two have exactly the schema of data/cef/cef_prices.parquet and
cef_nav.parquet, so the harness can be pointed at them unchanged.

WHY yfinance, THE SAME WAY THE LIVE PANEL IS BUILT
--------------------------------------------------
C4 is "the live signal on a new family". The live panels come from yfinance
`Ticker(tk).history(auto_adjust=False)` for prices and a NAV symbol's `Close`
for NAV (`scripts/cef/stage_cef.py`, `fetch_daily.py`; `docs/DATA.md` §2). A
family panel built any other way would test a different data pipeline from
the one the book trades on. CEFConnect (dated NAV) and CRSP (prices) are kept
in their own files by their own fetchers, as checks, and are never spliced in.

THE NAV SYMBOL. Not assumed to be `X<TK>X`. Candidates, in order: CEFConnect's
`NavTicker` for the fund (universe table), then `X<TK>X`. Each is fetched.
  * none returns rows  -> the fund has no yfinance NAV: a GAP, written nowhere.
  * one symbol returns rows -> used, and named in `nav_symbol.csv`.
  * two DIFFERENT symbols both return rows -> compared on common dates. If they
    agree within $0.005 on every common date they are one series and the
    CEFConnect-named one is used; otherwise the fund is a NAV CONFLICT and gets
    no NAV here. Never averaged, never picked silently.
A NAV candidate equal to the price ticker is not a NAV symbol and is skipped.

NOT A NAV. A NAV symbol can return the fund's market PRICE. Measured
2026-10-12: XBANX equalled BANX's close within $0.005 on 98.3% of paired
dates, while CEFConnect shows BANX striking a NAV monthly; the next-highest
fund was 1.2% (GGN). A discount computed on such a series is identically
zero, and it would pass every freshness check. So a NAV series that equals
the close on more than PRICE_AS_NAV_SHARE of paired dates is refused, with
the share in the log, and the fund has no NAV here. The threshold sits far
from both measured populations; it is not tuned to either.

DISCIPLINE CARRIED OVER FROM fetch_daily.py
-------------------------------------------
* A bar dated TODAY is dropped if the run starts before 16:05 ET: yfinance
  serves the partial session as a Close (`fetch_daily.before_close`).
* Dates are tz-naive, normalised. A duplicate (ticker, date) keeps the last
  row, as the live panel's `drop_duplicates(keep="last")` does, and every
  duplicate is COUNTED in `yf_fetch_log.csv`.
* A row with no close or no volume is dropped and counted, never filled.
  (`volume` is int64 in the live schema; a NaN cannot be cast honestly.)
* Raw responses are cached per symbol under raw/yfinance/ with the fetch time,
  so a rebuild is reproducible without re-fetching.

SPLITS. yfinance's `Close` with `auto_adjust=False` is split-adjusted after the
fact (docs/DATA.md §4 tests that on CRSP). Whether a NAV symbol is adjusted the
same way is NOT assumed: `cef_families_quality.py` measures the price/NAV
ratio either side of every split in `cef_actions.parquet` and reports any fund
whose two series sit on different share bases. Nothing here adjusts either.

ZERO TRIALS. Data only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.data.cef_families_common import (  # noqa: E402
    ACTIONS, NAV, OUT_DIR, PRICES, RAW_DIR, FamiliesDataError, assert_no_universe_names,
    cef_universe_names, included, load_universe, out_path, write_frame)

TOL_USD = 0.005
PRICE_AS_NAV_SHARE = 0.5
RAW_YF = RAW_DIR / "yfinance"
PAUSE_S = 0.4          # between symbols; politeness, not correctness


def nav_candidates(ticker: str, nav_ticker_cc) -> list[str]:
    """CEFConnect's NAV symbol first, then X<TK>X; unique; never the price ticker."""
    out = []
    for s in (nav_ticker_cc, f"X{ticker}X"):
        if isinstance(s, str) and s and s != ticker and s not in out:
            out.append(s)
    return out


def _raw_path(symbol: str) -> Path:
    return out_path(f"raw/yfinance/{symbol}.parquet")


def fetch_symbol(symbol: str, refresh: bool) -> pd.DataFrame:
    """yfinance daily history, period=max, auto_adjust=False, cached raw.

    Returns the frame as yfinance gave it plus `date` (tz-naive, normalised) and
    `fetched_at_utc`. An empty frame means yfinance returned no rows."""
    p = _raw_path(symbol)
    if p.exists() and not refresh:
        return pd.read_parquet(p)
    import yfinance as yf
    warnings.filterwarnings("ignore")
    h = yf.Ticker(symbol).history(period="max", auto_adjust=False, actions=True)
    h = h.reset_index()
    if len(h):
        h["date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None).dt.normalize()
        h = h.drop(columns=["Date"])
    else:
        h = pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]")})
    h["fetched_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    h.to_parquet(p, index=False)
    time.sleep(PAUSE_S)
    return h


def _drop_partial_today(df: pd.DataFrame, fetched_at_utc: str | None) -> tuple[pd.DataFrame, int]:
    """Drop a bar dated the fetch day if that fetch ran before 16:05 ET."""
    from zoneinfo import ZoneInfo
    if df.empty or not fetched_at_utc:
        return df, 0
    from scripts.cef.fetch_daily import before_close
    t = dt.datetime.fromisoformat(fetched_at_utc)
    day = pd.Timestamp(t.astimezone(ZoneInfo("America/New_York")).date())
    if before_close(t):
        m = df["date"] == day
        return df[~m], int(m.sum())
    return df, 0


def price_rows(raw: pd.DataFrame, ticker: str, family: str) -> tuple[pd.DataFrame, dict]:
    """Live-schema price rows from one raw yfinance frame, with counts of what was dropped."""
    log = {"px_raw_rows": len(raw)}
    if raw.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "ticker", "grp"]), log
    fa = raw["fetched_at_utc"].iloc[0]
    p = raw[["date", "Open", "High", "Low", "Close", "Volume"]].copy()
    p.columns = ["date", "open", "high", "low", "close", "volume"]
    p, log["px_dropped_partial_today"] = _drop_partial_today(p, fa)
    bad = p["close"].isna() | p["volume"].isna()
    log["px_dropped_no_close_or_volume"] = int(bad.sum())
    p = p[~bad]
    dup = p.duplicated("date", keep="last")
    log["px_duplicate_dates"] = int(dup.sum())
    p = p[~dup].copy()
    p["volume"] = p["volume"].astype("int64")
    p["ticker"], p["grp"] = ticker, family
    return p.sort_values("date").reset_index(drop=True), log


def nav_rows(raw: pd.DataFrame, ticker: str) -> tuple[pd.DataFrame, dict]:
    log = {"nav_raw_rows": len(raw)}
    if raw.empty:
        return pd.DataFrame(columns=["date", "nav", "ticker"]), log
    fa = raw["fetched_at_utc"].iloc[0]
    n = raw[["date", "Close"]].rename(columns={"Close": "nav"}).copy()
    n, log["nav_dropped_partial_today"] = _drop_partial_today(n, fa)
    bad = n["nav"].isna()
    log["nav_dropped_nan"] = int(bad.sum())
    n = n[~bad]
    dup = n.duplicated("date", keep="last")
    log["nav_duplicate_dates"] = int(dup.sum())
    n = n[~dup].copy()
    n["ticker"] = ticker
    return n.sort_values("date").reset_index(drop=True), log


def resolve_nav(cands: dict[str, pd.DataFrame], tol: float = TOL_USD) -> tuple[str | None, str]:
    """Pick the NAV symbol per the module docstring. Returns (symbol or None, status)."""
    have = [s for s, f in cands.items() if not f.empty]
    if not have:
        return None, "no NAV rows from any candidate symbol"
    if len(have) == 1:
        return have[0], "one candidate returned rows"
    a, b = cands[have[0]], cands[have[1]]
    m = a.merge(b, on="date", suffixes=("_a", "_b"))
    if m.empty:
        return None, f"CONFLICT: {have[0]} and {have[1]} both return rows on disjoint dates"
    d = (m["nav_a"] - m["nav_b"]).abs()
    if (d <= tol).all():
        return have[0], f"{have[0]} and {have[1]} agree on all {len(m)} common dates"
    return None, f"CONFLICT: {have[0]} vs {have[1]} differ by > ${tol} on {int((d > tol).sum())} of {len(m)} dates"


def price_as_nav_share(p: pd.DataFrame, n: pd.DataFrame, tol: float = TOL_USD) -> float:
    """Share of paired dates on which the NAV equals the close within `tol` (NaN if none paired)."""
    m = p[["date", "close"]].merge(n[["date", "nav"]], on="date")
    return float(((m["close"] - m["nav"]).abs() <= tol).mean()) if len(m) else float("nan")


def actions_rows(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    cols = {"Dividends": "dividends", "Stock Splits": "stock_splits"}
    if raw.empty or not set(cols) <= set(raw.columns):
        return pd.DataFrame(columns=["date", "ticker", "dividends", "stock_splits"])
    a = raw[["date", *cols]].rename(columns=cols)
    a = a[(a["dividends"].fillna(0) != 0) | (a["stock_splits"].fillna(0) != 0)].copy()  # keep event rows only
    a["ticker"] = ticker
    return a[["date", "ticker", "dividends", "stock_splits"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--only", nargs="*", help="restrict to these tickers (debugging)")
    args = ap.parse_args(argv)
    pd.set_option("compute.use_numexpr", False)        # scripts/events/numexpr_fault.py
    u = included(load_universe())
    the44 = cef_universe_names()
    assert_no_universe_names(u["ticker"], the44)
    if args.only:
        u = u[u["ticker"].isin(args.only)]
    P, N, A, LOG = [], [], [], []
    for _, r in u.iterrows():
        tk, fam = r["ticker"], r["family"]
        log = {"ticker": tk, "family": fam}
        try:
            praw = fetch_symbol(tk, args.refresh)
        except Exception as e:                       # recorded per name, never swallowed
            log["error"] = f"price fetch {type(e).__name__}: {e}"
            LOG.append(log); print(f"  ERR {tk:<6} {log['error']}"); continue
        p, pl = price_rows(praw, tk, fam)
        log.update(pl)
        cands, errs = {}, []
        for s in nav_candidates(tk, r.get("nav_ticker_cefconnect")):
            try:
                cands[s] = nav_rows(fetch_symbol(s, args.refresh), tk)[0]
            except Exception as e:
                errs.append(f"{s}: {type(e).__name__}")
                cands[s] = pd.DataFrame(columns=["date", "nav", "ticker"])
        sym, status = resolve_nav(cands)
        log.update({"nav_candidates": " ".join(cands) or "-", "nav_symbol": sym or "",
                    "nav_status": status, "nav_fetch_errors": "; ".join(errs)})
        if sym:
            n, nl = nav_rows(fetch_symbol(sym, False), tk)
            log.update(nl)
            share = price_as_nav_share(p, n)
            log["nav_equals_close_share"] = share
            if share > PRICE_AS_NAV_SHARE:
                status = f"NOT A NAV: {sym} equals the close on {share:.1%} of paired dates"
                log["nav_status"], sym = status, None
            else:
                N.append(n)
        P.append(p)
        A.append(actions_rows(praw, tk))
        log.update({"px_rows": len(p), "nav_rows": len(N[-1]) if sym else 0,
                    "fetched_at_utc": praw["fetched_at_utc"].iloc[0] if len(praw) else ""})
        LOG.append(log)
        print(f"  {tk:<6} {fam:<20} px {len(p):>5} nav {log['nav_rows']:>5} via {sym or '-':<8} {status}")
    P = pd.concat([x for x in P if len(x)], ignore_index=True)
    N = pd.concat([x for x in N if len(x)], ignore_index=True)
    A = pd.concat([x for x in A if len(x)], ignore_index=True)
    for frame in (P, N, A):
        assert_no_universe_names(frame["ticker"].unique(), the44)
    P = P[["date", "open", "high", "low", "close", "volume", "ticker", "grp"]]
    N = N[["date", "nav", "ticker"]]
    P["date"], N["date"] = pd.to_datetime(P["date"]), pd.to_datetime(N["date"])
    if not args.only:
        write_frame(P, PRICES); write_frame(N, NAV); write_frame(A, ACTIONS)
        write_frame(pd.DataFrame(LOG), "yf_fetch_log.csv")
    print(f"\nprices {len(P):,} rows / {P.ticker.nunique()} names, last {P.date.max().date()}; "
          f"NAV {len(N):,} rows / {N.ticker.nunique()} names, last {N.date.max().date()}  -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
