"""Capacity in the closing auction, and the opening auction's cost (C5's first gate).
Zero trials. Read-only market data and account reads.

    QUANTT_ENV_FILE=<config/.env> python3 scripts/cef/exec_capacity_open_cross.py fetch   # ~30 min, resumable
    QUANTT_ENV_FILE=<config/.env> python3 scripts/cef/exec_capacity_open_cross.py report \
        --state /Users/simonjarvis/quantt_state/cef                                       # cache + account reads

`report` needs QUANTT_ENV_FILE as well, for the broker-confirmed fills and the
account's equity history (GET /v2/account/activities/FILL and
/v2/account/portfolio/history -- both read-only; no order endpoint is called
anywhere in this module, and AlpacaClient has no cancel or replace path).
The write-up is results/cef/EXEC_CAPACITY_OPEN_CROSS_2026-10-13.md; the run
behind it is results/cef/exec_capacity/exec_capacity_output.txt.

WHY THIS EXISTS
---------------
1. CAPACITY. results/cef/CORE_SIGNAL_CANDIDATES_2026-10-12.md (§1, "two side
   observations") put the book's dollar-weighted median order at about 0.95x
   the median NYSE closing "print" (2016-22) and said: "If prints are whole
   crosses, the book is a large part of the closing auction it trades in."
   That ratio divided a median ORDER by a median PRINT, from Alpaca's
   /v2/stocks/auctions `s` field, taking condition M (official close) where
   present and 6 (closing trade) otherwise. Two things were unverified: what
   `s` is, and whether a ratio of medians says anything about how large a
   share of a given day's cross one order is. This module answers both, on
   the consolidated tape itself.
2. C5's FIRST KILL TEST. C5 (same note, §1) would fill at the t+1 OPENING
   auction instead of the t+1 close. Its cheapest kill test is the opening
   cross's cost, which had never been measured. The 2026-07-31 overnight
   market orders that filled at 07:27 ET (CLAUDE.md order-path rule 3) are the
   nearest dead relative; an auction-only order cannot fill pre-market, but the
   open cross of a thin CEF could still be a poor price. Measured here against
   a fair reference, beside the same measurement for the close.

WHAT THE CLOSING CROSS IS ON THE TAPE (the rule this module uses)
-----------------------------------------------------------------
CTS Pillar output specification v2.11b (2026-01-29), sale-condition table
(docs/REFERENCES.md §12o): `6` "Market Center Closing Trade" and `O` "Market
Center Opening Trade" UPDATE VOLUME; `M` "Market Center Official Close" and
`Q` "Market Center Official Open" do NOT. So the cross volume is the primary
listing's (NYSE, SIP code N) `6` / `O` print; the `M` / `Q` print is a price
message that repeats a size. Measured on this book's names:
  * On a day with a round-lot cross, /v2/stocks/auctions lists ONE primary `6`
    print (0 of 19,960 name-days in 2016-22 carry two), and the `M` twin
    repeats its size (on all 4,993 days with both).
  * On a day WITHOUT a round-lot cross there is no `6`, yet `M` still carries
    a size: that of the last eligible sale. PCN 2021-04-07: the cross was a
    74-share odd lot (an N print coded `I` at 16:00:02), and `M` said 270 --
    the 270-share regular trade at 15:59:44. MHD 2021-04-07: no N trade after
    16:00 at all, and `M` said 100 at 16.285, a TRF price. So "M where present"
    reads a size that is not the cross on those days; the auctions endpoint
    alone cannot tell an odd-lot cross from no cross.
  * The TAPE often carries the `6` print twice -- same size, about 10-40 ms
    apart: on every closing name-day sampled before 2020-11-04, on most of
    those sampled from then to 2022, and on none in the 2026 window
    (`legacy_duplicates`), while /v2/stocks/auctions lists it once. Identical sizes on every day make two
    separate executions implausible: it is read as one cross printed twice in
    the legacy format, the role `M` took over. Whether the legacy tape counted
    the second copy in volume is [U]; the cross here is one copy.
Therefore: cross shares = the N `6` print; if there is none, the eligible N
trades (not price-only M/Q, not late or extended Z, L, T, U, 9) in the window
that `classify_cross` reads next to the `M` print (see the constants below) --
an odd-lot cross, or zero. The opening side is the same with O/Q. Where both a
`6` and the tape exist, the two are checked against each other and every
mismatch is printed. A cross outside the tape that was fetched is "unknown",
never zero.

WHAT IS MEASURED
----------------
* Cross volume per name per session: the last RECENT_SESSIONS sessions
  (recent, for capacity today) and the 2016-22 cache (for the order-matched
  fit-period view).
* Our order sizes, every session since the book opened (2026-09-29): the
  ORDERED quantity where the laptop's orders.jsonl holds the session, else the
  broker-confirmed FILL (`read_live_orders` says why). Paper orders under
  `late_market` are market orders 8-2 minutes before the close (CLAUDE.md rule
  3 exception), so they never entered the auction: the crosses measured are
  crosses WITHOUT us, and participation is our shares / those cross shares.
* The deployed policy's orders in the fit period at the spec's capital
  (band_gross_capped on the frozen spec, decide t, fill t+1 -- the harness
  convention), each matched to the cross on its own fill date.
* Auction dislocation: |auction price - reference mid| / mid, in bp, at three
  matched horizons (`ref_points`): h0 = the last valid consolidated NBBO
  strictly before the auction (09:30:00 / the close); h1 and h5 = the last
  NBBO 1 and 5 minutes AFTER the open and BEFORE the close. If no valid
  pre-open NBBO exists, the open's h0 reference is the PRIOR session's official
  close (method `prior_close`, counted). "Valid" = bid > 0 and ask >= bid
  (crossed quotes are counted and skipped; locked quotes kept).
  The dislocation is what a participant on the imbalance side of every
  auction would pay; the other side earns it. It is therefore an UPPER
  bound on the cost of an auction fill, and the open-minus-close difference
  is an upper bound on C5's extra cost per unit of turnover.

HOLDOUT (H13)
-------------
Every frame that carries a position, a signal or a return stops at
2022-12-30 (`fit_only`, `_assert_fit`). The recent window (2026) is read for
COSTS and VOLUMES only: cross sizes, quotes, and the sizes of orders the live
book actually sent. No dislocation is signed by our side, no signal is
evaluated, and no return is computed on any date on or after 2023-01-01.

NO SILENT FALLBACKS
-------------------
A name-day with no primary print is a counted gap, never another venue's
print. Two volume-carrying primary prints raise. A missing quote is counted
and, for the open only, replaced by the prior close UNDER ITS OWN LABEL; the
close has no fallback. A cross of zero shares is reported as such, never
divided by.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

NY = ZoneInfo("America/New_York")
OUT_DIR = REPO / "results" / "cef" / "exec_capacity"
CACHE = OUT_DIR / "_cache_exec"                      # gitignored (results/**/_cache_*)
W4_CACHE = REPO / "results" / "cef" / "w4" / "_cache_w4"
FIT_END = "2022-12-30"                               # last session before the sealed holdout
FIT_FIRST = "2016-01-04"                             # Alpaca SIP history starts in 2016
RECENT_SESSIONS = 60
FIT_SAMPLE_EVERY = 14                                # every 14th fit-period session: 126 days
LIVE_FIRST = dt.date(2026, 9, 29)                    # first Alpaca paper session of the book
PRIMARY = "N"                                        # NYSE; every spec name is asset exchange NYSE
VOLUME_CODE = {"close": "6", "open": "O"}            # CTS: updates volume
PRICE_ONLY_CODE = {"close": "M", "open": "Q"}        # CTS: official price, no volume
NOT_CROSS_CODES = {"M", "Q", "Z", "L", "T", "U", "9"}  # price-only, late or extended-hours
CROSS_TRADE_WINDOW_S = 60                            # N tape fetched after the close / after 09:30
# Where the cross is on the primary's tape. CLOSE: the 6 print lands about 2-3s
# after the bell and its M twin follows it by 7ms to over 100ms (JFR 2026-07-22
# 7.5ms; PDI 2026-07-21 104ms); nothing else prints on N between them.
# Continuous-market prints, by contrast, are stamped within milliseconds AFTER
# the bell (MHD 2026-07-29: an N print at 16:00:00.0025). So the close's cross is
# every eligible N print from ANCHOR_LOOKBACK_S before the 6 print (never before
# AFTER_BELL_S after the bell) up to its M twin or 1s after it, whichever is
# first; with no 6, the same lookback before the M print, up to it.
# The lookback is what lets a LATE close be read: legacy NYSE printed PDI's 6 at
# 16:02:01 on 2016-01-04, and PHK's M came at 16:10 on 2026-08-20; the fetch
# takes the same lookback around any such print. Before 2020-11-04 NYSE
# published no M, so a day with no 6 has no anchor; the cross, if any, is then
# an eligible N print in [bell + AFTER_BELL_S, bell + CROSS_TRADE_WINDOW_S].
# OPEN: continuous trading starts on N within ~2ms after the O print (MQY
# 2026-07-23), and O and Q usually share a timestamp, so the open's cross is the
# eligible N prints in [O - CROSS_MS, O] (or [Q - CROSS_MS, Q] with no O).
AFTER_BELL_S = 0.5
ANCHOR_LOOKBACK_S = 2
CROSS_MS = 20
POST_OPEN = dt.time(9, 35)
PREOPEN_FIRST = dt.time(4, 0)
PREOPEN_NEAR = dt.time(9, 0)
REQ_SLEEP_S = 0.31                                   # stay under 200 requests/minute
# A reference quote this wide has a placeholder on one side (MHD's 2018 pre-open
# book carried an ask of $199,999). Such quotes are counted and the means are
# shown with and without them; nothing is dropped silently.
STUB_HS_BP = 1000


class CrossError(RuntimeError):
    """The tape does not have the shape this module's rule assumes."""


