"""Daily refresh of the credit CEF price and NAV panels.

Run after the US close. Appends only new dates, so it is safe to run repeatedly.

    python3 scripts/cef/fetch_daily.py                       # plain refresh
    python3 scripts/cef/fetch_daily.py --require-asof 2026-09-08 \
            --nav-fallback cefconnect --book ops/books/cef_discount_book.json

--require-asof D   exit 4 unless every deployed name has BOTH a close and a NAV
                   dated D after the refresh, naming the gaps. A row dated D
                   with no finite close is not a close (EMPTY ROWS below).
                   The session uses this so it trades on today's pair or not
                   at all. It checks the DATE only: Yahoo serves rows dated D
                   that carry D-1's NAV
                   (results/cef/LIVE_NAV_QUALITY_2026-10-12.md §5). The VALUE is
                   the session's stale-NAV gate's job (quantt/session/nav_gate.py),
                   which writes its CEFConnect replacements through
                   `merge_nav_fills` / `log_nav_fills` below.
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

LOCKING (2026-09-29). Two things now run this script against the same two
panels: the trading session (`quantt/session/run.py`, step 1) and the nightly
data collector (`quantt/collect`, every 30 minutes). Each run READS both panels,
spends minutes fetching, then REPLACES them. `atomic_write` stops a reader
seeing half a file, but not two writers interleaving: run A reads, run B reads,
B writes its new rows, A writes its own copy -- and B's rows are gone, with no
error anywhere. So the whole read-modify-write runs under an exclusive
`fcntl.flock` on `data/cef/.fetch.lock`. A second run waits for it, at most
LOCK_WAIT_S, then exits 3 naming the lock rather than waiting forever: the
session has a cls cutoff and the collector has its next 30-minute slot, and
neither may be blocked indefinitely by a hung fetch. Exit 3 is a refusal to
refresh, never a partial write.

EMPTY ROWS (fix approved by the team lead 2026-10-28). When Yahoo's chart
response carries a dividend (or split) for a date with no bar, yfinance 0.2.66
emits a row for that date with every price NaN and volume 0: `safe_merge_dfs`
appends a "row of NaNs" for an out-of-range event (yfinance/utils.py:761-767),
`keepna=False` keeps any row whose only datum is that event
(scrapers/history.py:502-506), and Volume is then filled with 0
(scrapers/history.py:492). This script wrote such rows unchecked, and because
each run's row for a date replaces the last one, an empty row overwrote a good
bar. Measured 2026-10-28, read-only, on the laptop's cef_prices.parquet (to
2026-10-15) against its 2026-09-28 backup (cef_prices.parquet.pre-20261015.bak):
15 good 2026-09-15 bars had become empty rows -- BIT, HYT, JFR, MHD and MQY of
the live 13 among them -- and the panel held 65 empty-close rows against the
backup's 49, every one with volume 0. Bars four weeks old were emptied, so this
is not only a partial today. `--require-asof` counted such a row as the as-of
close.

Now (`merge_price_bars`): a fetched row with no close is never merged. It
cannot replace a bar that has a close, it is not written for a date the panel
lacks, and each one is printed as `NO CLOSE <ticker> <date> <why>`. A fetched
bar WITH a close does replace an empty panel row (the repair), printed as
`REPAIRED`; never the other way round. "No close" means the close is missing or
not finite (`has_close`), never volume 0: the panel holds 20 real zero-volume
days that carry a close (FCT 2026-08-10, 9.67), and an empty row's 0 is
yfinance's fill, not a measurement. Nothing is filled or invented; a name whose
only row for D is empty has no close for D and `--require-asof` refuses it.
These lines go to stdout, the record both callers already keep (the session and
the collector each store the last 40 lines), beside the ERR and CEFConnect lines.
With no empty rows the panel bytes are exactly what the old merge wrote
(scripts/cef/tests/test_fetch_daily_empty_rows.py).
"""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
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
ET = ZoneInfo("America/New_York")


