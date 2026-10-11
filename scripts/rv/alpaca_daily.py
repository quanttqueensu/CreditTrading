"""Read-only Alpaca daily bars and cash distributions: the leg that continues the ETF panels.

WHY THIS EXISTS (2026-10-11, results/cef/RESEARCH_PLAN_2026-10-09.md item 0.1)
-----------------------------------------------------------------------------
The ETF research panels (`data/rv/*.parquet`, `data/etf_daily.parquet`) were
staged from yfinance (and CRSP through 2024) by fetchers deleted in the
2026-09-28 clean slate and restored beside this module. The plan continues them
from Alpaca daily bars rather than Yahoo: Alpaca is the broker the book trades
through, its market-data API is documented and versioned, and Yahoo's history
has already moved under this desk once (an intraday last row and a revised
volume, `docs/REFERENCES.md` §8). Each restored fetcher therefore keeps its
ORIGINAL source for every date up to the panel's old last date (so the history
can be proved byte-identical to what was staged) and takes every later row
from here.

WHAT IT FETCHES, AND THE CONVENTION IT KEEPS
--------------------------------------------
  * `GET https://data.alpaca.markets/v2/stocks/bars`, `timeframe=1Day`,
    `feed=sip` (all US venues), `adjustment=raw`. RAW is chosen to match the
    old panels: their yfinance `history(auto_adjust=False)` Close is
    split-adjusted as of the fetch date but NOT dividend-adjusted, and between
    the start of the comparison window and today there is no split in any
    panel name (the corporate-actions query below proves that on every run and
    raises if one appears), so raw == split-adjusted over the whole window.
    Volume is SIP consolidated volume (Yahoo's is consolidated too: the median
    ratio on 2025-01-02..2026-07-29 was 1.000, measured 2026-10-11).
  * `GET https://data.alpaca.markets/v1/corporate-actions` for cash dividends,
    capital-gains distributions and splits. Cash dividends are the panels'
    `dividend` column, in dollars per share on the ex-date, at Alpaca's full
    precision. Yahoo publishes the same events rounded to 3 decimals (97% of
    the old panel's dividends equal their 3dp rounding); on 2025-01-02..
    2026-07-30 the two sources had identical ex-date sets for every name and
    differed by at most $0.00054/share (0.38bp of price) -- measured
    2026-10-11. Several records on one (symbol, ex_date) are summed: Alpaca
    books a December regular and supplemental distribution separately (CLOI
    2025-12-29: 0.2332 + 0.0349), Yahoo shows their sum.

Prices from here are exact decimals (79.27); the yfinance history is stored as
float32-rounded values (79.26999664306641). The difference is ~1e-7 relative
and is a representation, not a disagreement.

WHAT IT REFUSES (raises, naming the symbol and date; never a default)
--------------------------------------------------------------------
  * a daily bar not labelled at midnight New York time -- the convention the
    date mapping relies on [V: every one of 166,898 bars fetched 2026-10-11];
  * a session with no bar for a symbol, or a bar on a non-session (checked
    against Alpaca's own `/v2/calendar`);
  * a split (forward, reverse or unit) with an ex-date in the window: the
    yfinance history is split-adjusted as of ITS fetch, raw Alpaca bars are
    not, and one panel cannot hold two share bases;
  * a capital-gains distribution record: the old rv panels took yfinance
    `Dividends` only, and whether a separately-booked capital gain belongs in
    `dividend` is a convention a human decides, not this module (none exist
    for any panel name, 2015-06..2026-10, measured 2026-10-11);
  * two identical cash-dividend records (same symbol, ex-date and rate):
    Alpaca published one such pair (QQQ 2022-09-19, 0.51856 twice), and
    summing it would double a distribution;
  * a cash dividend whose ex-date has no bar.

THE CROSS-CHECK (`compare_legs`)
--------------------------------
Every row this module supplies is compared with an independent source before
a fetcher writes it: total return (and the high-low mid return for the OHLC
panels) computed in-house on both sides from each source's own close and
distribution, over a window that starts well before the splice. Gate: max
|difference| < 5bp per day, the `SPLICE_MAX_BP` the CRSP->yfinance splice in
`build_etf_daily.py` has always used; ex-date sets must be identical. The
first runs (2026-10-11, 2025-01-02..2026-10-09, 60 ETFs) passed with at most
2.82bp on total return (FPE) and 4.26bp on mid return (PGX), because Alpaca's
close and range can be sub-penny prints where Yahoo rounds to the cent; against
CRSP `ret` over 2024 the gap was at most 0.006bp. A failure raises; it is never
averaged and never silently resolved (CLAUDE.md).

READ-ONLY. The only network call is `AlpacaClient._get`, which issues GET and
nothing else (bounded retry, key-scrubbed errors). The client is reused for its
transport rather than given a `bars()` method because `quantt/` is the live
path and the live path never reads bars; a research fetcher must not change it.
Keys: the cef book's (`ALPACA_CEF_KEY_ID`/`_SECRET_KEY`) from the file named by
`QUANTT_ENV_FILE`, never printed.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")
DATA_BASE = "https://data.alpaca.markets"

FEED = "sip"
ADJUSTMENT = "raw"
BOOK = "cef"                 # whose paper key reads the market data; read-only
SPLICE_MAX_BP = 5.0          # same gate as build_etf_daily.py's CRSP->yfinance splice
BARS_LIMIT = 10000           # GET /v2/stocks/bars: limit max 10000 [V: reference]
CA_LIMIT = 1000              # GET /v1/corporate-actions: limit max 1000 [V: reference]
SYMBOLS_PER_REQUEST = 20
MAX_PAGES = 1000             # a pagination loop this long is a bug, not data
# Corporate actions are filtered by PROCESS date [V: reference], which trails the
# ex-date (max lag 47 days on 7,079 dividends, 2016-2026; never before it). The
# query therefore runs past `end` by this much, and the result is filtered on
# ex_date. A record not yet published is still missed -- Alpaca says it has
# "no guarantees on the creation time" -- which is what the cross-check against
# yfinance's ex-dates is for.
CA_PROCESS_LAG_DAYS = 120
SPLIT_TYPES = ("forward_splits", "reverse_splits", "unit_splits")
CA_TYPES = "cash_dividend,capital_gains_distribution,forward_split,reverse_split,unit_split"

COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume", "dividend"]


class AlpacaLegError(RuntimeError):
    """The Alpaca leg is incomplete, inconsistent, or disagrees with its check."""


def make_client():
    """The cef book's read-only client; keys from the file named by QUANTT_ENV_FILE."""
    from quantt.broker.alpaca import AlpacaClient
    return AlpacaClient.from_environment(BOOK)