# =============================================================================
# pure functions (tested in scripts/cef/tests/test_exec_capacity_open_cross.py)
# =============================================================================

def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def et(d: dt.date, hhmm: dt.time) -> pd.Timestamp:
    """A wall-clock ET time on date d, as a UTC timestamp."""
    return pd.Timestamp(dt.datetime.combine(d, hhmm, NY)).tz_convert("UTC")


def _covered(cov, lo: pd.Timestamp, hi: pd.Timestamp) -> bool:
    """True when [lo, hi] lies inside the tape that was fetched: one window, or
    windows that overlap (a cross can straddle the end of the first minute and
    the start of the window fetched around a late print). A gap is not covered."""
    spans = sorted((_ts(a), _ts(b)) for a, b in (cov or []))
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return any(a <= lo and hi <= b for a, b in merged)


def classify_cross(side: str, auction_rows: list[dict], trades_n: list[dict] | None,
                   boundary: pd.Timestamp, cov: list | None = None) -> dict:
    """The primary exchange's cross on one name-day, from the auction prints and
    (when fetched) the primary's trades.

    auction_rows: this name-day's prints from /v2/stocks/auctions for `side`
        (dicts with x, c, p, s, t), every exchange.
    trades_n: the primary's trades (dicts with t, p, s, c as a list of codes),
        or None when the tape was not fetched for this day.
    boundary: the session close (side "close") or 09:30 ET (side "open").
    cov: the [lo, hi] windows of tape that were fetched for this name-day; a
        cross outside them is "unknown", never "none".

    Returns {kind, shares, price, t, twin_size, check, anchor}. kind is
      "round"   a volume-carrying print (6 / O) exists: its size is the cross;
      "odd"     no 6/O, but primary trades sit at the M/Q print: an odd-lot cross;
      "none"    no 6/O, an M/Q was published, and no primary trade sits at it;
      "unknown" no 6/O and that part of the tape was not fetched;
      "missing" no primary print of either kind, and nothing to anchor on.
    `twin_size` is the M/Q print's size (what the earlier note read). `check`
    is ok / ok_twice (the tape repeats the identical 6/O print) / mismatch /
    not_checked, for a round cross against the tape.
    """
    if side not in VOLUME_CODE:
        raise ValueError(f"side {side!r} is not open|close")
    vc, pc = VOLUME_CODE[side], PRICE_ONLY_CODE[side]
    prim = [r for r in auction_rows if r["x"] == PRIMARY]
    vol = [r for r in prim if r["c"] == vc]
    twin = [r for r in prim if r["c"] == pc]
    if len(vol) > 1:
        raise CrossError(f"{side}: {len(vol)} primary {vc!r} prints on one name-day; the rule "
                         f"assumes one cross print")
    if len({float(r["s"]) for r in twin}) > 1:
        raise CrossError(f"{side}: primary {pc!r} prints disagree on size")
    twin_size = float(twin[0]["s"]) if twin else np.nan
    times = [_ts(r["t"]) for r in vol + twin]
    anchor = max(times) if times else None
    eligible = lambda tr: not (set(tr["c"]) & NOT_CROSS_CODES)

    def tape(lo, hi):
        if trades_n is None or (cov is not None and not _covered(cov, lo, hi)):
            return None
        return [tr for tr in trades_n if lo <= _ts(tr["t"]) <= hi and eligible(tr)]

    after_bell = boundary + pd.Timedelta(seconds=AFTER_BELL_S)
    if side == "close" and vol:
        # hang the window off the 6 print, not off a late M (on 2021-04-16 every
        # name's 6 printed at 16:00:02 and its M at 16:10)
        v_t = _ts(vol[0]["t"])
        lo = max(after_bell, v_t - pd.Timedelta(seconds=ANCHOR_LOOKBACK_S))
        hi = min(anchor, v_t + pd.Timedelta(seconds=1))
        ct, how = tape(lo, hi), "print"
    elif side == "close" and anchor is not None:
        lo = max(after_bell, anchor - pd.Timedelta(seconds=ANCHOR_LOOKBACK_S))
        ct, how = tape(lo, anchor), "print"
    elif side == "close":
        ct, how = tape(after_bell, boundary + pd.Timedelta(seconds=CROSS_TRADE_WINDOW_S)), "window"
    elif anchor is not None:
        ref = _ts(vol[0]["t"]) if vol else _ts(twin[0]["t"])
        # never before 09:30: the primary has not opened
        ct, how = tape(max(boundary, ref - pd.Timedelta(milliseconds=CROSS_MS)), ref), "print"
    else:
        ct, how = None, "none"
    if vol:
        v = vol[0]
        if ct is None:
            check = "not_checked"
        elif abs(sum(float(tr["s"]) for tr in ct) - float(v["s"])) < 1e-9:
            check = "ok"
        elif len(ct) > 1 and all(vc in tr["c"] and float(tr["s"]) == float(v["s"]) for tr in ct):
            # the tape repeats the same 6/O print (legacy convention, see the
            # module docstring): one cross printed twice, not two crosses
            check = "ok_twice"
        else:
            check = "mismatch"
        return dict(kind="round", shares=float(v["s"]), price=float(v["p"]), t=_ts(v["t"]),
                    twin_size=twin_size, check=check, anchor=how)
    if ct is None:
        # no anchor and no tape: there is no primary print to speak of
        kind = "missing" if anchor is None and (how == "none" or trades_n is None) else "unknown"
        return dict(kind=kind, shares=np.nan, price=float(twin[0]["p"]) if twin else np.nan,
                    t=anchor, twin_size=twin_size, check="not_checked", anchor=how)
    sh = sum(float(tr["s"]) for tr in ct)
    if sh > 0:
        px = sum(float(tr["p"]) * float(tr["s"]) for tr in ct) / sh
        return dict(kind="odd", shares=sh, price=px, t=anchor, twin_size=twin_size, check="ok",
                    anchor=how)
    if anchor is None:
        # no 6, no M (before 2020-11-04) and no odd lot after the bell: nothing
        # says an auction ran -- the name may not even have traded (PDO listed
        # in 2021). Not evidence of a zero cross.
        return dict(kind="unknown", shares=np.nan, price=np.nan, t=None, twin_size=np.nan,
                    check="not_checked", anchor=how)
    # an official close was published but no primary trade sits at it: the
    # auction did not trade, and the official price is a last sale, not an auction
    return dict(kind="none", shares=0.0, price=np.nan, t=anchor, twin_size=twin_size, check="ok",
                anchor=how)


