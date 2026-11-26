"""Test doubles for B10 (the IBKR market-data feed): a fake clock, and the twin's stub `ib_async` extended
with the market-data calls the feed makes. NO SOCKET, NO LIBRARY (quantt/twin/tests/fakes.py; root
conftest.py). Every IBKR message text below is a STUB string written for these tests in the shape of
IBKR's; none is a claim about what IBKR sends this account (that is measured on the VM)."""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import types
from pathlib import Path

from quantt.twin.tests import fakes as F

PACING_STUB = "Historical Market Data Service error message:API historical data query cancelled: pacing violation (stub)"
NO_PERMISSION_STUB = "Historical Market Data Service error message:No market data permissions for NYSE STK (stub)"
NOT_SUBSCRIBED_STUB = "Requested market data is not subscribed (stub)"


class Clock:
    """Monotonic seconds and a wall clock that move only when something waits."""

    def __init__(self, start: dt.datetime):
        if start.tzinfo is None:
            raise ValueError("start must be aware")
        self.start, self.t = start, 0.0
        self.alarms = []                         # every alarm(seconds) the run armed; 0 clears

    def monotonic(self) -> float:
        return self.t

    def utcnow(self) -> dt.datetime:
        return (self.start + dt.timedelta(seconds=self.t)).astimezone(dt.timezone.utc)

    def advance(self, s: float) -> None:
        self.t += float(s)


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self

    def __isub__(self, h):
        self.handlers.remove(h)
        return self

    def emit(self, *a):
        for h in list(self.handlers):
            h(*a)


class _Ticker:
    """ib_async's Ticker as far as the feed reads it: marketDataType defaults to 1, as the library's does."""

    def __init__(self, contract):
        self.contract = contract
        self.ticks = []
        self.marketDataType = 1


class MarketWorld:
    """What the Gateway serves, by IBKR symbol."""

    def __init__(self):
        self.bars: dict = {}            # symbol -> [(date, o, h, l, c, v)]
        self.hist_errors: dict = {}     # symbol -> [(code, text)]
        self.pacing_on: set = set()     # symbols whose request is answered with a pacing violation
        self.unknown: set = set()       # symbols IBKR cannot resolve (error 200)
        self.ticks: dict = {}           # symbol -> [(tickType, price)]
        self.reported: dict = {}        # symbol -> the marketDataType IBKR reports (absent: none sent)
        self.quote_errors: dict = {}    # symbol -> [(code, text)]
        self.global_msgs: list = []     # (code, text) with no request, at connect
        self.hist_calls: list = []      # (clock seconds, symbol, request)
        self.mkt_calls: list = []       # (symbol, snapshot, regulatorySnapshot)
        self.cancels: list = []
        self.market_types: list = []
        self.latency = 0.5


def market_module(world: F.World, mw: MarketWorld, clock: Clock):
    """fakes.stub_module(world), its IB extended with reqHistoricalData, reqMktData, cancelMktData,
    reqMarketDataType, the error and ticker events, and a `sleep` that moves the clock and delivers ticks."""
    m = F.stub_module(world)
    Base = m.IB

    class IB(Base):
        def __init__(self):
            super().__init__()
            self.errorEvent = Event()
            self.pendingTickersEvent = Event()
            self._pending = []
            self._rid = 0

        def _next(self):
            self._rid += 1
            return self._rid

        def sleep(self, secs=0.02):
            clock.advance(secs)
            if self._pending:
                batch, self._pending = self._pending, []
                for t, ticks, reported in batch:
                    t.ticks = [types.SimpleNamespace(tickType=tt, price=p, size=1.0) for tt, p in ticks]
                    if reported is not None:
                        t.marketDataType = reported
                self.pendingTickersEvent.emit({b[0] for b in batch})
                for t, _, _ in batch:
                    t.ticks = []            # ib_async clears ticks at the next arrival
            return True

        def connect(self, *a, **kw):
            super().connect(*a, **kw)
            for code, text in mw.global_msgs:
                self.errorEvent.emit(-1, code, text, None)

        def reqContractDetails(self, con):
            # the client's `qualify` reads contract details (review of the twin, finding 3)
            if con.symbol in mw.unknown:
                self.errorEvent.emit(self._next(), 200, "No security definition has been found for the request", con)
                return []
            return super().reqContractDetails(con)

        def reqHistoricalData(self, contract, endDateTime, durationStr, barSizeSetting, whatToShow, useRTH,
                              formatDate=1, keepUpToDate=False, chartOptions=(), timeout=60):
            sym = contract.symbol
            mw.hist_calls.append((clock.t, sym, {"end": endDateTime, "duration": durationStr, "bar": barSizeSetting,
                                                 "what": whatToShow, "rth": useRTH, "keep": keepUpToDate,
                                                 "format": formatDate, "timeout": timeout}))
            clock.advance(mw.latency)
            rid = self._next()
            for code, text in mw.hist_errors.get(sym, []):
                self.errorEvent.emit(rid, code, text, contract)
            if sym in mw.pacing_on:
                self.errorEvent.emit(rid, 162, PACING_STUB, contract)
                return []
            return [types.SimpleNamespace(date=d, open=o, high=h, low=lo, close=c, volume=v, average=c, barCount=7)
                    for d, o, h, lo, c, v in mw.bars.get(sym, [])]

        def reqMarketDataType(self, t):
            mw.market_types.append(t)

        def reqMktData(self, contract, genericTickList="", snapshot=False, regulatorySnapshot=False,
                       mktDataOptions=None):
            mw.mkt_calls.append((contract.symbol, snapshot, regulatorySnapshot))
            t = _Ticker(contract)
            rid = self._next()
            for code, text in mw.quote_errors.get(contract.symbol, []):
                self.errorEvent.emit(rid, code, text, contract)
            if contract.symbol in mw.ticks:
                self._pending.append((t, mw.ticks[contract.symbol], mw.reported.get(contract.symbol)))
            return t

        def cancelMktData(self, contract):
            mw.cancels.append(contract.symbol)
            return True

    m.IB = IB
    return m


