"""Read-only IBKR market data for the B10 feed: daily bars, an intraday quote capture, the market-data type.

WHY THIS EXISTS (team lead, 2026-11-25: "we can trade/interacti with ibrk quotes to run shadow
books / test ideas"; results/ops/IBKR_PAPER_MOVE_2026-11-25.md §5 B10). The desk's paper books
are moving to one IBKR paper account behind an IB Gateway on the VM. The shadow books may use
IBKR's prices, but the shadow user must never reach the Gateway's API port, because the Gateway
can send orders. So the trading user's read-only producer (quantt/twin/feed.py) asks the Gateway
through THIS module and writes plain files; the shadow side only reads them.

WHAT IT WILL NOT DO
  * Hold a trade client. `MarketReader` refuses any `IBKRClient` whose mode is not "read", and the
    read mode itself refuses `place_moc`, `cancel` and `global_cancel` (quantt/broker/ibkr.py).
    This module names no order method at all; quantt/twin/tests/test_feed.py reads its source.
  * Pay for data. Every quote request is `regulatorySnapshot=False` (a regulatory snapshot is
    charged per request [S: ib_async's own docstring, "may incur a fee"]); `reqTickers` is never
    used (it has no timeout: a snapshot whose end never arrives would hang the run).
  * Pass delayed off as live. ib_async writes a delayed tick (66 "Delayed Bid", 67, 68, 75 "Delayed
    Close"; IBKR's tick table [S: interactivebrokers.github.io/tws-api/tick_types.html, read
    2026-11-25]) into the same `bid`/`ask`/`last`/`close` fields as a live one, and `Ticker.marketDataType`
    defaults to 1 (live) when IBKR sends no type [V: ib_async 2.1.0 ticker.py and wrapper.py, read
    on this machine 2026-11-25]. So each value is labelled from the TICK TYPE that carried it,
    collected as the ticks arrive, and from the type IBKR reported for the request:
        delayed-numbered tick                      -> "delayed" ("delayed_frozen" if IBKR said 4)
        live-numbered tick, IBKR reported 2        -> "frozen"
        live-numbered tick, IBKR reported 1/none   -> "live" (IBKR confirms only a switch to a
                                                      NON-live type with a callback [S: market_data_type.html])
        live-numbered tick, IBKR reported 3 or 4   -> "unlabelled" (the two disagree; never "live")
  * Fill a gap. A symbol IBKR will not resolve, has no permission for, or answers with no bars is a
    `Gap` naming IBKR's error codes and words; nothing stands in for it.
  * Retry. A historical request is made once. A pacing violation (error 162 with "pacing violation"
    in its text [S: IBKR's error 162 wording as quoted in its pacing pages; not re-read]) or a lost
    Gateway connection (504 "Not connected", 1100 "Connectivity between IB and the TWS has been lost"
    [S: interactivebrokers.github.io/tws-api/message_codes.html, read 2026-11-25]) raises `FeedStop`,
    and the caller stops the run. Spacing (`Pacer`), not retrying, is how pacing is kept.

HISTORICAL BARS carry no market-data type: IBKR does not say whether a daily bar it serves this
account was built from delayed data. They are labelled "historical", never live or delayed, and
whether this paper account gets them at all without subscriptions is UNMEASURED until the first
read on the VM (contract §8 N4: paper gets "delayed data, as available" [V there]).

ERRORS are matched to a request by the CONTRACT ib_async passes with `errorEvent` (its symbol);
messages with no contract (reqId -1: data-farm status 2104, 2106, 2158 ...) are the Gateway's
and are kept apart. Every message is scrubbed of the account id before it is stored.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import math
import re
from typing import Callable

from quantt.broker.ibkr import IBKRClient, IBKRError, NotConnected, ReadOnlyClient, UnexpectedReply, to_ib_symbol

BAR_SIZE = "1 day"
WHAT_TO_SHOW = "TRADES"
USE_RTH = True
BAR_LABEL = "historical"

MARKET_DATA_TYPES = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed_frozen"}
LIVE_PRICE_TICKS = {1: "bid", 2: "ask", 4: "last", 9: "close"}
DELAYED_PRICE_TICKS = {66: "bid", 67: "ask", 68: "last", 75: "close"}
QUOTE_FIELDS = ("bid", "ask", "last", "close")
QUOTE_LABELS = frozenset({"live", "frozen", "delayed", "delayed_frozen", "unlabelled"})

PACING_CODE = 162
PACING_TEXT = "pacing violation"
LOST_CODES = frozenset({504, 1100})
_DURATION_RE = re.compile(r"^[1-9][0-9]{0,3} [DWMY]$")


class FeedStop(IBKRError):
    """The run must stop now; every symbol not yet asked is UNMEASURED with this reason."""


class PacingViolation(FeedStop):
    """IBKR said a request broke its pacing rules. Nothing more is asked this run."""


class GatewayLost(FeedStop):
    """The API session or the Gateway's link to IBKR dropped during the run."""