def last_valid_quote(quotes: list[dict], before: pd.Timestamp) -> dict | None:
    """The last quote strictly before `before` with bid > 0 and ask >= bid.

    Returns {bp, ap, mid, hs_bp, t, n, n_crossed} or None. A crossed quote is
    skipped (and counted), never averaged into a mid."""
    good, n_crossed, n = None, 0, 0
    for q in sorted(quotes, key=lambda q: _ts(q["t"])):
        if _ts(q["t"]) >= before:
            break
        n += 1
        bp, ap = float(q["bp"]), float(q["ap"])
        if bp > 0 and ap >= bp:
            good = q
        elif bp > 0 and ap > 0:
            n_crossed += 1
    if good is None:
        return None
    bp, ap = float(good["bp"]), float(good["ap"])
    mid = (bp + ap) / 2
    return dict(bp=bp, ap=ap, mid=mid, hs_bp=(ap - bp) / 2 / mid * 1e4, t=_ts(good["t"]),
                n=n, n_crossed=n_crossed)


def dislocation_bp(price: float, mid: float) -> tuple[float, float]:
    """(signed, absolute) distance of an auction price from a reference mid, bp."""
    if not (np.isfinite(price) and np.isfinite(mid) and mid > 0):
        raise ValueError(f"dislocation needs a finite price and a positive mid, got {price}, {mid}")
    s = (price - mid) / mid * 1e4
    return s, abs(s)


def weighted_median(x, w) -> float:
    """The value at which half of the total weight lies at or below (NaN-free input)."""
    x, w = np.asarray(x, float), np.asarray(w, float)
    if len(x) == 0:
        return np.nan
    if np.isnan(x).any() or np.isnan(w).any() or (w < 0).any():
        raise ValueError("weighted_median needs finite x and non-negative weights")
    o = np.argsort(x)
    c = np.cumsum(w[o])
    return float(x[o][np.searchsorted(c, c[-1] / 2)])


def capital_for(target: float, participation_at_ref: float, ref_capital: float) -> float:
    """Capital at which participation reaches `target`, scaling orders linearly
    with capital and holding the cross fixed (our own order does not deepen it)."""
    if not participation_at_ref > 0:
        return np.inf
    return ref_capital * target / participation_at_ref


def backtest_orders(H: pd.DataFrame, px: pd.DataFrame, capital: float) -> pd.DataFrame:
    """Whole-share orders of a weight path, dated on the session they FILL.

    H.loc[t] is decided at t and fills at the t+1 auction (band_frontier.evaluate's
    convention: decide t, MOC fill t+1, earn t+2). The trade decided at t is
    H_t - H_{t-1} (H_{-1} = 0), sized at t's close, the price the sleeve sizes
    with, and rounded to whole shares (Alpaca cannot short or route a fraction).
    The last row has no fill session inside H's index and is dropped."""
    if not H.index.is_monotonic_increasing:
        raise ValueError("H index must be sorted")
    dH = H.diff()
    dH.iloc[0] = H.iloc[0]
    fill = pd.Series(H.index[1:], index=H.index[:-1])
    rows = []
    for t, f in fill.items():
        for k in H.columns:
            w = float(dH.at[t, k])
            if w == 0.0:
                continue
            p = float(px.at[t, k]) if (t in px.index and k in px.columns) else np.nan
            if not (np.isfinite(p) and p > 0):
                raise ValueError(f"{k} traded on {t.date()} with no close to size it")
            sh = int(round(abs(w) * capital / p))
            if sh == 0:
                continue
            rows.append(dict(decided=t, fill=f, ticker=k, shares=float(sh), notional=sh * p,
                             side="buy" if w > 0 else "sell"))
    return pd.DataFrame(rows)


def participation(orders: pd.DataFrame, cross: pd.DataFrame, on: str) -> pd.DataFrame:
    """orders (fill date `on`, ticker, shares) joined to cross (date, ticker,
    kind, shares). part = our shares / cross shares; a zero cross gives inf
    and an unknown/missing cross NaN, so neither is ever averaged in silently."""
    c = cross.rename(columns={"shares": "cross_shares", "date": on})[[on, "ticker", "kind", "cross_shares"]]
    m = orders.merge(c, on=[on, "ticker"], how="left")
    m["kind"] = m["kind"].fillna("missing")
    with np.errstate(divide="ignore", invalid="ignore"):
        m["part"] = np.where(m.cross_shares > 0, m.shares / m.cross_shares,
                             np.where(m.cross_shares == 0, np.inf, np.nan))
    return m


# =============================================================================
# fetch (network; read-only GETs on the market-data host and the account)
# =============================================================================

def _client():
    from quantt.broker.alpaca import AlpacaClient
    return AlpacaClient.from_environment("cef")


def _paged(c, path: str, params: dict, key: str) -> dict:
    """Every page of a multi-symbol market-data GET -> {symbol: [rows]}."""
    from quantt.broker.alpaca import DATA_BASE
    out, token, pages = {}, None, 0
    while True:
        p = dict(params)
        if token:
            p["page_token"] = token
        time.sleep(REQ_SLEEP_S)
        body = c._get(DATA_BASE, path, p)
        if not isinstance(body, dict) or key not in body:
            raise CrossError(f"GET {path}: response has no {key!r} key")
        for sym, rows in (body[key] or {}).items():
            out.setdefault(sym, []).extend(rows)
        pages += 1
        nxt = body.get("next_page_token")
        if not nxt:
            return out
        if nxt == token or pages > 500:
            raise CrossError(f"GET {path}: paging did not terminate")
        token = nxt


def _iso(t: pd.Timestamp) -> str:
    return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _window(c, path, key, syms, lo, hi, extra=None):
    params = {"symbols": ",".join(sorted(syms)), "start": _iso(lo), "end": _iso(hi),
              "feed": "sip", "limit": 10000}
    params.update(extra or {})
    return _paged(c, path, params, key)


def _reduce_quotes(qs: dict, syms, before: pd.Timestamp) -> dict:
    out = {}
    for s in syms:
        q = last_valid_quote(qs.get(s, []), before)
        out[s] = None if q is None else {**q, "t": q["t"].isoformat()}
    return out


def _quotes_before(c, syms, near_lo, far_lo, before):
    """Last valid NBBO before `before`, looking in [near_lo, before) and then, for
    names with none there, [far_lo, near_lo). Returns {sym: reduced quote | None}."""
    qs = _window(c, "/v2/stocks/quotes", "quotes", syms, near_lo, before)
    got = _reduce_quotes(qs, syms, before)
    miss = [s for s in syms if got[s] is None]
    if miss and far_lo < near_lo:
        qs2 = _window(c, "/v2/stocks/quotes", "quotes", miss, far_lo, near_lo)
        got.update(_reduce_quotes(qs2, miss, near_lo))
    return got


def _n_trades(rows: dict) -> dict:
    return {s: [{"t": r["t"], "p": r["p"], "s": r["s"], "c": list(r.get("c") or [])}
                for r in v if r["x"] == PRIMARY] for s, v in rows.items()}


def fetch_day(c, d: dt.date, close_hhmm: str, syms, auctions_day: dict) -> dict:
    """Everything one session needs, reduced to what the analysis reads.

    The primary's tape is fetched for the first CROSS_TRADE_WINDOW_S after the
    close and after 09:30 for every name, and around any primary auction print
    that falls later (the DMM can open late, and can close late: PHK printed
    its M at 16:10 on 2026-08-20). Each window fetched is recorded in `cov`, so
    the analysis can tell "no cross" from "not looked at"."""
    close_t = dt.time(*map(int, close_hhmm.split(":")))
    bounds = {"close": et(d, close_t), "open": et(d, dt.time(9, 30))}
    rec = {"date": d.isoformat(), "close": close_hhmm, "cov": {"close": {}, "open": {}}}
    for side, key in (("close", "c"), ("open", "o")):
        b = bounds[side]
        hi = b + pd.Timedelta(seconds=CROSS_TRADE_WINDOW_S)
        tr = _n_trades(_window(c, "/v2/stocks/trades", "trades", syms, b, hi))
        late = {}
        for s in syms:
            rec["cov"][side][s] = [[_iso(b), _iso(hi)]]
            prim = [r for r in auctions_day.get(s, {}).get(key, []) if r["x"] == PRIMARY]
            ts_ = sorted({_ts(r["t"]) for r in prim if _ts(r["t"]) > hi - pd.Timedelta(seconds=1)})
            if ts_:
                late[s] = ts_
        if late:
            # one multi-symbol request over every late print of the day (legacy
            # NYSE printed all its closes a minute or two after the bell), so the
            # coverage of each name is that one window
            lo2 = min(v[0] for v in late.values()) - pd.Timedelta(seconds=ANCHOR_LOOKBACK_S)
            hi2 = max(v[-1] for v in late.values()) + pd.Timedelta(seconds=1)
            if hi2 - lo2 > pd.Timedelta(minutes=30):
                raise CrossError(f"{d} {side}: late primary prints span {hi2 - lo2}; fetch them per name")
            extra = _n_trades(_window(c, "/v2/stocks/trades", "trades", sorted(late), lo2, hi2))
            for s in late:
                tr[s] = tr.get(s, []) + extra.get(s, [])
                rec["cov"][side][s].append([_iso(lo2), _iso(hi2)])
        rec["trades_" + side] = tr
    rec.update(fetch_refs(c, d, close_hhmm, syms, rec))
    return rec