def before_close(now: datetime) -> bool:
    """True before 16:05 ET, when a bar dated today is still a partial session.

    ET, not the machine's zone (review 2026-09-29): prod will move to a cloud VM
    that may run in UTC, where 12:30 ET is 16:30 local and the old local-clock
    test would have written a morning's partial bar as that day's close."""
    t = now.astimezone(ET)
    return t.hour < 16 or (t.hour == 16 and t.minute < 5)
FALLBACK_LOG = OUT / "nav_fallback_log.csv"
CC_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
LOCK_PATH = OUT / ".fetch.lock"
# Bounded wait for the panel lock (module docstring, LOCKING). Ten minutes is
# longer than a healthy refresh and shorter than the collector's 30-minute slot.
LOCK_WAIT_S = 600.0
LOCK_POLL_S = 1.0
EXIT_LOCKED = 3


class PanelLockTimeout(RuntimeError):
    """Another fetch held the panel lock for longer than the bounded wait."""


class panel_lock:
    """Exclusive `flock` on `path` for the life of the `with` block.

    Polls with LOCK_NB rather than blocking, because flock has no timeout of
    its own and an unbounded wait is the hang this exists to prevent. The
    holder writes its pid and start time into the file and a timeout names
    them, so a stuck run can be found. The kernel releases the lock if the
    holder dies, so a crash can never leave it held.
    """

    def __init__(self, path, wait_s: float = LOCK_WAIT_S, poll_s: float = LOCK_POLL_S):
        self.path, self.wait_s, self.poll_s = Path(path), float(wait_s), float(poll_s)
        self._fd = None

    def __enter__(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    holder = os.pread(fd, 200, 0).decode("utf-8", "replace").strip()
                    os.close(fd)
                    raise PanelLockTimeout(
                        f"panel lock {self.path} still held after {self.wait_s:.0f}s "
                        f"(holder: {holder or 'unrecorded'}); not refreshing") from None
                time.sleep(self.poll_s)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid {os.getpid()} since {datetime.now().isoformat()}\n".encode(), 0)
        self._fd = fd
        return self

    def __exit__(self, *exc):
        fd, self._fd = self._fd, None
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        return False


def _cefconnect_navs(ticker: str, dates) -> dict:
    """{date: CEFConnect's NAV dated exactly that day, or None}, for each of
    `dates`. Daily rows, ONE request however many dates (2026-10-13: the
    session's stale-NAV gate needs D and D-1 for every deployed name). Rows are
    read newest first and the first row for a date wins, exactly as the
    single-date reader always did."""
    import requests
    out = {pd.Timestamp(d).normalize(): None for d in dates}
    r = requests.get(f"https://www.cefconnect.com/api/v3/pricinghistory/{ticker}/1Y",
                     headers=CC_HEADERS, timeout=20)
    rows = r.json()["Data"]["PriceHistory"]
    seen = set()
    for x in reversed(rows):
        d = pd.Timestamp(x["DataDate"]).normalize()
        if d in out and d not in seen:
            out[d] = float(x["NAVData"])
            seen.add(d)
            if len(seen) == len(out):
                break
    return out


def _cefconnect_nav(ticker: str, asof: pd.Timestamp):
    """CEFConnect's NAV dated exactly `asof`, or None. Daily rows, one request."""
    return _cefconnect_navs(ticker, [asof])[pd.Timestamp(asof).normalize()]


def merge_nav_fills(N: pd.DataFrame, F: pd.DataFrame) -> pd.DataFrame:
    """The NAV panel with the (date, ticker) rows of `F` written over it.

    The one way a NAV not taken from yfinance enters the panel: the
    `--nav-fallback cefconnect` fill below (a NAV yfinance does not have yet)
    and the session's stale-NAV gate (`quantt/session/nav_gate.py`: a yfinance
    row dated D that repeats D-1 while CEFConnect's D differs). Every such row
    is also appended to the fallback log (`log_nav_fills`)."""
    return (pd.concat([N, F], ignore_index=True)
              .drop_duplicates(subset=["date", "ticker"], keep="last")
              .sort_values(["ticker", "date"]))


def log_nav_fills(F: pd.DataFrame, source: str, log_path=None) -> None:
    """Append `F`'s rows to data/cef/nav_fallback_log.csv (columns date, nav,
    ticker, source, written_utc; header written when the file is absent).
    `source` says which path wrote the row: "cefconnect" for a missing NAV,
    "cefconnect_stale_copy" for the gate's replacement. The collector reads this
    log to know a panel NAV came from CEFConnect (`quantt/collect/collect.py`
    `_fallback_names`), so every non-yfinance NAV must be in it."""
    path = FALLBACK_LOG if log_path is None else Path(log_path)
    rec = F.assign(source=source, written_utc=pd.Timestamp.utcnow())
    rec.to_csv(path, mode="a", index=False, header=not path.exists())


def has_close(frame: pd.DataFrame) -> pd.Series:
    """True where a price row carries a close: present and finite.

    THE ONE TEST for an empty row (module docstring, EMPTY ROWS), shared by the
    merge and the as-of check so the two cannot disagree. It keys on the close
    alone. Volume 0 does not make a row empty: real zero-volume days carry a
    close and are kept, and the 0 on an empty row is yfinance's fill. A close
    that is not numeric raises (`pd.to_numeric`), never coerced to "missing"."""
    c = pd.to_numeric(frame["close"]).to_numpy(dtype="float64", na_value=np.nan)
    return pd.Series(np.isfinite(c), index=frame.index)


def merge_price_bars(P: pd.DataFrame, fetched: list) -> tuple:
    """(panel, log): `fetched` merged into the price panel `P`, and one entry per
    row the merge refused or repaired.

    The merge is the one it always was -- concat, keep the LAST row for each
    (date, ticker), sort -- run on the fetched rows that have a close. A
    fetched row with no close is held back, so it can neither replace a panel
    bar nor become a new date (by 2026-10-15, 15 good 2026-09-15 bars had been
    emptied this way; module docstring, EMPTY ROWS). A fetched bar with a close
    that lands on a panel row with none replaces it, as keep="last" always did;
    that repair is now logged. A frame with no empty row is passed through
    untouched, so a fetch without one writes the same bytes as before.

    Each log entry is {"what": "NO CLOSE" | "REPAIRED", "ticker", "date",
    "why"}; the caller prints them. `why` says what the panel holds for that
    date, read from `P` BEFORE the merge."""
    dated = [p["date"].min() for p in fetched if len(p)]
    # Only rows inside the fetched window can be refused or repaired.
    W = P[P["date"] >= min(dated)] if dated else P.iloc[:0]
    w_has = has_close(W)
    panel_bar = set(zip(W.loc[w_has, "date"], W.loc[w_has, "ticker"]))
    panel_empty = set(zip(W.loc[~w_has, "date"], W.loc[~w_has, "ticker"]))
    keep, log = [], []
    for p in fetched:
        ok = has_close(p)
        for r in p.loc[~ok].itertuples(index=False):
            k = (r.date, r.ticker)
            why = ("not merged: the panel's bar for this date has a close and is kept"
                   if k in panel_bar else
                   "not merged: the panel's row for this date has no close either and is left as it was"
                   if k in panel_empty else
                   "not written: the panel has no row for this date")
            log.append({"what": "NO CLOSE", "ticker": r.ticker, "date": r.date,
                        "why": f"(close {r.close}, volume {r.volume}) {why}"})
        for r in p.loc[ok].itertuples(index=False):
            if (r.date, r.ticker) in panel_empty:
                log.append({"what": "REPAIRED", "ticker": r.ticker, "date": r.date,
                            "why": f"the panel's row had no close; yfinance's bar "
                                   f"(close {r.close:g}, volume {r.volume:,}) replaces it"})
        if ok.all():
            keep.append(p)            # as before, even a frame the clock emptied
        elif ok.any():
            keep.append(p.loc[ok])    # an all-empty frame is not concatenated at all
    out = (pd.concat([P] + keep, ignore_index=True)
             .drop_duplicates(subset=["date", "ticker"], keep="last")
             .sort_values(["ticker", "date"]))
    return out, log


def _deployed(book_path) -> list:
    sys.path.insert(0, str(REPO))
    from ops.common import deployed_tickers
    return sorted({t for insts in deployed_tickers(Path(book_path)).values() for t in insts})


def refresh(period: str = "6mo", require_asof=None, nav_fallback=None,
            book=None) -> int:
    if not PX_PATH.exists():
        print("no staged panel; run scripts/cef/stage_cef.py first")
        return 1
    # The read below and the write at its end are one transaction (LOCKING).
    with panel_lock(LOCK_PATH, LOCK_WAIT_S, LOCK_POLL_S):
        return _refresh_locked(period, require_asof, nav_fallback, book)


def _refresh_locked(period, require_asof, nav_fallback, book) -> int:
    P, N = pd.read_parquet(PX_PATH), pd.read_parquet(NAV_PATH)
    now = datetime.now(ET)
    today = pd.Timestamp(now.date())
    session_open = before_close(now)
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

    # A fetched row with no close is never merged; each refusal or repair is
    # printed (module docstring, EMPTY ROWS). The NAV merge below is unchanged.
    P, bar_log = merge_price_bars(P, newp)
    for e in bar_log:
        print(f"  {e['what']:<8} {e['ticker']:<6} {e['date'].date()} {e['why']}")
    N = (pd.concat([N] + newn, ignore_index=True)
           .drop_duplicates(subset=["date", "ticker"], keep="last")
           .sort_values(["ticker", "date"]))

    incomplete = []
    if require_asof is not None:
        asof = pd.Timestamp(require_asof).normalize()
        names = _deployed(book) if book else sorted(tickers)
        # A row dated D with no close is not D's close (EMPTY ROWS): the panel
        # can still hold one written before 2026-10-28, and the fetch may not
        # have brought the bar. Same test as the merge (`has_close`).
        at = P[P["date"] == asof]
        at_has = has_close(at)
        have_px = set(at.loc[at_has, "ticker"])
        empty_px = set(at.loc[~at_has, "ticker"])
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
                N = merge_nav_fills(N, F)
                log_nav_fills(F, "cefconnect")
                have_nav |= set(F["ticker"])
        def gap(t):
            # A missing row reads exactly as it always did; an empty one says so.
            px = (f"no close (its {asof.date()} row is empty)" if t in empty_px
                  else "no close")
            return "/".join(([px] if t not in have_px else [])
                            + (["no NAV"] if t not in have_nav else []))
        incomplete = [f"{t}: {gap(t)}"
                      for t in names if t not in have_px or t not in have_nav]

    # Atomic: these two ARE what the sleeve prices from, and the session
    # holding them open overlaps this write. See ops.common.atomic_write.
    atomic_write(P, PX_PATH)
    atomic_write(N, NAV_PATH)

    tally = {w: sum(e["what"] == w for e in bar_log) for w in ("NO CLOSE", "REPAIRED")}
    print(f"  prices {len(P):,} rows -> {P.date.max().date()}"
          + (f" ({tally['NO CLOSE']} fetched row(s) with no close not merged, "
             f"{tally['REPAIRED']} empty row(s) repaired; listed above)" if bar_log else ""))
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
    try:
        return refresh(a.period, a.require_asof, a.nav_fallback, a.book)
    except PanelLockTimeout as e:
        print(f"  LOCKED: {e}")
        return EXIT_LOCKED


if __name__ == "__main__":
    sys.exit(main())