class Deadline(FeedStop):
    """The caller's deadline came while waiting for a request's turn; that request was not sent."""


@dataclasses.dataclass(frozen=True)
class IbMessage:
    req_id: int
    code: int
    text: str
    ib_symbol: str | None

    def to_dict(self) -> dict:
        return {"code": self.code, "text": self.text}


@dataclasses.dataclass(frozen=True)
class Gap:
    """One symbol IBKR did not measure, and why, in IBKR's own codes and words."""
    symbol: str
    what: str                  # "contract" | "bars" | "quote"
    reason: str
    messages: tuple = ()       # IbMessage

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "what": self.what, "reason": self.reason,
                "codes": sorted({m.code for m in self.messages}),
                "messages": [m.to_dict() for m in self.messages][:5]}


@dataclasses.dataclass(frozen=True)
class Bars:
    """One symbol's daily bars, oldest first, with whatever IBKR said about the request."""
    symbol: str
    rows: tuple
    messages: tuple = ()


class Pacer:
    """One request at a time, each at least `spacing_s` after the previous one began (monotonic)."""

    def __init__(self, spacing_s: float, *, monotonic: Callable[[], float], wait: Callable[[float], None]):
        if isinstance(spacing_s, bool) or not isinstance(spacing_s, (int, float)) or not spacing_s > 0:
            raise ValueError(f"spacing {spacing_s!r} must be a positive number of seconds")
        self.spacing_s = float(spacing_s)
        self._mono, self._wait = monotonic, wait
        self._last = None
        self.turns = 0

    def turn(self) -> None:
        if self._last is not None:
            gap = self._mono() - self._last
            if gap < self.spacing_s:
                self._wait(self.spacing_s - gap)
        self._last = self._mono()
        self.turns += 1