def ref_points(d: dt.date, close_hhmm: str) -> dict:
    """Every reference quote the cost section reads: {key: (before, near_lo, far_lo)}.

    WHY SEVERAL. The task's reference for the open is the pre-open NBBO at 09:30,
    but a thin CEF's pre-open book is wide and stale (other venues quote it; NYSE
    has not opened), so its mid is a poor fair value. A post-open mid is a better
    one but carries the drift of the minutes between. So the close is given the
    SAME horizons on its own side of the auction (1 and 5 minutes before), and
    the comparison is made horizon by horizon:
      h0  open vs last NBBO before 09:30   |  close vs last NBBO before the close
      h1  open vs last NBBO before 09:31   |  close vs last NBBO 1 minute before the close
      h5  open vs last NBBO before 09:35   |  close vs last NBBO 5 minutes before the close
    At h1 and h5 each side includes a matched horizon of drift (the open's
    minutes are the more volatile ones, which biases AGAINST the open)."""
    close_ts = et(d, dt.time(*map(int, close_hhmm.split(":"))))
    open_ts = et(d, dt.time(9, 30))
    mn = lambda k: pd.Timedelta(minutes=k)
    return {
        "q_preopen": (open_ts, et(d, PREOPEN_NEAR), et(d, PREOPEN_FIRST)),
        "q_open_p1": (open_ts + mn(1), open_ts, open_ts),
        "q_postopen": (et(d, POST_OPEN), et(d, POST_OPEN) - mn(1), open_ts),
        "q_preclose": (close_ts, close_ts - mn(1), close_ts - mn(30)),
        "q_close_m1": (close_ts - mn(1), close_ts - mn(2), close_ts - mn(30)),
        "q_close_m5": (close_ts - mn(5), close_ts - mn(6), close_ts - mn(30)),
    }


def fetch_refs(c, d: dt.date, close_hhmm: str, syms, have: dict) -> dict:
    """The reference quotes `have` does not hold yet (so a cached day can be
    completed without refetching its tape)."""
    out = {}
    for k, (before, near_lo, far_lo) in ref_points(d, close_hhmm).items():
        if k not in have:
            out[k] = _quotes_before(c, syms, near_lo, far_lo, before)
    return out


def fetch_auctions(c, syms, d0: dt.date, d1: dt.date) -> list[dict]:
    """Every auction print, both sides, every exchange, d0..d1 (ET days)."""
    lo, hi = et(d0, dt.time(0, 0)), et(d1, dt.time(16, 30))
    if hi > pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=20):
        raise CrossError(f"{d1} 16:30 ET is less than 20 minutes old; the Basic plan refuses "
                         "recent SIP data")
    got = _paged(c, "/v2/stocks/auctions",
                 {"symbols": ",".join(sorted(syms)), "start": _iso(lo), "end": _iso(hi),
                  "feed": "sip", "limit": 10000}, "auctions")
    rows = []
    for sym, days in got.items():
        if sym not in syms:
            raise CrossError(f"unrequested symbol {sym}")
        for day in days:
            for side, key in (("open", "o"), ("close", "c")):
                for p in day.get(key) or []:
                    if "s" not in p:
                        raise CrossError(f"{sym} {day['d'][:10]}: auction print has no size")
                    rows.append(dict(date=day["d"][:10], ticker=sym, side=side, x=p["x"],
                                     c=p["c"], p=float(p["p"]), s=float(p["s"]), t=p["t"]))
    return rows


def fetch(argv=None) -> int:
    from scripts.cef.spec import UNIVERSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fit", action="store_true")
    # --skip-recent (added 2026-10-14, trial C5 DG-C5-5): fetch ONLY the 2016-22
    # sample. The recent window's auction prints (the last RECENT_SESSIONS
    # sessions) lie inside C5's sealed 2023-01-03 -> 2026-09-30 holdout, whose
    # opening prints PREREG_C5 DG-C5-6 says are read only after the fit verdict
    # is committed; the trial's cost rows need the fit sample alone. Default off:
    # without the flag this fetch is byte-for-byte what the EXEC note ran.
    ap.add_argument("--skip-recent", action="store_true")
    a = ap.parse_args(argv)
    if a.skip_fit and a.skip_recent:
        raise SystemExit("--skip-fit with --skip-recent fetches nothing")
    syms = sorted(UNIVERSE)
    c = _client()
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "days").mkdir(exist_ok=True)
    now = pd.Timestamp.now(tz="UTC")
    cal = c.calendar(dt.date(2015, 12, 1), now.tz_convert(NY).date())
    cal = [r for r in cal if et(r["date"], dt.time(*map(int, r["close"].split(":")))) +
           pd.Timedelta(minutes=20) < now]
    pd.DataFrame([{"date": r["date"].isoformat(), "open": r["open"], "close": r["close"]}
                  for r in cal]).to_parquet(CACHE / "calendar.parquet", index=False)
    days, by_day = [], {}
    if not a.skip_recent:
        recent = cal[-(RECENT_SESSIONS + 1):]            # one extra: the first day's prior close
        print(f"recent window {recent[1]['date']}..{recent[-1]['date']} ({len(recent) - 1} sessions)")
        A = fetch_auctions(c, syms, recent[0]["date"], recent[-1]["date"])
        pd.DataFrame(A).to_parquet(CACHE / "auctions_recent.parquet", index=False)
        for r in A:
            by_day.setdefault(r["date"], {}).setdefault(r["ticker"], {"o": [], "c": []})[
                "o" if r["side"] == "open" else "c"].append(r)
        # daily volume, for the cross's share of the day
        bars = _window(c, "/v2/stocks/bars", "bars", syms, et(recent[1]["date"], dt.time(0, 0)),
                       et(recent[-1]["date"], dt.time(16, 30)), {"timeframe": "1Day", "adjustment": "raw"})
        pd.DataFrame([dict(ticker=s, date=pd.Timestamp(b["t"]).tz_convert(NY).date().isoformat(),
                           v=float(b["v"]), c=float(b["c"])) for s, v in bars.items() for b in v]
                     ).to_parquet(CACHE / "bars_recent.parquet", index=False)
        days = [(r, "recent") for r in recent[1:]]
    if not a.skip_fit:
        fit = [r for r in cal if pd.Timestamp(FIT_FIRST) <= pd.Timestamp(r["date"]) <= pd.Timestamp(FIT_END)]
        days += [(r, "fit") for r in fit[::FIT_SAMPLE_EVERY]]
        fitA = fit_auction_rows(syms)
        fitA = fitA[fitA.x == PRIMARY]
    for i, (r, era) in enumerate(days):
        d = r["date"]
        f = CACHE / "days" / f"{d.isoformat()}.json"
        if f.exists():
            rec = json.loads(f.read_text())
            add = fetch_refs(c, d, r["close"], syms, rec)
            if add:
                rec.update(add)
                f.write_text(json.dumps(rec))
            continue
        if era == "recent":
            aday = by_day.get(d.isoformat(), {})
        else:
            o = fitA[fitA.date == d.isoformat()]
            aday = {}
            for row in o.itertuples():
                aday.setdefault(row.ticker, {"o": [], "c": []})["o" if row.side == "open" else "c"].append(
                    dict(x=row.x, c=row.c, p=row.p, s=row.s, t=row.t))
        rec = fetch_day(c, d, r["close"], syms, aday)
        rec["era"] = era
        f.write_text(json.dumps(rec))
        if i % 20 == 0:
            print(f"  {i + 1}/{len(days)} {d} ({era})", flush=True)
    print(f"done: {len(days)} session files under {CACHE.relative_to(REPO)}/days")
    return 0


# =============================================================================
# report (offline from the cache, plus the account's fills and equity)
# =============================================================================

def hr(title: str) -> None:
    print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)


def _need(p: Path, how: str) -> Path:
    if not p.exists():
        raise FileNotFoundError(f"{p.relative_to(REPO)} is missing; build it with `{how}`. "
                                "No substitute is used.")
    return p