def last_complete_date(now: dt.datetime | None = None) -> dt.date:
    """Yesterday in New York. The leg never asks for today's bar, so a run made
    during a session cannot write a partial day -- the defect that left an
    intraday 2026-07-29 row in the old `etf_ohlc.parquet` (staged 10:46 EDT)."""
    now = dt.datetime.now(NY) if now is None else now.astimezone(NY)
    return now.date() - dt.timedelta(days=1)


def _ny(d: dt.date, hh: int) -> str:
    """RFC-3339 for `d` at `hh`:00 New York time. Explicit timestamps, because a
    bare date as `end` reaches up to now and the Basic plan refuses SIP data
    younger than 15 minutes (results/ops/ALPACA_API_FACTS_2026-09-28.md §3)."""
    return dt.datetime(d.year, d.month, d.day, hh, tzinfo=NY).isoformat()


def _paged(client, path: str, params: dict, key: str):
    """Yield each page's `key` object, following next_page_token."""
    token = None
    for _ in range(MAX_PAGES):
        p = dict(params)
        if token:
            p["page_token"] = token
        body = client._get(DATA_BASE, path, p)
        if not isinstance(body, dict) or key not in body or "next_page_token" not in body:
            raise AlpacaLegError(f"GET {path}: response lacks {key!r} or next_page_token")
        yield body[key] or {}
        token = body["next_page_token"]
        if not token:
            return
    raise AlpacaLegError(f"GET {path}: more than {MAX_PAGES} pages")


def parse_bars(bars: dict, requested: set) -> list[dict]:
    """One page's `bars` object -> rows. Every bar must be stamped at NY midnight."""
    rows = []
    for sym, items in bars.items():
        if sym not in requested:
            raise AlpacaLegError(f"bars: symbol {sym!r} returned but not requested")
        for i, b in enumerate(items):
            missing = [f for f in ("t", "o", "h", "l", "c", "v") if f not in b or b[f] is None]
            if missing:
                raise AlpacaLegError(f"bars {sym}[{i}]: missing {missing}")
            ts = pd.Timestamp(b["t"])
            if ts.tzinfo is None:
                raise AlpacaLegError(f"bars {sym}[{i}]: timestamp {b['t']!r} has no offset")
            local = ts.tz_convert(NY)
            if (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0):
                raise AlpacaLegError(
                    f"bars {sym}[{i}]: daily bar stamped {b['t']} = {local} NY, not midnight; "
                    "the date mapping would be wrong")
            rows.append({"date": pd.Timestamp(local.date()), "ticker": sym,
                         "open": float(b["o"]), "high": float(b["h"]), "low": float(b["l"]),
                         "close": float(b["c"]), "volume": float(b["v"])})
    return rows


