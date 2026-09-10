"""Daily refresh of the credit CEF price and NAV panels.

Run after the US close. Appends only new dates, so it is safe to run repeatedly.

    python3 scripts/cef/fetch_daily.py                       # plain refresh
    python3 scripts/cef/fetch_daily.py --require-asof 2026-09-08 \
            --nav-fallback cefconnect --book ops/books/cef_discount_book.json

--require-asof D   exit 4 unless every deployed name has BOTH a close and a NAV
                   dated D after the refresh, naming the gaps. The session uses
                   this so it trades on today's pair or not at all.
--nav-fallback     for a deployed name whose NAV for D is not on yfinance, take
                   CEFConnect's dated row for D. Every such fill is printed and
                   appended to data/cef/nav_fallback_log.csv; the two sources
                   agree to the cent on every comparison made 2026-09-08.

A bar dated TODAY is dropped if the run starts before 16:05 local. yfinance
serves the partial session as a 'Close' (NZF 11.88 on 78k shares at 10:27 on
2026-09-08); written as a close it would put an intraday print in the panel
that the drop_duplicates(keep="last") below would overwrite only at the next
after-hours run.

NAV is the load-bearing input here -- the entire strategy is the gap between price
and NAV, so a stale or missing NAV silently turns the signal into noise. The
freshness of every fund's NAV is therefore checked and reported, and any fund
whose NAV has not updated in three business days is flagged so the sleeve can
drop it rather than trade on a stale number.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:            # run as a script, not -m
    sys.path.insert(0, str(REPO))
from ops.common import atomic_write      # noqa: E402
OUT = REPO / "data" / "cef"
PX_PATH = OUT / "cef_prices.parquet"
NAV_PATH = OUT / "cef_nav.parquet"
STALE_BD = 3
FALLBACK_LOG = OUT / "nav_fallback_log.csv"
CC_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _cefconnect_nav(ticker: str, asof: pd.Timestamp):
    """CEFConnect's NAV dated exactly `asof`, or None. Daily rows, one request."""
    import requests
    r = requests.get(f"https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/1Y",
                     headers=CC_HEADERS, timeout=20)
    rows = r.json()["Data"]["PriceHistory"]
    for x in reversed(rows):
        if pd.Timestamp(x["DataDate"]).normalize() == asof:
            return float(x["NAVData"])
    return None


def _deployed(book_path) -> list:
    sys.path.insert(0, str(REPO))
    from ops.preflight import deployed_tickers
    return sorted({t for insts in deployed_tickers(Path(book_path)).values() for t in insts})