def sample_days(eras=("fit", "recent")) -> dict:
    """{date: era} for exactly the declared sample: the last RECENT_SESSIONS
    sessions of the cached calendar, and every FIT_SAMPLE_EVERY-th fit-period
    session from FIT_FIRST. The cache may hold more (an earlier, denser sample);
    only these are read. `eras` (added 2026-10-14 for trial C5, default both:
    unchanged) restricts it to one sample, e.g. ("fit",) after
    `fetch --skip-recent`."""
    cal = list(pd.read_parquet(_need(CACHE / "calendar.parquet", "... fetch")).date)
    fit = [d for d in cal if FIT_FIRST <= d <= FIT_END][::FIT_SAMPLE_EVERY]
    out = {**{d: "fit" for d in fit}, **{d: "recent" for d in cal[-RECENT_SESSIONS:]}}
    return {d: e for d, e in out.items() if e in eras}


def load_days(eras=("fit", "recent")) -> dict:
    d = _need(CACHE / "days", "python3 scripts/cef/exec_capacity_open_cross.py fetch")
    want = sample_days(eras)
    missing = [x for x in want if not (d / f"{x}.json").exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} sample session(s) not cached (first {missing[:3]}); "
                                "run `fetch`")
    out = {}
    for x, era in want.items():
        rec = json.loads((d / f"{x}.json").read_text())
        if rec.get("era") != era:
            raise ValueError(f"{x}: cached as {rec.get('era')!r}, sampled as {era!r}")
        out[x] = rec
    return out


def cross_tables(days: dict, auctions: pd.DataFrame, syms) -> pd.DataFrame:
    """One row per (date, ticker, side): the classified cross, for every cached day."""
    rows = []
    A = {(r.date, r.ticker, r.side): [] for r in auctions.itertuples()}
    for r in auctions.itertuples():
        A[(r.date, r.ticker, r.side)].append(dict(x=r.x, c=r.c, p=r.p, s=r.s, t=r.t))
    for ds, rec in days.items():
        d = dt.date.fromisoformat(ds)
        close_ts = et(d, dt.time(*map(int, rec["close"].split(":"))))
        for s in syms:
            for side, key, b in (("close", "trades_close", close_ts),
                                 ("open", "trades_open", et(d, dt.time(9, 30)))):
                tr = rec[key].get(s, [])
                x = classify_cross(side, A.get((ds, s, side), []), tr, b, cov=rec["cov"][side][s])
                rows.append(dict(date=ds, ticker=s, side=side, era=rec["era"], **x))
    return pd.DataFrame(rows)


def fit_auction_rows(syms) -> pd.DataFrame:
    """The 2016-22 sized prints (W4's cache), both sides, in this module's row shape."""
    out = []
    for side, name in (("close", "closing"), ("open", "opening")):
        a = pd.read_parquet(_need(W4_CACHE / f"alpaca_{name}_prints_sized_2016_2022.parquet",
                                  f"scripts/data/fetch_alpaca_auction_history.py --side "
                                  f"{side} --sizes"))
        if a.date.max() >= pd.Timestamp("2023-01-01"):
            raise AssertionError("holdout leak in the 2016-22 auction cache")
        a = a[a.ticker.isin(syms)]
        out.append(pd.DataFrame(dict(date=a.date.dt.strftime("%Y-%m-%d"), ticker=a.ticker, side=side,
                                     x=a.exchange, c=a.condition, p=a.price, s=a["size"], t=a.t)))
    return pd.concat(out, ignore_index=True)


def fit_cross_all(fitA: pd.DataFrame, syms) -> pd.DataFrame:
    """Every 2016-22 name-day classified from the auction prints alone (no tape):
    round / unknown (no 6 or O: odd-lot or none) / missing."""
    rows = []
    for (ds, s, side), g in fitA.groupby(["date", "ticker", "side"]):
        b = (et(dt.date.fromisoformat(ds), dt.time(16, 0)) if side == "close"
             else et(dt.date.fromisoformat(ds), dt.time(9, 30)))
        x = classify_cross(side, g.to_dict("records"), None, b)
        rows.append(dict(date=ds, ticker=s, side=side, **x))
    return pd.DataFrame(rows)


def q(x, p):
    x = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna()
    return float(x.quantile(p)) if len(x) else np.nan


def sec_what_the_print_is(X: pd.DataFrame, fitX: pd.DataFrame, cond: dict | None, days: dict) -> None:
    hr("§1 WHAT THE 'CLOSING PRINT' IS: the primary's volume-carrying cross print, checked on the tape")
    if cond:
        print("Alpaca /v2/stocks/meta/conditions/trade?tape=A (read now): "
              + "; ".join(f"{k}={cond[k]!r}" for k in ("6", "M", "O", "Q", "I") if k in cond))
    for era, g in X.groupby("era"):
        print(f"\n{era} sessions ({g.date.nunique()} days; the tape was fetched for every one):")
        for side in ("close", "open"):
            h = g[g.side == side]
            kc = h.kind.value_counts()
            print(f"  {side:<6} name-days {len(h):5d}: " + ", ".join(f"{k} {kc.get(k, 0)}" for k in
                  ("round", "odd", "none", "unknown", "missing")) +
                  f"; round crosses checked against the tape: ok {int(((h.kind == 'round') & (h.check == 'ok')).sum())}, "
                  f"ok but printed twice {int(((h.kind == 'round') & (h.check == 'ok_twice')).sum())}, "
                  f"mismatch {int(((h.kind == 'round') & (h.check == 'mismatch')).sum())}, "
                  f"not checked {int(((h.kind == 'round') & (h.check == 'not_checked')).sum())}")
            nr = h[h.kind.isin(["odd", "none"]) & h.twin_size.notna()]
            if len(nr):
                print(f"         on the {len(nr)} non-round name-days the {PRICE_ONLY_CODE[side]} twin's "
                      f"size is NOT the cross: median twin {nr.twin_size.median():.0f} sh vs median "
                      f"cross {nr.shares.median():.0f} sh")
    print("\nThe tape's volume-carrying print, counted per name-day (the auctions endpoint lists it once):")
    print(legacy_duplicates(days).to_string())
    for side in ("close", "open"):
        h = fitX[fitX.side == side]
        kc = h.kind.value_counts()
        print(f"\n2016-22, every name-day from the auction prints alone ({side}): "
              + ", ".join(f"{k} {kc.get(k, 0)}" for k in ("round", "unknown", "missing"))
              + f"  ('unknown' = no {VOLUME_CODE[side]} print: an odd-lot cross or none; "
              f"{kc.get('unknown', 0) / max(len(h), 1):.1%} of name-days with a primary print)")


def legacy_duplicates(days: dict) -> pd.DataFrame:
    """Name-days whose primary tape carries the volume-carrying print (6 / O) more
    than once, by side and period (before 2020-11-04, when M began; from then to
    the end of the fit period; the 2026 window)."""
    rows = []
    for ds, rec in days.items():
        per = ("a: 2016 -> 2020-11-03" if ds < "2020-11-04" else
               "b: 2020-11-04 -> 2022" if ds <= FIT_END else "c: the 2026 window")
        for side in ("close", "open"):
            for s_, trs in rec["trades_" + side].items():
                v = {(t["t"], t["s"]) for t in trs if VOLUME_CODE[side] in t["c"]}
                if v:
                    sizes = {sz for _, sz in v}
                    rows.append(dict(side=side, period=per, multi=len(v) > 1,
                                     same_size=len(v) > 1 and len(sizes) == 1))
    D = pd.DataFrame(rows)
    return D.groupby(["side", "period"]).agg(name_days=("multi", "size"), printed_twice_or_more=("multi", "sum"),
                                             of_which_identical_sizes=("same_size", "sum"))