def bars_for(last: dt.date, n: int = 3, px: float = 10.0) -> list:
    """`n` daily bars ending `last` (weekdays only), each a sane OHLCV."""
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5 and d != dt.date(2026, 11, 26):
            out.append((d, px, px * 1.01, px * 0.99, px * 1.002, 1000.0))
        d -= dt.timedelta(days=1)
    return sorted(out)


def make_feed_dir(tmp_path: Path) -> Path:
    """A feed directory shaped as the installer makes it: setgid 2750, of a group this user is in, with
    requests/ inside (0750 here; on the VM it belongs to the shadow user)."""
    feed = tmp_path / "srv" / "quantt-ibkr-feed"
    feed.mkdir(parents=True)
    os.chown(feed, -1, os.getgid())
    os.chmod(feed, 0o2750)
    req = feed / "requests"
    req.mkdir()
    os.chmod(req, 0o750)
    return feed


def write_book_plan(state: Path, book: str, day: dt.date, symbols: list) -> Path:
    d = state / day.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    p = d / "plan.json"
    p.write_text(json.dumps({"book": book, "session_date": day.isoformat(),
                             "targets": {s: {"target": 0, "current": 0} for s in symbols}}))
    return p


def feed_setup(tmp_path: Path, start: dt.datetime, books: dict | None = None):
    """(states, feed, env, world, mw, clock). `books` is {book: [symbols]} for each book's latest plan."""
    states = F.make_states(tmp_path)
    books = books if books is not None else {"cef": ["PDI", "PTY"], "c4": ["EVV"], "events": ["PDI", "SPY"]}
    for b, syms in books.items():
        write_book_plan(states[b], b, start.date(), syms)
    feed = make_feed_dir(tmp_path)
    env = F.env_for(states)
    return states, feed, env, F.World(), MarketWorld(), Clock(start)


def feed_deps(states, feed, env, world, mw, clock, *, mode="read", lock=None, settings=None, producer_uid=None):
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    from quantt.twin import config
    from quantt.twin.feed import FeedDeps, load_settings
    cfg = IBKRConfig(host="127.0.0.1", port=4002, client_id=34, account=F.ACCOUNT)
    mod = market_module(world, mw, clock)
    lock = lock if lock is not None else config.gateway_lock_path(states["twin"])
    return FeedDeps(env=env, state=states["twin"], feed=feed, market=F.FakeMarket(clock.utcnow(), F.nov_calendar()),
                    read_client=lambda: IBKRClient(cfg, mode=mode, ib_module=mod, sleep=lambda s: None,
                                                   session_lock=lock, lock_wait_s=0.0),
                    alarm=clock.alarms.append, utcnow=clock.utcnow, monotonic=clock.monotonic, wait=None, out=io.StringIO(),
                    settings=settings or load_settings(),
                    producer_uid=os.getuid() + 1 if producer_uid is None else producer_uid)