def refresh(period: str = "6mo", require_asof=None, nav_fallback=None,
            book=None) -> int:
    if not PX_PATH.exists():
        print("no staged panel; run scripts/cef/stage_cef.py first")
        return 1
    P, N = pd.read_parquet(PX_PATH), pd.read_parquet(NAV_PATH)
    now = datetime.now()
    today = pd.Timestamp(now.date())
    session_open = now.hour < 16 or (now.hour == 16 and now.minute < 5)
    if session_open:
        print(f"  {now:%H:%M} is before the close: any bar dated {today.date()} "
              f"is a partial session and will not be written")
    tickers = sorted(P.ticker.unique())
    grp = P.drop_duplicates("ticker").set_index("ticker")["grp"].to_dict()

    newp, newn, stale = [], [], []
    for tk in tickers:
        try:
            px = yf.Ticker(tk).history(period=period, auto_adjust=False)
            nav = yf.Ticker(f"X{tk}X").history(period=period, auto_adjust=False)
        except Exception as e:
            print(f"  ERR {tk:<6} {type(e).__name__}")
            continue
        if len(px):
            p = px.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
            p.columns = ["date", "open", "high", "low", "close", "volume"]
            p["date"] = pd.to_datetime(p["date"]).dt.tz_localize(None).dt.normalize()
            if session_open:
                p = p[p["date"] < today]
            p["ticker"], p["grp"] = tk, grp.get(tk, "?")
            newp.append(p)
        if len(nav):
            n = nav.reset_index()[["Date", "Close"]]
            n.columns = ["date", "nav"]
            n["date"] = pd.to_datetime(n["date"]).dt.tz_localize(None).dt.normalize()
            if session_open:
                n = n[n["date"] < today]
            n["ticker"] = tk
            newn.append(n)
            age = len(pd.bdate_range(n.date.max(), pd.Timestamp.today().normalize())) - 1
            if age > STALE_BD:
                stale.append((tk, str(n.date.max().date()), age))

    P = (pd.concat([P] + newp, ignore_index=True)
           .drop_duplicates(subset=["date", "ticker"], keep="last")
           .sort_values(["ticker", "date"]))
    N = (pd.concat([N] + newn, ignore_index=True)
           .drop_duplicates(subset=["date", "ticker"], keep="last")
           .sort_values(["ticker", "date"]))

    incomplete = []
    if require_asof is not None:
        asof = pd.Timestamp(require_asof).normalize()
        names = _deployed(book) if book else sorted(tickers)
        have_px = set(P.loc[P["date"] == asof, "ticker"])
        have_nav = set(N.loc[N["date"] == asof, "ticker"])
        need_nav = [t for t in names if t not in have_nav]
        if need_nav and nav_fallback == "cefconnect":
            filled = []
            for tk in need_nav:
                try:
                    v = _cefconnect_nav(tk, asof)
                except Exception as e:
                    print(f"  cefconnect {tk}: {type(e).__name__}")
                    continue
                if v is None:
                    continue
                filled.append({"date": asof, "nav": v, "ticker": tk})
                print(f"  NAV {tk} {asof.date()} = {v:.2f} from CEFConnect "
                      f"(not on yfinance yet)")
            if filled:
                F = pd.DataFrame(filled)
                N = (pd.concat([N, F], ignore_index=True)
                       .drop_duplicates(subset=["date", "ticker"], keep="last")
                       .sort_values(["ticker", "date"]))
                rec = F.assign(source="cefconnect", written_utc=pd.Timestamp.utcnow())
                rec.to_csv(FALLBACK_LOG, mode="a", index=False,
                           header=not FALLBACK_LOG.exists())
                have_nav |= set(F["ticker"])
        incomplete = [f"{t}: {'no close' if t not in have_px else ''}"
                      f"{'/' if t not in have_px and t not in have_nav else ''}"
                      f"{'no NAV' if t not in have_nav else ''}"
                      for t in names if t not in have_px or t not in have_nav]

    # Atomic: these two ARE what the sleeve prices from, and the session
    # holding them open overlaps this write. See ops.common.atomic_write.
    atomic_write(P, PX_PATH)
    atomic_write(N, NAV_PATH)

    print(f"  prices {len(P):,} rows -> {P.date.max().date()}")
    print(f"  NAV    {len(N):,} rows -> {N.date.max().date()}")
    if stale:
        print(f"  STALE NAV ({len(stale)} funds, >{STALE_BD} business days old) — "
              f"the sleeve must not trade these:")
        for tk, d, age in sorted(stale, key=lambda x: -x[2]):
            print(f"    {tk:<6} last NAV {d}  ({age} bd old)")
    else:
        print(f"  all {N.ticker.nunique()} NAV series fresh within {STALE_BD} bd")
    if incomplete:
        print(f"  INCOMPLETE for {pd.Timestamp(require_asof).date()} on "
              f"{len(incomplete)} deployed name(s): " + "; ".join(incomplete))
        return 4
    if require_asof is not None:
        print(f"  today's pair complete: every deployed name has a close and a "
              f"NAV dated {pd.Timestamp(require_asof).date()}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--period", default="6mo")
    ap.add_argument("--require-asof", default=None)
    ap.add_argument("--nav-fallback", choices=["cefconnect"], default=None)
    ap.add_argument("--book", default=None,
                    help="book json; with --require-asof, only its deployed "
                         "names must be complete (default: the whole panel)")
    a = ap.parse_args(argv)
    return refresh(a.period, a.require_asof, a.nav_fallback, a.book)


if __name__ == "__main__":
    sys.exit(main())