def sec_cross_volume(X: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    hr(f"§2 CROSS VOLUME BY NAME, last {RECENT_SESSIONS} sessions (shares and $; the cross WITHOUT us)")
    R = X[X.era == "recent"].copy()
    R["usd"] = R.shares * R.price
    b = bars.rename(columns={"v": "day_v"})
    C = R[R.side == "close"].merge(b[["date", "ticker", "day_v"]], on=["date", "ticker"], how="left")
    O = R[R.side == "open"]
    rows = []
    for s, g in C.groupby("ticker"):
        o = O[O.ticker == s]
        rows.append(dict(ticker=s, sessions=len(g),
                         close_sh_med=g.shares.median(), close_sh_p10=q(g.shares, 0.10),
                         close_usd_med=(g.shares * g.price.fillna(0)).median(),
                         no_round=int((g.kind != "round").sum()), zero=int((g.kind == "none").sum()),
                         close_share_of_day=(g.shares / g.day_v).median(),
                         open_sh_med=o.shares.median(), open_over_close=o.shares.median() / g.shares.median()))
    T = pd.DataFrame(rows).set_index("ticker")
    with pd.option_context("display.width", 200):
        print(T.round(4).to_string())
    print(f"  median across names: close cross {T.close_sh_med.median():.0f} sh "
          f"(${T.close_usd_med.median():,.0f}); open cross {T.open_sh_med.median():.0f} sh; "
          f"open/close {T.open_over_close.median():.1f}x; close cross = "
          f"{T.close_share_of_day.median():.2%} of the day's consolidated volume")
    return T


def read_live_orders(client, state: Path | None, last_day: dt.date, bars: pd.DataFrame):
    """The book's order sizes per (day, ticker), every session since LIVE_FIRST.

    WHICH SIZE. The size that matters for capacity is what a live account would
    send to the auction. Where the laptop's orders.jsonl holds the session
    (2026-09-29 .. 10-07) that is the ORDERED quantity: on 2026-09-29 the book
    sent `cls` orders from flat and paper expired 11 of 13, so the fills
    understate that session's orders. Elsewhere (the VM era, 2026-10-08 on,
    whose records this module does not read) it is the broker-confirmed FILLED
    quantity; under `late_market` paper fills market `day` orders in full, which
    the overlap days check (ordered == filled). Notional is shares x the day's
    consolidated close (daily bar), used only to weight orders.
    Equity: GET /v2/account/portfolio/history (1D), the prior session's value,
    used to rescale each order to $100,000 of capital."""
    from quantt.session.verify import parse_fill
    cal = pd.read_parquet(CACHE / "calendar.parquet")
    sess = [dt.date.fromisoformat(x) for x in cal.date if LIVE_FIRST <= dt.date.fromisoformat(x) <= last_day]
    rows = []
    for d in sess:
        for a in client.activities_fills(d):
            f = parse_fill(a)
            rows.append(dict(fill=d.isoformat(), ticker=f.symbol, side=f.side, qty=float(f.qty)))
    F = pd.DataFrame(rows)
    if F.empty:
        raise ValueError("no fills read from the account")
    if (F.groupby(["fill", "ticker"]).side.nunique() > 1).any():
        raise ValueError("both sides in one name-day: the book nets each symbol into one side")
    Fd = F.groupby(["fill", "ticker"]).qty.sum().rename("filled").reset_index()
    sub = []
    if state is not None:
        for f in sorted(state.glob("2026-*/orders.jsonl")):
            for line in f.read_text().splitlines():
                e = json.loads(line)
                if e.get("event") == "submit":
                    sub.append(dict(fill=f.parent.name, ticker=e["symbol"], ordered=float(e["qty"]),
                                    tif=e["time_in_force"]))
    S = (pd.DataFrame(sub).groupby(["fill", "ticker"]).agg(ordered=("ordered", "sum"), tif=("tif", "first"))
         .reset_index() if sub else pd.DataFrame(columns=["fill", "ticker", "ordered", "tif"]))
    O = S.merge(Fd, on=["fill", "ticker"], how="outer")
    O["shares"] = O.ordered.combine_first(O.filled)
    O["src"] = np.where(O.ordered.notna(), "ordered", "filled")
    px = bars.set_index(["date", "ticker"]).c
    O["notional"] = [O_sh * px.get((d, t), np.nan) for O_sh, d, t in zip(O.shares, O.fill, O.ticker)]
    if O.notional.isna().any():
        raise ValueError(f"no daily close for {O[O.notional.isna()][['fill', 'ticker']].values.tolist()}")
    from quantt.broker.alpaca import PAPER_BASE
    ph = client._get(PAPER_BASE, "/v2/account/portfolio/history", {"period": "2M", "timeframe": "1D"})
    for k in ("timestamp", "equity"):
        if k not in ph:
            raise ValueError(f"portfolio/history has no {k!r}")
    E = pd.Series([float(e) if e is not None else np.nan for e in ph["equity"]],
                  index=[pd.Timestamp(t, unit="s", tz="UTC").tz_convert(NY).date().isoformat()
                         for t in ph["timestamp"]])
    cal_list = list(cal.date)
    O["equity_prev"] = [E.get(cal_list[cal_list.index(d) - 1], np.nan) for d in O.fill]
    if O.equity_prev.isna().any() or (O.equity_prev <= 0).any():
        bad = sorted(O[O.equity_prev.isna() | (O.equity_prev <= 0)].fill.unique())
        raise ValueError(f"no positive equity on the prior close for order days {bad}")
    return O, E


def summarize_part(M: pd.DataFrame, by="ticker", scale_col=None, ref=100_000.0) -> pd.DataFrame:
    """Per-name participation statistics at `ref` capital (orders rescaled from
    the equity they were sized on when scale_col is given)."""
    M = M.copy()
    if scale_col:
        M["part"] = M.part * ref / M[scale_col]
        M["notional"] = M.notional * ref / M[scale_col]
    rows = []
    for k, g in list(M.groupby(by)) + [("ALL", M)]:
        fin = g[np.isfinite(g.part)]
        rows.append(dict(**{by: k}, orders=len(g), zero_cross=int(np.isinf(g.part).sum()),
                         unmeasured=int(g.part.isna().sum()),
                         med=fin.part.median() if len(fin) else np.nan, p90=q(fin.part, 0.9),
                         max=fin.part.max() if len(fin) else np.nan,
                         wmed=weighted_median(fin.part, fin.notional) if len(fin) else np.nan))
    T = pd.DataFrame(rows).set_index(by)
    for x in (0.10, 0.25):
        T[f"K{int(x * 100)}_med"] = [capital_for(x, v, ref) for v in T.med]
        T[f"K{int(x * 100)}_wmed"] = [capital_for(x, v, ref) for v in T.wmed]
    return T


def _fmt_part(T: pd.DataFrame) -> str:
    f = T.copy()
    for c in [c for c in ("med", "p90", "max", "wmed") if c in f.columns]:
        f[c] = f[c].map(lambda v: "-" if not np.isfinite(v) else f"{v:.2%}")
    for c in [c for c in f.columns if c.startswith("K")]:
        f[c] = f[c].map(lambda v: "-" if not np.isfinite(v) else f"${v / 1e6:,.2f}m")
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        return f.to_string()


def sec_live(client, state, X, last_day, bars):
    hr("§3 OUR ORDERS vs THE SAME DAY'S CROSS: every session since the book opened (2026-09-29)")
    O, E = read_live_orders(client, state, last_day, bars)
    # Counts and ratios only: no equity, position or order size is printed (the
    # output is tracked and the repository is public).
    r = O.equity_prev / 100_000.0
    print(f"{len(O)} name-day orders on {O.fill.nunique()} sessions {O.fill.min()}..{O.fill.max()}; each "
          f"rescaled to $100,000 of capital by the prior close's equity (ratio {r.min():.3f}..{r.max():.3f})")
    both = O.dropna(subset=["ordered", "filled"])
    print(f"size source: ordered (laptop orders.jsonl) {int((O.src == 'ordered').sum())}, filled (broker, "
          f"VM era) {int((O.src == 'filled').sum())}. Where both exist ({len(both)} name-days): ordered == filled "
          f"on {int((both.ordered == both.filled).sum())}; ordered but no fill {int((O.ordered.notna() & O.filled.isna()).sum())} "
          f"(all `cls` on 2026-09-29: {int((O.ordered.notna() & O.filled.isna() & (O.tif == 'cls')).sum())})")
    print(O.groupby("fill").agg(names=("ticker", "size"), src=("src", "first")).T.to_string())
    dv = bars.set_index(["date", "ticker"]).v
    O["day_share"] = [sh / dv.get((d, t), np.nan) for sh, d, t in zip(O.shares, O.fill, O.ticker)]
    st_ = O[O.fill >= "2026-10-01"]
    print(f"our orders as a share of the day's CONSOLIDATED volume (all venues): steady state median "
          f"{st_.day_share.median():.2%}, p90 {q(st_.day_share, .9):.2%}, max {st_.day_share.max():.2%}; "
          f"build day median {O[O.fill == '2026-09-29'].day_share.median():.2%}")
    R = X[(X.era == "recent")]
    out = {}
    for side in ("close", "open"):
        M = participation(O.rename(columns={"fill": "date"}), R[R.side == side], on="date")
        out[side] = M.rename(columns={"date": "fill"})
    phases = [("BUILD: 2026-09-29, the 13 orders sent from flat", lambda m: m.fill == "2026-09-29"),
              ("CATCH-UP: 2026-09-30, the build of the names whose cls orders expired",
               lambda m: m.fill == "2026-09-30"),
              ("STEADY STATE: 2026-10-01 on", lambda m: m.fill >= "2026-10-01")]
    for lab, sel in phases:
        for side in ("close", "open"):
            M = out[side][sel(out[side])]
            if M.empty:
                continue
            print(f"\n{lab} -- vs the {side.upper()} cross of the same day (C5 would use the open):")
            print(_fmt_part(summarize_part(M, scale_col="equity_prev")))
    return O, out


def sec_backtest(fitX, X):
    """Deployed policy, fit period, at the spec's capital: orders matched to the
    cross of their own fill day, both sides; then the same order sizes ($)
    against the recent crosses."""
    hr("§4 THE DEPLOYED POLICY'S ORDERS AT THE SPEC'S CAPITAL, fit period (decide t, fill t+1)")
    from scripts.cef.band_frontier import band_gross_capped, build_panel, build_targets, fit_only
    from scripts.cef.spec import BAND_WIDTH, CAPITAL_USD, MAX_GROSS_STRESS, summary
    from scripts.cef.w4_artifacts import _assert_fit
    T, R = build_targets()
    T, R = fit_only(T, R)
    cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
    H = band_gross_capped(T, BAND_WIDTH, cap)
    px = build_panel(end=FIT_END)["px"]
    _assert_fit(H, px)
    B = backtest_orders(H, px, CAPITAL_USD)
    B = B[(B.fill >= pd.Timestamp(FIT_FIRST)) & (B.fill <= pd.Timestamp(FIT_END))]
    _assert_fit(B.set_index("fill"))
    B["fill"] = B.fill.dt.strftime("%Y-%m-%d")
    print(summary())
    print(f"{len(B)} whole-share orders on {B.fill.nunique()} fill days {B.fill.min()}..{B.fill.max()} "
          f"at ${CAPITAL_USD:,.0f}")
    res = {}
    for side in ("close", "open"):
        M = participation(B.rename(columns={"fill": "date"}), fitX[fitX.side == side], on="date")
        M = M.rename(columns={"date": "fill"})
        k = M.kind.value_counts()
        print(f"\nvs the {side.upper()} cross of the fill day: orders on round-cross days {k.get('round', 0)}, "
              f"on days with no {VOLUME_CODE[side]} print (odd-lot or no cross; participation not "
              f"computed) {k.get('unknown', 0)} = {k.get('unknown', 0) / len(M):.1%} of orders, "
              f"{M[M.kind == 'unknown'].notional.sum() / M.notional.sum():.1%} of notional; "
              f"missing {k.get('missing', 0)}")
        res[side] = M
        print(_fmt_part(summarize_part(M[M.kind == "round"], ref=CAPITAL_USD)))
    # the earlier note's statistic, reproduced, then what it should have been
    Mc = res["close"]
    a = fit_auction_rows(sorted(B.ticker.unique()))
    a = a[(a.side == "close") & (a.x == PRIMARY)]
    pv = a.pivot_table(index=["date", "ticker"], columns="c", values=["p", "s"], aggfunc="first")
    price = pv["p"]["M"].combine_first(pv["p"]["6"])
    size = pv["s"]["M"].combine_first(pv["s"]["6"])
    med_print = (price * size).groupby(level="ticker").median()
    wmed_order = B.groupby("ticker").notional.apply(lambda v: weighted_median(v, v))
    ratio = (wmed_order / med_print).median()
    print(f"\nThe 2026-10-12 note's statistic, reproduced on this order set: median across names of "
          f"[dollar-weighted median order / median (M-else-6) print $] = {ratio:.2f}x")
    rr = Mc[Mc.kind == "round"]
    print(f"Day-matched instead: median participation {rr.part.median():.2%}, notional-weighted median "
          f"{weighted_median(rr.part, rr.notional):.2%}, p90 {q(rr.part, .9):.2%} (all names, round-cross days)")
    # fit-period order sizes ($ at the spec's capital) against today's crosses
    Rc = X[(X.era == "recent") & (X.side == "close") & (X.kind == "round")].copy()
    Rc["usd"] = Rc.shares * Rc.price
    rows, allP, allW = [], [], []
    for s, g in B.groupby("ticker"):
        cu = Rc[Rc.ticker == s].usd.to_numpy()
        if not len(cu):
            continue
        P = (g.notional.to_numpy()[:, None] / cu[None, :]).ravel()
        W = np.repeat(g.notional.to_numpy(), len(cu)) / len(cu)   # each order weighs its notional once
        allP.append(P), allW.append(W)
        rows.append(dict(ticker=s, pairs=len(P), med=np.median(P), p90=np.quantile(P, .9),
                         wmed=weighted_median(P, W)))
    P, W = np.concatenate(allP), np.concatenate(allW)
    rows.append(dict(ticker="ALL", pairs=len(P), med=np.median(P), p90=np.quantile(P, .9),
                     wmed=weighted_median(P, W)))
    Tn = pd.DataFrame(rows).set_index("ticker")
    for x in (0.10, 0.25):
        Tn[f"K{int(x * 100)}_med"] = [capital_for(x, v, CAPITAL_USD) for v in Tn.med]
        Tn[f"K{int(x * 100)}_wmed"] = [capital_for(x, v, CAPITAL_USD) for v in Tn.wmed]
    print(f"\nFit-period order sizes ($, at ${CAPITAL_USD:,.0f}) against the last {RECENT_SESSIONS} sessions' "
          "round closing crosses ($), every order x every session:")
    print(_fmt_part(Tn))
    return B, res, Tn, H, R


def sec_breakeven(H, R):
    hr("§5 CONTEXT FOR THE C5 GATE: the deployed book's gross return per unit of turnover, fit period")
    from scripts.cef.band_frontier import evaluate, total_returns
    from scripts.cef.w4_artifacts import _assert_fit
    Rt = total_returns(R)
    _assert_fit(Rt)
    out = {}
    for lab, lo in (("2013-06-21 -> 2022-12-30 (book live)", "2013-06-21"), ("2016-01-04 -> 2022-12-30", FIT_FIRST)):
        Hs, Rs = H.loc[lo:], Rt.loc[lo:]
        e = evaluate(Hs, Rs)
        be = e["ann_ret"] / e["turn"] * 1e4
        out[lab] = be
        print(f"  {lab}: gross {e['ann_ret']:.2%}/yr (total return), turnover {e['turn']:.1f}x/yr one-way, "
              f"gross per unit of turnover {be:.1f}bp")
    print("  (no borrow, no execution cost; this is the deployed book's breakeven cost per unit turnover)")
    return out


HORIZONS = {"h0": {"open": "q_preopen", "close": "q_preclose"},
            "h1": {"open": "q_open_p1", "close": "q_close_m1"},
            "h5": {"open": "q_postopen", "close": "q_close_m5"}}


def cost_table(days: dict, X: pd.DataFrame, prior_close: dict) -> pd.DataFrame:
    """Per name-day, side and horizon: the auction price against the reference
    mid (bp). Only name-days with an auction trade (round or odd) are scored: a
    day with no cross has no auction price. The open at h0 with no valid
    pre-open NBBO uses the PRIOR official close, labelled `prior_close`; no other
    reference has a fallback (`unmeasured`)."""
    rows = []
    for r in X[X.kind.isin(["round", "odd"])].itertuples():
        rec = days[r.date]
        d = dt.date.fromisoformat(r.date)
        pts = ref_points(d, rec["close"])
        for h, keys in HORIZONS.items():
            key = keys[r.side]
            if key not in rec:
                raise KeyError(f"{r.date}: reference {key} not cached; run `fetch` to complete the cache")
            qte = rec[key].get(r.ticker)
            method, mid, hs, age = "nbbo", np.nan, np.nan, np.nan
            if qte is not None:
                mid, hs = qte["mid"], qte["hs_bp"]
                age = (pts[key][0] - _ts(qte["t"])).total_seconds()
            elif r.side == "open" and h == "h0":
                pc = prior_close.get((r.date, r.ticker))
                method, mid = ("prior_close", pc) if pc is not None and np.isfinite(pc) else ("unmeasured", np.nan)
            else:
                method = "unmeasured"
            sgn, ab = dislocation_bp(r.price, mid) if np.isfinite(mid) else (np.nan, np.nan)
            rows.append(dict(date=r.date, ticker=r.ticker, side=r.side, era=r.era, h=h, method=method,
                             kind=r.kind, signed=sgn, abs=ab, hs=hs, age_s=age))
    return pd.DataFrame(rows)


def prior_closes(days: dict, auctions_recent: pd.DataFrame, fitA: pd.DataFrame) -> dict:
    """{(date, ticker): the PRIOR session's official close on the primary}: the
    M print, else the 6 print (they agree wherever both exist; before
    2020-11-04 only 6 is published). Used only as the open's labelled fallback
    reference when no valid pre-open NBBO exists."""
    cal = list(pd.read_parquet(CACHE / "calendar.parquet").date)
    allA = pd.concat([auctions_recent, fitA], ignore_index=True)
    c = allA[(allA.side == "close") & (allA.x == PRIMARY)]
    m = c[c.c == "M"].drop_duplicates(["date", "ticker"]).set_index(["date", "ticker"]).p
    six = c[c.c == "6"].drop_duplicates(["date", "ticker"]).set_index(["date", "ticker"]).p
    offp = m.combine_first(six)
    by_date = {d: g.droplevel(0) for d, g in offp.groupby(level=0)}
    out = {}
    for ds in days:
        prev = cal[cal.index(ds) - 1]
        for t, v in by_date.get(prev, pd.Series(dtype=float)).items():
            out[(ds, t)] = float(v)
    return out


def _date_t(d: pd.Series) -> tuple[float, int]:
    """t of the mean of a per-name-day series, clustered by date (sessions share a market)."""
    dd = d.groupby(level="date").mean()
    if len(dd) < 3:
        return np.nan, len(dd)
    return dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd))), len(dd)