def _positive(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def quote_label(kind: str, reported) -> str:
    """The label of one quote value: `kind` is the tick's numbering ("live" or "delayed"), `reported`
    the type IBKR reported for the request (ib_async's Ticker.marketDataType). Module docstring."""
    if kind == "delayed":
        return "delayed_frozen" if reported == 4 else "delayed"
    if kind != "live":
        raise ValueError(f"tick kind {kind!r}")
    if reported == 2:
        return "frozen"
    if reported == 1:
        return "live"
    return "unlabelled"


class MarketReader:
    """Daily bars and quotes through ONE connected, read-mode `IBKRClient`. Use as a context manager:
    it listens to the library's error and tick events only while open.

    `wait(secs)` must run the library's event loop (the connected IB object's `sleep`), or no reply
    arrives while it waits; tests pass the stub's. `scrub` removes the account id from IBKR's text."""

    def __init__(self, client: IBKRClient, *, pacer: Pacer, request_timeout_s: float,
                 scrub: Callable[[str], str], wait: Callable[[float], None] | None = None,
                 utcnow: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc)):
        if not isinstance(client, IBKRClient):
            raise TypeError("client must be an IBKRClient")
        if client.mode != "read":
            raise ReadOnlyClient("market data is read through a READ client only; a trade client is never "
                                 "handed to the feed")
        if client.ib is None or not client.ib.isConnected():
            raise NotConnected("connect() the read client first")
        if isinstance(request_timeout_s, bool) or not isinstance(request_timeout_s, (int, float)) \
                or not request_timeout_s > 0:
            raise ValueError(f"request timeout {request_timeout_s!r} must be positive")
        self._c = client
        self._ib = client.ib
        self._pacer = pacer
        self._timeout = float(request_timeout_s)
        self._scrub = scrub
        self._wait = wait if wait is not None else self._ib.sleep
        self._utcnow = utcnow
        self.messages: list = []             # every IbMessage seen while open
        self._watch: dict = {}               # id(ticker) -> symbol, during one quote batch
        self._ticks: dict = {}               # symbol -> [(tickType, price)]
        self.requested_type = None
        self._open = False

    # ------------------------------------------------------------------ events

    def __enter__(self) -> "MarketReader":
        self._ib.errorEvent += self._on_error
        self._ib.pendingTickersEvent += self._on_tickers
        self._open = True
        return self

    def __exit__(self, *exc) -> bool:
        if self._open:
            self._ib.errorEvent -= self._on_error
            self._ib.pendingTickersEvent -= self._on_tickers
            self._open = False
        return False

    def _on_error(self, req_id, code, text, contract=None) -> None:
        sym = getattr(contract, "symbol", None) if contract is not None else None
        try:
            c = int(code)
        except (TypeError, ValueError):
            c = -1
        self.messages.append(IbMessage(int(req_id) if isinstance(req_id, int) else -1, c,
                                       self._scrub(str(text))[:300], str(sym) if sym else None))

    def _on_tickers(self, tickers) -> None:
        for t in tickers:
            sym = self._watch.get(id(t))
            if sym is None:
                continue
            for x in getattr(t, "ticks", None) or []:
                self._ticks.setdefault(sym, []).append((getattr(x, "tickType", None), getattr(x, "price", None)))

    def _since(self, mark: int, ib_symbol: str) -> tuple:
        new = self.messages[mark:]
        return tuple(m for m in new if m.ib_symbol == ib_symbol), tuple(m for m in new if m.ib_symbol is None)

    def _stop_if(self, symbol: str, mine: tuple, glob: tuple) -> None:
        for m in mine + glob:
            if m.code == PACING_CODE and PACING_TEXT in m.text.lower():
                raise PacingViolation(f"IBKR reported a pacing violation at {symbol} (error {m.code}: {m.text}); "
                                      "the run stops and nothing is retried")
        for m in glob + mine:
            if m.code in LOST_CODES:
                raise GatewayLost(f"the Gateway reported error {m.code} ({m.text}) at {symbol}; the run stops")
        if not self._ib.isConnected():
            raise GatewayLost(f"the API session dropped at {symbol}; the run stops")

    # -------------------------------------------------------------- requests

    def set_market_data_type(self, t: int) -> None:
        if isinstance(t, bool) or t not in MARKET_DATA_TYPES:
            raise ValueError(f"market data type {t!r} is not one of {sorted(MARKET_DATA_TYPES)}")
        self._ib.reqMarketDataType(t)
        self.requested_type = t

    def contract(self, symbol: str):
        """(qualified contract, None) or (None, Gap). One symbol at a time, so one bad name never
        refuses the rest (the client's `qualify` refuses a whole basket, rightly, before orders)."""
        try:
            ib_sym = to_ib_symbol(symbol)
        except ValueError:
            return None, Gap(symbol, "contract", "not a US equity symbol the IBKR client maps")
        mark = len(self.messages)
        try:
            con = self._c.qualify([symbol])[symbol]
        except UnexpectedReply:
            mine, glob = self._since(mark, ib_sym)
            self._stop_if(symbol, mine, glob)
            return None, Gap(symbol, "contract", "IBKR did not resolve it to exactly one US stock", mine)
        return con, None

    def daily_bars(self, symbol: str, duration: str, *, before: Callable[[], bool] = lambda: True) -> "Bars | Gap":
        """Daily TRADES bars, regular hours, ending now: `Bars`, or a `Gap` saying why not.

        `before()` is asked AFTER the pacing wait, just before the request goes: False raises
        `Deadline` and nothing is sent (the caller's stop time binds the request, not the wait)."""
        if not isinstance(duration, str) or not _DURATION_RE.match(duration):
            raise ValueError(f"duration {duration!r} is not IBKR's '<n> <D|W|M|Y>'")
        con, gap = self.contract(symbol)
        if gap is not None:
            return gap
        ib_sym = to_ib_symbol(symbol)
        self._pacer.turn()
        if not before():
            raise Deadline(f"the deadline came before {symbol}'s request could go")
        mark = len(self.messages)
        bars = self._ib.reqHistoricalData(con, endDateTime="", durationStr=duration, barSizeSetting=BAR_SIZE,
                                          whatToShow=WHAT_TO_SHOW, useRTH=USE_RTH, formatDate=1,
                                          keepUpToDate=False, timeout=self._timeout)
        mine, glob = self._since(mark, ib_sym)
        self._stop_if(symbol, mine, glob)
        if not bars:
            why = ("IBKR returned no bars" if mine else
                   f"IBKR returned no bars and no error within {self._timeout:g}s (a timed-out request is cancelled)")
            return Gap(symbol, "bars", why, mine)
        rows, seen = [], set()
        for b in bars:
            d = getattr(b, "date", None)
            if not isinstance(d, dt.date) or isinstance(d, dt.datetime):
                return Gap(symbol, "bars", f"a bar's date {d!r} is not a session date", mine)
            if d in seen:
                return Gap(symbol, "bars", f"two bars dated {d}", mine)
            seen.add(d)
            o, h, lo, c = (_positive(getattr(b, k, None)) for k in ("open", "high", "low", "close"))
            if None in (o, h, lo, c):
                return Gap(symbol, "bars", f"the bar of {d} has a missing or non-positive price", mine)
            if not (h >= max(o, c, lo) and lo <= min(o, c)):
                return Gap(symbol, "bars", f"the bar of {d} is not a bar (high {h}, low {lo})", mine)
            try:
                v = float(getattr(b, "volume", None))
            except (TypeError, ValueError):
                v = float("nan")
            if not (math.isfinite(v) and v >= 0):
                return Gap(symbol, "bars", f"the bar of {d} has volume {getattr(b, 'volume', None)!r}", mine)
            wap = _positive(getattr(b, "average", None))
            n = getattr(b, "barCount", None)
            rows.append({"symbol": symbol, "date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v,
                         "wap": wap, "bar_count": n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None})
        rows.sort(key=lambda r: r["date"])
        return Bars(symbol, tuple(rows), mine)

    def quotes(self, symbols: list, *, batch: int, stream_s: float, before: Callable[[], bool]) -> tuple:
        """([quote rows], [Gap]) for `symbols`, `batch` lines at a time, each batch streamed for
        `stream_s` and then cancelled. `before()` is asked before each batch; False stops (the caller's
        deadline), and the symbols not asked are returned as Gaps."""
        if self.requested_type is None:
            raise ValueError("set_market_data_type first: the request's type is part of every label")
        if isinstance(batch, bool) or not isinstance(batch, int) or not 0 < batch <= 90:
            raise ValueError(f"batch {batch!r} must be 1..90 lines")
        rows, gaps = [], []
        todo = list(symbols)
        while todo:
            chunk, todo = todo[:batch], todo[batch:]
            if not before():
                gaps += [Gap(s, "quote", "not asked: the run's deadline") for s in chunk + todo]
                break
            cons = {}
            for s in chunk:
                con, gap = self.contract(s)
                if gap is not None:
                    gaps.append(Gap(s, "quote", gap.reason, gap.messages))
                else:
                    cons[s] = con
            if not cons:
                continue
            self._pacer.turn()
            if not before():
                gaps += [Gap(s, "quote", "not asked: the run's deadline") for s in cons]
                gaps += [Gap(s, "quote", "not asked: the run's deadline") for s in todo]
                break
            mark = len(self.messages)
            self._watch, self._ticks = {}, {}
            subs = {}
            try:
                for s, con in cons.items():
                    t = self._ib.reqMktData(con, genericTickList="", snapshot=False, regulatorySnapshot=False)
                    subs[s] = t
                    self._watch[id(t)] = s
                self._wait(stream_s)
            finally:
                for s, t in subs.items():
                    self._ib.cancelMktData(cons[s])
                self._watch = {}
            at = self._utcnow()
            for s, t in subs.items():
                mine, glob = self._since(mark, to_ib_symbol(s))
                self._stop_if(s, mine, glob)
                row, gap = self._quote_row(s, t, self._ticks.get(s, []), mine, at, stream_s)
                if row is not None:
                    rows.append(row)
                if gap is not None:
                    gaps.append(gap)
        return rows, gaps

    def _quote_row(self, symbol, ticker, ticks, mine, at, stream_s) -> tuple:
        reported = getattr(ticker, "marketDataType", None)
        got: dict = {}
        for tt, price in ticks:
            if tt in LIVE_PRICE_TICKS:
                f, kind = LIVE_PRICE_TICKS[tt], "live"
            elif tt in DELAYED_PRICE_TICKS:
                f, kind = DELAYED_PRICE_TICKS[tt], "delayed"
            else:
                continue
            p = _positive(price)
            if p is None:                 # IBKR's "no price" (-1) or ib_async's empty value
                continue
            got[f] = (p, tt, kind)        # the last tick of a field wins
        if not got:
            why = (f"no price tick within {stream_s:g}s" + ("" if mine else " and no error"))
            return None, Gap(symbol, "quote", why, mine)
        row = {"symbol": symbol, "captured_utc": at.isoformat(), "requested_market_data_type": self.requested_type,
               "reported_market_data_type": reported if isinstance(reported, int) else None}
        for f in QUOTE_FIELDS:
            if f in got:
                p, tt, kind = got[f]
                row[f], row[f + "_type"], row[f + "_tick"] = p, quote_label(kind, reported), tt
            else:
                row[f], row[f + "_type"], row[f + "_tick"] = None, None, None
        row["codes"] = " ".join(str(c) for c in sorted({m.code for m in mine}))
        return row, None