def fetch_bars(client, symbols, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Daily SIP bars, raw, for `symbols` on [start, end] (NY dates)."""
    symbols = sorted(set(symbols))
    rows = []
    for i in range(0, len(symbols), SYMBOLS_PER_REQUEST):
        chunk = symbols[i:i + SYMBOLS_PER_REQUEST]
        params = {"symbols": ",".join(chunk), "timeframe": "1Day", "feed": FEED,
                  "adjustment": ADJUSTMENT, "start": _ny(start, 0), "end": _ny(end, 20),
                  "limit": BARS_LIMIT, "sort": "asc"}
        for page in _paged(client, "/v2/stocks/bars", params, "bars"):
            rows.extend(parse_bars(page, set(chunk)))
    df = pd.DataFrame(rows, columns=COLUMNS[:-1])
    if df.empty:
        raise AlpacaLegError(f"bars: nothing returned for {symbols} on {start}..{end}")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    dup = df[df.duplicated(["ticker", "date"], keep=False)]
    if not dup.empty:
        raise AlpacaLegError(f"bars: duplicate (ticker, date): {dup[['ticker', 'date']].values.tolist()[:10]}")
    bad = df[(df[["open", "high", "low", "close"]] <= 0).any(axis=1) | (df["volume"] < 0)]
    if not bad.empty:
        raise AlpacaLegError(f"bars: non-positive price or negative volume: {bad.head().to_dict('records')}")
    absent = sorted(set(symbols) - set(df["ticker"]))
    if absent:
        raise AlpacaLegError(f"bars: no bars at all for {absent} on {start}..{end}")
    return df


def parse_corporate_actions(pages, start: dt.date, end: dt.date,
                            today: dt.date) -> pd.DataFrame:
    """Corporate-action pages -> cash dividends per (ticker, ex-date), summed.

    Raises on a split with ex-date in [start, today] (two share bases in one
    panel), on any capital-gains record in [start, end], and on duplicate
    identical dividend records. See the module docstring for why each refuses.
    """
    divs, splits, capg = [], [], []
    for page in pages:
        for typ, items in page.items():
            for x in items or []:
                if typ == "cash_dividends":
                    for f in ("symbol", "ex_date", "rate"):
                        if x.get(f) in (None, ""):
                            raise AlpacaLegError(f"cash_dividend record missing {f}: {x}")
                    divs.append((x["symbol"], x["ex_date"], float(x["rate"])))
                elif typ in SPLIT_TYPES:
                    # unit splits carry effective_date, the others ex_date [V: reference]
                    when = x.get("ex_date") or x.get("effective_date")
                    if not when:
                        raise AlpacaLegError(f"{typ} record with no ex_date/effective_date: {x}")
                    splits.append((typ, x.get("symbol") or x.get("old_symbol"), when))
                elif typ == "capital_gains_distributions":
                    if not x.get("ex_date"):
                        raise AlpacaLegError(f"capital_gains_distribution with no ex_date: {x}")
                    capg.append((x.get("symbol"), x["ex_date"]))
    s0, t1, e1 = start.isoformat(), today.isoformat(), end.isoformat()
    bad_splits = [s for s in splits if s0 <= s[2] <= t1]
    if bad_splits:
        raise AlpacaLegError(
            f"split(s) with ex-date in {s0}..{t1}: {bad_splits}. The yfinance history is "
            "split-adjusted as of its fetch and raw Alpaca bars are not; extend the splice "
            "before trusting either side.")
    bad_capg = [c for c in capg if s0 <= c[1] <= e1]
    if bad_capg:
        raise AlpacaLegError(
            f"capital-gains distribution record(s) {bad_capg}: whether they belong in "
            "`dividend` is undecided for these panels (module docstring); decide, then code it")
    inwin = [d for d in divs if s0 <= d[1] <= e1]
    dupes = [k for k, n in Counter(inwin).items() if n > 1]
    if dupes:
        raise AlpacaLegError(f"identical cash-dividend records (would double-count): {dupes}")
    df = pd.DataFrame(inwin, columns=["ticker", "ex_date", "rate"])
    if df.empty:
        return pd.DataFrame({"ticker": pd.Series(dtype=object),
                             "date": pd.Series(dtype="datetime64[ns]"),
                             "dividend": pd.Series(dtype=float)})
    df["date"] = pd.to_datetime(df["ex_date"])
    return (df.groupby(["ticker", "date"], as_index=False)["rate"].sum()
              .rename(columns={"rate": "dividend"}))


def fetch_dividends(client, symbols, start: dt.date, end: dt.date,
                    today: dt.date | None = None) -> pd.DataFrame:
    today = dt.datetime.now(NY).date() if today is None else today
    symbols = sorted(set(symbols))
    q_end = (max(end, today) + dt.timedelta(days=CA_PROCESS_LAG_DAYS)).isoformat()

    def pages():
        for i in range(0, len(symbols), SYMBOLS_PER_REQUEST):
            chunk = symbols[i:i + SYMBOLS_PER_REQUEST]
            params = {"symbols": ",".join(chunk), "types": CA_TYPES,
                      "start": start.isoformat(), "end": q_end, "limit": CA_LIMIT}
            yield from _paged(client, "/v1/corporate-actions", params, "corporate_actions")

    return parse_corporate_actions(pages(), start, end, today)


def sessions(client, start: dt.date, end: dt.date) -> list[pd.Timestamp]:
    return [pd.Timestamp(r["date"]) for r in client.calendar(start, end)]


def attach_dividends(bars: pd.DataFrame, divs: pd.DataFrame) -> pd.DataFrame:
    """Bars + dividend column. A non-ex-date row's 0.0 is a measured zero (no
    record exists), the same value yfinance carries on such days. An ex-date
    with no bar raises."""
    keys = set(zip(bars["ticker"], bars["date"]))
    orphan = [(t, d.date()) for t, d in zip(divs["ticker"], divs["date"]) if (t, d) not in keys]
    if orphan:
        raise AlpacaLegError(f"cash dividend ex-date with no bar: {orphan}")
    out = bars.merge(divs, on=["ticker", "date"], how="left")
    out["dividend"] = out["dividend"].where(out["dividend"].notna(), 0.0)
    return out[COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)


def check_sessions(frame: pd.DataFrame, cal: list[pd.Timestamp], start: dt.date,
                   end: dt.date, what: str) -> None:
    """Every symbol has a bar on every session in [start, end], and none elsewhere."""
    want = {d for d in cal if pd.Timestamp(start) <= d <= pd.Timestamp(end)}
    if not want:
        raise AlpacaLegError(f"{what}: Alpaca calendar has no session in {start}..{end}")
    for t, g in frame.groupby("ticker"):
        have = set(g.loc[(g["date"] >= pd.Timestamp(start)) & (g["date"] <= pd.Timestamp(end)), "date"])
        miss, extra = sorted(want - have), sorted(have - want)
        if miss or extra:
            raise AlpacaLegError(
                f"{what} {t}: sessions without a bar {[d.date() for d in miss][:10]}"
                f"{'...' if len(miss) > 10 else ''}; bars on non-sessions {[d.date() for d in extra][:10]}")


def leg(client, symbols, start: dt.date, end: dt.date | None = None,
        today: dt.date | None = None) -> pd.DataFrame:
    """Bars + dividends on [start, end] with full session coverage checked.
    `end` defaults to `last_complete_date()`."""
    end = last_complete_date() if end is None else end
    if end < start:
        raise AlpacaLegError(f"leg: end {end} is before start {start}")
    bars = fetch_bars(client, symbols, start, end)
    divs = fetch_dividends(client, symbols, start, end, today=today)
    frame = attach_dividends(bars, divs)
    check_sessions(frame, sessions(client, start, end), start, end, "alpaca bars")
    return frame


def inhouse_returns(frame: pd.DataFrame) -> pd.DataFrame:
    """Add ret_total = (close + dividend)/prev_close - 1, ret_px, mid_hl, ret_mid,
    each computed WITHIN `frame`'s own series per ticker (first row NaN).
    The house formula of every restored fetcher (stage_universe.total_return)."""
    f = frame.sort_values(["ticker", "date"]).copy()
    prev = f.groupby("ticker")["close"].shift(1)
    f["ret_total"] = (f["close"] + f["dividend"]) / prev - 1.0
    f["ret_px"] = f["close"] / prev - 1.0
    if {"high", "low"} <= set(f.columns):
        f["mid_hl"] = (f["high"] + f["low"]) / 2.0
        f["ret_mid"] = f["mid_hl"] / f.groupby("ticker")["mid_hl"].shift(1) - 1.0
    return f


def compare_legs(alp: pd.DataFrame, ref: pd.DataFrame, start: dt.date, end: dt.date,
                 cols=("ret_total",), max_bp: float = SPLICE_MAX_BP,
                 label: str = "alpaca vs yfinance") -> pd.DataFrame:
    """Per-ticker agreement of two sources on [start, end]; raises on any breach.

    Both frames carry [date, ticker, close, dividend, *cols], each col computed
    from that frame's own prices (never one source's return on the other's
    close). Dates are compared up to the earlier of the two sources' last
    dates; Alpaca rows past the reference's end are counted as unchecked.
    Returns the per-ticker statistics table for the build log.
    """
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out, problems = [], []
    for t in sorted(set(alp["ticker"])):
        a = alp[(alp.ticker == t) & (alp.date >= s) & (alp.date <= e)].set_index("date")
        r = ref[(ref.ticker == t) & (ref.date >= s) & (ref.date <= e)].set_index("date")
        if r.empty:
            problems.append(f"{t}: reference has no rows in {start}..{end}")
            continue
        last = min(a.index.max(), r.index.max())
        a_in, r_in = a[a.index <= last], r[r.index <= last]
        only_a, only_r = sorted(set(a_in.index) - set(r_in.index)), sorted(set(r_in.index) - set(a_in.index))
        if only_a or only_r:
            problems.append(f"{t}: calendar mismatch, alpaca-only {[d.date() for d in only_a][:5]}, "
                            f"reference-only {[d.date() for d in only_r][:5]}")
            continue
        ex_a = set(a_in.index[a_in["dividend"] > 0])
        ex_r = set(r_in.index[r_in["dividend"] > 0])
        if ex_a != ex_r:
            problems.append(f"{t}: ex-dates differ, alpaca-only {sorted(d.date() for d in ex_a - ex_r)}, "
                            f"reference-only {sorted(d.date() for d in ex_r - ex_a)}")
        row = {"ticker": t, "n": int(len(a_in)), "last_compared": last.date(),
               "unchecked_after": int((a.index > last).sum()), "n_ex": len(ex_a),
               "max_div_diff": float((a_in["dividend"] - r_in["dividend"]).abs().max())}
        for c in cols:
            d = ((a_in[c] - r_in[c]).abs() * 1e4).dropna()
            row[f"{c}_max_bp"] = float(d.max()) if len(d) else np.nan
            row[f"{c}_worst"] = d.idxmax().date() if len(d) else None
            if len(d) and d.max() >= max_bp:
                problems.append(f"{t}: {c} differs by {d.max():.2f}bp on {d.idxmax().date()} "
                                f"(gate {max_bp}bp)")
        out.append(row)
    if problems:
        raise AlpacaLegError(f"{label} on {start}..{end} failed:\n  " + "\n  ".join(problems))
    return pd.DataFrame(out)


def continue_after(yf_full: pd.DataFrame, seam: str, validate_from: str, *, ohlc: bool,
                   client=None, end: dt.date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The Alpaca rows that continue a yfinance panel past `seam`, and the check table.

    `yf_full` is the vendor history as fetched today, [date, ticker, close,
    dividend (+ high, low when `ohlc`)], NOT yet cut at the seam: its rows after
    the seam are the independent check on Alpaca's. Every ticker must have a
    yfinance row ON the seam date (the last row the panel keeps from Yahoo).

    Returns (rows, stats). `rows` holds every ticker's Alpaca bars strictly after
    the seam with ret_total / ret_px (and mid_hl / ret_mid) computed from
    ALPACA's own seam-day close and mid -- the convention the CRSP->yfinance
    splice in build_etf_daily.py set: the first spliced return accrues within the
    new source, so a half-cent difference between the vendors' seam closes
    never enters a return. (Recomputing that one row from the panel's own
    `close.shift(1)` can therefore differ from `ret_total` by up to the
    vendors' seam-close gap, < 3bp measured; every other row is exact.)
    """
    seam_ts = pd.Timestamp(seam)
    tickers = sorted(yf_full["ticker"].unique())
    no_seam = [t for t in tickers
               if not ((yf_full["ticker"] == t) & (yf_full["date"] == seam_ts)).any()]
    if no_seam:
        raise AlpacaLegError(f"yfinance has no row on the seam date {seam} for {no_seam}")
    client = make_client() if client is None else client
    end = last_complete_date() if end is None else end
    start = dt.date.fromisoformat(validate_from)
    if not start <= seam_ts.date():
        raise AlpacaLegError(f"validate_from {validate_from} must not be after the seam {seam}")
    a = inhouse_returns(leg(client, tickers, start, end))
    keep = ["date", "ticker", "close", "dividend"] + (["high", "low"] if ohlc else [])
    ref = inhouse_returns(yf_full[keep])
    stats = compare_legs(a, ref, start, end, ("ret_total", "ret_mid") if ohlc else ("ret_total",))
    return a[a["date"] > seam_ts].reset_index(drop=True), stats