def sec_cost(days, X, pc, breakeven: dict):
    hr("§6 C5 GATE: the auction price against a fair reference mid, OPEN vs CLOSE, by name (bp)")
    print("abs = |auction price - reference mid| / mid. Horizons (see ref_points): h0 = last NBBO before the "
          "auction (open: before 09:30, prior official close if none, labelled); h1 / h5 = last NBBO 1 / 5 "
          "minutes AFTER the open and 1 / 5 minutes BEFORE the close. hs = that quote's half-spread. "
          "Name-days with no auction trade are not scored.")
    C = cost_table(days, X, pc)
    be = min(breakeven.values()) if breakeven else np.nan
    out = {}
    for era in ("recent", "fit"):
        g = C[C.era == era]
        if g.empty:
            continue
        print(f"\n{era.upper()}: {g.date.nunique()} sessions")
        for h in HORIZONS:
            gh = g[g.h == h]
            m = gh.groupby(["side", "method"]).size()
            print(f"  [{h}] reference methods: " + ", ".join(f"{a} {b} {n}" for (a, b), n in m.items()))
            cl = gh[(gh.side == "close") & (gh.method != "unmeasured")]
            op = gh[(gh.side == "open") & (gh.method != "unmeasured")]
            pair = (cl.set_index(["date", "ticker"])["abs"].rename("c").to_frame()
                    .join(op[op.method == "nbbo"].set_index(["date", "ticker"])["abs"].rename("o"), how="inner"))
            dif = pair.o - pair.c
            rows = []
            for t_ in sorted(gh.ticker.unique()):
                a, b = cl[cl.ticker == t_], op[op.ticker == t_]
                dt_ = dif[dif.index.get_level_values("ticker") == t_]
                rows.append(dict(ticker=t_, close_n=len(a), close_med=a["abs"].median(), close_mean=a["abs"].mean(),
                                 close_hs=a.hs.median(), open_n=len(b), open_med=b["abs"].median(),
                                 open_mean=b["abs"].mean(), open_hs=b.hs.median(),
                                 diff_med=dt_.median(), diff_mean=dt_.mean()))
            T = pd.DataFrame(rows).set_index("ticker")
            t, nd = _date_t(dif)
            out[(era, h)] = dict(close_mean=cl["abs"].mean(), open_mean=op["abs"].mean(), diff_mean=dif.mean(),
                                 diff_med=dif.median(), t=t)
            if h in ("h0", "h5") or era == "recent":
                with pd.option_context("display.width", 220, "display.max_columns", 20):
                    print(T.round(1).to_string())
            print(f"  [{h}] pooled: close median {cl['abs'].median():.1f} / mean {cl['abs'].mean():.1f}; open median "
                  f"{op['abs'].median():.1f} / mean {op['abs'].mean():.1f}; paired open - close (NBBO-referenced, "
                  f"{len(dif)} name-days): median {dif.median():+.1f}, mean {dif.mean():+.1f} (date-clustered t "
                  f"{t:.2f}, {nd} dates)")
            print(f"  [{h}] signed mean (price - mid): close {cl.signed.mean():+.1f}, open {op.signed.mean():+.1f}; "
                  f"quoted half-spread median: close {cl.hs.median():.1f}, open {op[op.method == 'nbbo'].hs.median():.1f}; "
                  f"reference age median: close {cl.age_s.median():.0f}s, open {op.age_s.median():.0f}s")
            stub = gh[(gh.method == "nbbo") & (gh.hs > STUB_HS_BP)]
            if len(stub):
                keep = ~pair.index.isin(stub.set_index(["date", "ticker"]).index)
                print(f"  [{h}] STUB-LIKE references (half-spread > {STUB_HS_BP:,}bp, e.g. an ask of $199,999): "
                      f"{len(stub)} name-day(s), {sorted(stub.ticker.unique())}. Shown, not dropped; beside the "
                      f"figures above, without them: open mean {op[~op.index.isin(stub.index)]['abs'].mean():.1f}, "
                      f"paired mean {(pair.o - pair.c)[keep].mean():+.1f}")
            if np.isfinite(be):
                print(f"  [{h}] the mean open surcharge is {dif.mean() / be:.0%} of the deployed book's gross return per "
                      f"unit of turnover ({be:.1f}bp, the lower of the §5 windows) -- an UPPER bound on C5's extra "
                      "cost, reached only if C5 sat on the imbalance side of every opening cross")
    return C, out


def report(argv=None) -> int:
    from scripts.cef.spec import UNIVERSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=Path, default=None,
                    help="the laptop's retired prod state dir (read-only), for orders.jsonl")
    a = ap.parse_args(argv)
    syms = sorted(UNIVERSE)
    days = load_days()
    Ar = pd.read_parquet(_need(CACHE / "auctions_recent.parquet", "... fetch"))
    fitA = fit_auction_rows(syms)
    bars = pd.read_parquet(_need(CACHE / "bars_recent.parquet", "... fetch"))
    print(f"exec_capacity_open_cross report, run {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M}Z; "
          f"names {', '.join(syms)}")
    rec_days = sorted(d for d, r in days.items() if r["era"] == "recent")
    fit_days = sorted(d for d, r in days.items() if r["era"] == "fit")
    print(f"recent sessions {len(rec_days)} ({rec_days[0]}..{rec_days[-1]}); fit-period sample "
          f"{len(fit_days)} sessions (every {FIT_SAMPLE_EVERY}th, {fit_days[0] if fit_days else '-'}.."
          f"{fit_days[-1] if fit_days else '-'})")
    allA = pd.concat([Ar, fitA[fitA.date.isin(fit_days)]], ignore_index=True)
    X = cross_tables(days, allA, syms)
    fitX = fit_cross_all(fitA, syms)
    client = _client()
    from quantt.broker.alpaca import DATA_BASE
    cond = client._get(DATA_BASE, "/v2/stocks/meta/conditions/trade", {"tape": "A"})
    sec_what_the_print_is(X, fitX, cond, days)
    sec_cross_volume(X, bars)
    sec_live(client, a.state, X, dt.date.fromisoformat(rec_days[-1]), bars)
    B, res, Tn, H, R = sec_backtest(fitX, X)
    be = sec_breakeven(H, R)
    pc = prior_closes(days, Ar, fitA)
    sec_cost(days, X, pc, be)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("fetch", "report"):
        print(__doc__)
        return 2
    return fetch(argv[1:]) if argv[0] == "fetch" else report(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
