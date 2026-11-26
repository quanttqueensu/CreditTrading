"""Test doubles for the twin: a stub `ib_async` module over one simulated paper account, a fake
Alpaca market-data object, and builders for the books' saved plans. NO SOCKET, NO LIBRARY: the
stub stands in for `ib_async` (passed as `ib_module`), so the real one is never imported here, and
the root conftest's netguard refuses any connection a test might still try. Account ids below are
made-up strings in the paper shape, never a real account's."""
from __future__ import annotations

import datetime as dt
import enum
import json
import types
from pathlib import Path

from quantt.session.gate import ET

ACCOUNT = "DU0000001"            # a made-up paper-shaped id; never a real account


class _Status:
    def __init__(self, status):
        self.status = status


class StartupFetch(enum.Flag):
    """ib_async 2.1.0's StartupFetch members, by name (pinned against the library by a test)."""
    POSITIONS = enum.auto()
    ORDERS_OPEN = enum.auto()
    ORDERS_COMPLETE = enum.auto()
    ACCOUNT_UPDATES = enum.auto()
    SUB_ACCOUNT_UPDATES = enum.auto()
    EXECUTIONS = enum.auto()


class _Log:
    def __init__(self, message, code):
        self.message, self.errorCode = message, code


class _Later:
    """A status that reads `first` `after` times, then `then` (ib_async: PreSubmitted -> ValidationError ->
    Submitted when the warning can be ignored)."""

    def __init__(self, first, then, after):
        self._first, self._then, self._left = first, then, after

    @property
    def status(self):
        if self._left > 0:
            self._left -= 1
            return self._first
        return self._then

    def peek(self):
        return self._first if self._left > 0 else self._then


_DONE = frozenset({"Filled", "Cancelled", "ApiCancelled", "Inactive"})     # ib_async OrderStatus.DoneStates


def _current(t) -> str:
    st = t.orderStatus
    return st.peek() if isinstance(st, _Later) else st.status


class _Trade:
    def __init__(self, contract, order, status):
        self.contract, self.order = contract, order
        self.orderStatus = _Status(status)
        self.log = []


class World:
    """One paper account as the Gateway would show it. Several IB() connections share it."""

    def __init__(self):
        self.accounts = [ACCOUNT]
        self.reachable = True
        self.positions: dict = {}
        self.open: list = []            # _Trade objects resting
        self.blind_all_open = False     # reqAllOpenOrders misses another client's orders
        self.executions: list = []
        self.placed: list = []          # (client_id, symbol, order)
        self.cancelled = 0
        self.global_cancels = 0
        self.reject = set()             # symbols whose order the Gateway rejects
        self.silent = set()             # symbols whose order is never acknowledged
        self.nlv, self.bp, self.base = 1_000_000.0, 4_000_000.0, "USD"
        self.usd_rate = None            # base per USD, for a non-USD base (accountValues)
        self.ledger = None              # {currency: (ExchangeRate, NetLiquidationByCurrency)} incl. "BASE"
        self.fx_bars = None             # [(date, close)] for USD<base> MIDPOINT daily bars; None: no contract
        self.fx_requests = 0
        self.fx_timeout = None          # the timeout the bar request was given
        self.fx_raise = None            # an exception the bar request raises
        self.requery_error = None       # an exception reqAllOpenOrders raises (set mid-batch by a hook)
        self.connections: list = []
        self.before_place = None        # hook: called before each placeOrder
        self.next_order_id = 100
        self.unknown_symbols = set()    # symbols reqContractDetails cannot resolve
        self.next_perm = 9000
        self.sync_error = None          # e.g. "positions request timed out": the connect's initial sync fails
        self.connect_kwargs: list = []  # what each connect asked of ib_async
        self.warn = {}                  # symbol -> (warning code, "absent" | "open" | a later status)

    def fill_all_at(self, prices: dict, when: dt.datetime) -> None:
        """The close: every resting MOC fills in full at `prices`, as IBKR paper did in September."""
        for t in list(self.open):
            o = t.order
            sym = t.contract.symbol
            q = o.totalQuantity if o.action == "BUY" else -o.totalQuantity
            self.positions[sym] = self.positions.get(sym, 0) + q
            if self.positions[sym] == 0:
                del self.positions[sym]
            n = len(self.executions) + 1
            ex = types.SimpleNamespace(execId=f"E{n}", side="BOT" if o.action == "BUY" else "SLD",
                                       shares=float(o.totalQuantity), price=prices[sym], permId=o.permId,
                                       orderId=o.orderId, clientId=o.clientId, orderRef=o.orderRef,
                                       acctNumber=ACCOUNT, time=when)
            cr = types.SimpleNamespace(execId=f"E{n}", commission=0.35, currency="USD")
            self.executions.append(types.SimpleNamespace(
                execution=ex, contract=types.SimpleNamespace(symbol=sym, localSymbol=sym, secType="STK",
                                                             currency="USD"),
                commissionReport=cr, time=when))
            t.orderStatus.status = "Filled"
        self.open = []


def stub_module(world: World):
    """A module-shaped stub of ib_async over `world`."""

    class Stock:
        def __init__(self, symbol, exchange, currency):
            self.symbol, self.exchange, self.currency, self.secType = symbol, exchange, currency, "STK"
            self.localSymbol, self.conId = symbol, 0

    class Order:
        def __init__(self):
            self.action = self.orderType = self.tif = self.orderRef = self.account = ""
            self.totalQuantity = 0
            self.transmit = True
            self.orderId = self.permId = self.clientId = 0

    class ExecutionFilter:
        def __init__(self, acctCode="", time=""):
            self.acctCode, self.time = acctCode, time

    class IB:
        def __init__(self):
            self.client_id = None
            self.readonly = None
            self._up = False
            self._trades = []           # this connection's LOCAL cache (ib_async wrapper.trades)

        @staticmethod
        def sleep(secs=0.02):
            return True

        def connect(self, host, port, clientId, timeout=4, readonly=False, account="", raiseSyncErrors=False,
                    fetchFields=None):
            world.connect_kwargs.append({"readonly": readonly, "raiseSyncErrors": raiseSyncErrors,
                                         "fetchFields": fetchFields})
            if not world.reachable:
                raise ConnectionRefusedError("stub: nothing listening")
            if world.sync_error:
                # ib_async 2.1.0: a failed initial sync is only logged unless raiseSyncErrors is True
                if raiseSyncErrors:
                    raise ConnectionError([world.sync_error])
                world.positions = {}                         # what the cache would hold: nothing
            self.client_id, self.readonly, self._up = clientId, readonly, True
            world.connections.append(self)

        def isConnected(self):
            return self._up

        def disconnect(self):
            self._up = False

        def managedAccounts(self):
            return list(world.accounts)

        def accountSummary(self, account=""):
            rows = [types.SimpleNamespace(account=ACCOUNT, tag="NetLiquidation", value=str(world.nlv), currency=world.base),
                    types.SimpleNamespace(account=ACCOUNT, tag="BuyingPower", value=str(world.bp), currency=world.base)]
            for cur, (rate, nlv) in (world.ledger or {}).items():      # the $LEDGER:ALL rows
                rows.append(types.SimpleNamespace(account=ACCOUNT, tag="ExchangeRate", value=str(rate), currency=cur))
                rows.append(types.SimpleNamespace(account=ACCOUNT, tag="NetLiquidationByCurrency", value=str(nlv),
                                                  currency=cur))
            return rows

        def accountValues(self, account=""):
            if world.usd_rate is None:
                return []
            return [types.SimpleNamespace(account=ACCOUNT, tag="ExchangeRate", value=str(world.usd_rate), currency="USD")]

        def positions(self, account=""):
            return [types.SimpleNamespace(account=ACCOUNT, position=float(q),
                                          contract=types.SimpleNamespace(symbol=s, localSymbol=s, secType="STK",
                                                                         currency="USD"))
                    for s, q in world.positions.items()]

        def reqAllOpenOrders(self):
            if world.requery_error is not None:
                raise world.requery_error
            if world.blind_all_open:
                return [t for t in world.open if t.order.clientId == self.client_id]
            return list(world.open)

        def openTrades(self):
            # ib_async 2.1.0 ib.py: every trade in the LOCAL cache whose status is not a DoneState,
            # including an order this client just placed and IBKR never took (release check, 300b884).
            # The Gateway's own answer is reqAllOpenOrders (world.open).
            return [t for t in self._trades if _current(t) not in _DONE]

        def reqExecutions(self, flt=None):
            return list(world.executions)

        def reqCurrentTime(self):
            return dt.datetime.now(dt.timezone.utc)

        def reqContractDetails(self, con):
            if getattr(con, "secType", "STK") == "CASH":
                if world.fx_bars is None:
                    return []
                con.conId = 15016062                  # any id: the stub's own
                return [types.SimpleNamespace(contract=con)]
            if con.symbol in world.unknown_symbols:
                return []
            con.conId = abs(hash(con.symbol)) % 100000 + 1
            return [types.SimpleNamespace(contract=con)]

        def reqHistoricalData(self, con, endDateTime, durationStr, barSizeSetting, whatToShow, useRTH,
                              formatDate=1, keepUpToDate=False, chartOptions=(), timeout=60):
            assert getattr(con, "secType", "") == "CASH" and whatToShow == "MIDPOINT" and barSizeSetting == "1 day"
            world.fx_requests += 1
            world.fx_timeout = timeout
            if world.fx_raise is not None:
                raise world.fx_raise
            return [types.SimpleNamespace(date=d, close=c) for d, c in (world.fx_bars or [])]

        def placeOrder(self, con, order):
            if self.readonly:
                raise AssertionError("stub: placeOrder on a read-only connection")
            if world.before_place:
                world.before_place(con, order)
            order.clientId = self.client_id
            order.orderId = world.next_order_id
            world.next_order_id += 1
            order.permId = world.next_perm
            world.next_perm += 1
            world.placed.append((self.client_id, con.symbol, order))
            t = self._place(con, order)
            self._trades.append(t)               # ib_async caches the trade before the Gateway replies
            return t

        def _place(self, con, order):
            if con.symbol in world.reject:
                return _Trade(con, order, "Inactive")
            if con.symbol in world.silent:
                return _Trade(con, order, "PendingSubmit")
            if con.symbol in world.warn:
                # ib_async on a warning code: status ValidationError, the trade kept, a log line with the code
                code, then = world.warn[con.symbol]
                t = _Trade(con, order, "ValidationError")
                t.log.append(_Log(f"Warning {code}, reqId {order.orderId}: held while IBKR locates shares", code))
                if then == "absent":
                    return t
                if then != "open":
                    # not yet among the open orders when first asked; its own status moves on later
                    t.orderStatus = _Later("ValidationError", then, after=3)
                    return t
                world.open.append(t)
                return t
            t = _Trade(con, order, "PreSubmitted")
            world.open.append(t)
            return t

        def cancelOrder(self, order):
            world.cancelled += 1
            return None

        def reqGlobalCancel(self):
            world.global_cancels += 1
            world.open = []

    m = types.ModuleType("ib_async_stub")
    m.IB, m.Stock, m.Order, m.ExecutionFilter = IB, Stock, Order, ExecutionFilter

    class Forex:
        def __init__(self, pair="", exchange="IDEALPRO"):
            self.secType, self.symbol, self.currency, self.exchange, self.conId = "CASH", pair[:3], pair[3:], exchange, 0
    m.Forex = Forex
    m.StartupFetch = StartupFetch
    return m


class FakeMarket:
    """Alpaca's clock, calendar, corporate actions and closing prints, from fixed tables."""

    def __init__(self, now: dt.datetime, calendar_rows: list, prints: dict | None = None,
                 daily: dict | None = None, ca_events: list | None = None):
        self.now = now
        self.rows = calendar_rows
        self.prints = prints or {}
        self.daily = daily or {}
        self.ca_events = ca_events or []
        self.ca_calls = 0

    def clock(self):
        n = self.now.astimezone(ET)
        close = next((dt.datetime.combine(r["date"], dt.time(*map(int, r["close"].split(":"))), tzinfo=ET)
                      for r in self.rows if r["date"] == n.date()), None)
        is_open = close is not None and dt.datetime.combine(n.date(), dt.time(9, 30), tzinfo=ET) <= n < close
        before_open = close is not None and n < dt.datetime.combine(n.date(), dt.time(9, 30), tzinfo=ET)
        nxt = n.date() if before_open else min((r["date"] for r in self.rows if r["date"] > n.date()),
                                               default=n.date() + dt.timedelta(days=3))
        return {"timestamp": self.now, "is_open": is_open,
                "next_open": dt.datetime.combine(nxt, dt.time(9, 30), tzinfo=ET),
                "next_close": dt.datetime.combine(nxt, dt.time(16, 0), tzinfo=ET)}

    def calendar(self, start, end):
        return [r for r in self.rows if start <= r["date"] <= end]

    def corporate_actions(self, symbols, start, end, **kw):
        self.ca_calls += 1
        return list(self.ca_events)

    def official_closes(self, symbols, day):
        from quantt.session.score import AuctionPrints
        p = {s: self.prints[s] for s in symbols if s in self.prints}
        g = {s: "stub: no print" for s in symbols if s not in self.prints}
        return AuctionPrints(prices=p, gaps=g)

    def daily_closes(self, symbols, day, utcnow):
        return {s: self.daily[s] for s in symbols if s in self.daily}


def nov_calendar() -> list:
    """Alpaca's calendar rows around Thanksgiving 2026 (Thursday 26 Nov closed; Friday 27 Nov closes at
    13:00). Written from the NYSE's published holiday schedule's shape; the repo's nyse_calendar must
    agree on which days trade, which is what the tests check."""
    rows = []
    d = dt.date(2026, 11, 9)
    while d <= dt.date(2026, 12, 4):
        if d.weekday() < 5 and d != dt.date(2026, 11, 26):
            rows.append({"date": d, "open": "09:30", "close": "13:00" if d == dt.date(2026, 11, 27) else "16:00"})
        d += dt.timedelta(days=1)
    return rows


def et(y, mo, d, h, mi=0, s=0) -> dt.datetime:
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=ET)


# ------------------------------------------------------------------ the books' plans

def write_core_plan(state: Path, book: str, F: dt.date, asof: dt.date, targets: dict, current: dict,
                    closes: dict, *, status: str = "decided") -> dict:
    """A late-market plan.json the core's own `load_decided_plan` accepts."""
    from quantt.session import decide as dec
    from quantt.session import records as rec
    orders = []
    for s in sorted(targets):
        d = targets[s] - current.get(s, 0)
        if d:
            orders.append(dec.Order(s, "buy" if d > 0 else "sell", abs(d), 1,
                                    dec.client_order_id(book, F, s, 1), current.get(s, 0), targets[s],
                                    closes[s], "test", "day"))
    orders = dec.transmit_sequence(orders)
    plan = {"book": book, "spec_id": "test", "session_date": F.isoformat(), "asof": asof.isoformat(),
            "equity": 100000.0, "execution": "late_market", "status": status,
            "plan_sha": dec.plan_sha(orders), "orders": [o.to_dict() for o in orders],
            "targets": {s: {"current": current.get(s, 0), "target": q, "kind": "qty", "reason": "test"}
                        for s, q in targets.items()},
            "notes": {}, "closes": closes, "refusals": []}
    day = rec.day_dir(state, F)
    rec.write_json_atomic(day / "plan.json", plan)
    return plan


def write_events_plan(state: Path, F: dt.date, asof: dt.date, sleeves: dict, current: dict, closes: dict,
                      *, break_sum: str | None = None) -> dict:
    """An events plan.json the events runner's own `load_plan` accepts (record_sha included).
    `sleeves` is {slug: {symbol: shares}}; `break_sum` makes the book's target for one symbol
    disagree with its sleeves (the refusal case)."""
    from quantt.session import decide as dec
    from quantt.session import records as rec
    from quantt.sleeves.run import _record_sha, ledger_sha
    from quantt.sleeves import ledger as L
    net = {}
    for tg in sleeves.values():
        for s, q in tg.items():
            net[s] = net.get(s, 0) + q
    net = {s: q for s, q in sorted(net.items()) if q}
    book_t = dict(net)
    if break_sum:
        book_t[break_sum] = book_t.get(break_sum, 0) + 1
    syms = sorted(set(book_t) | set(current))
    orders = []
    for s in syms:
        d = book_t.get(s, 0) - current.get(s, 0)
        if d:
            orders.append(dec.Order(s, "buy" if d > 0 else "sell", abs(d), 1, dec.client_order_id("events", F, s, 1),
                                    current.get(s, 0), book_t.get(s, 0), closes[s], "test", "day"))
    orders = dec.transmit_sequence(orders)
    plan = {"book": "events", "execution": "late_market", "status": "decided", "session_date": F.isoformat(),
            "asof": asof.isoformat(), "equity": 1000000.0, "positions": current, "closes": closes,
            "stale_closes": {}, "ledger_sha": ledger_sha(L.empty()),
            "sleeves": [{"slug": k, "action": "decided", "why": "", "targets": v, "stale_sessions": 0,
                         "dropped": [], "scale": {}, "capital_usd": 25000.0,
                         "decision": {"sha256": "x" * 64, "written_at": "t"}} for k, v in sleeves.items()],
            "net_targets": net,
            "targets": {s: {"current": current.get(s, 0), "target": book_t.get(s, 0), "kind": "qty", "reason": "t"}
                        for s in syms},
            "notes": {}, "orders": [o.to_dict() for o in orders], "plan_sha": dec.plan_sha(orders)}
    plan = json.loads(json.dumps(plan))
    plan["record_sha"] = _record_sha(plan)
    day = rec.day_dir(state, F)
    rec.write_json_atomic(day / "plan.json", plan)
    return plan


REPO = Path(__file__).resolve().parents[3]
UNIT_ENV = {"quantt-cef-session.service": "DRY_RUN=0 QUANTT_STATE_DIR=/x",
            "quantt-c4-session.service": "DRY_RUN=0 QUANTT_STATE_DIR=/y",
            "quantt-events-send.service": "DRY_RUN=0 QUANTT_STATE_DIR=/z"}


def make_states(tmp_path: Path) -> dict:
    """State directories for the three books (each ARMED by its own AUTO_ARMED) and the twin, the
    twin's own clone (an empty ops/) and a copy of the books' clone's book files (read-only to the
    twin; tests write HALT files into either)."""
    import shutil
    out = {}
    for b in ("cef", "c4", "events", "twin"):
        p = tmp_path / "quantt_state" / b
        p.mkdir(parents=True)
        out[b] = p
        if b != "twin":
            (p / "AUTO_ARMED").write_text("")
    own = tmp_path / "own_clone"
    (own / "ops").mkdir(parents=True)
    bc = tmp_path / "books_clone"
    for f in ("ops/sleeves/events_sleeves.json", "ops/books/cef_discount_book.json", "ops/books/c4_families_book.json"):
        (bc / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / f, bc / f)
    out["own_clone"], out["books_clone"] = own, bc
    return out


def env_for(states: dict, **extra) -> dict:
    env = {"QUANTT_TWIN_CEF_STATE": str(states["cef"]), "QUANTT_TWIN_C4_STATE": str(states["c4"]),
           "QUANTT_TWIN_EVENTS_STATE": str(states["events"]), "DRY_RUN": "1",
           "QUANTT_BOOKS_CLONE": str(states["books_clone"])}
    env.update(extra)
    return env


def deps_for(states, world, market, env, *, out=None, utcnow=None):
    import io
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    from quantt.twin.run import Deps
    cfg = IBKRConfig(host="127.0.0.1", port=4002, client_id=31, account=ACCOUNT)
    mod = stub_module(world)
    return Deps(env=env, state=states["twin"], market=market,
                ibkr=lambda mode: IBKRClient(cfg, mode=mode, ib_module=mod, sleep=lambda s: None),
                utcnow=utcnow or (lambda: market.now.astimezone(dt.timezone.utc)),
                out=out if out is not None else io.StringIO(),
                memory=lambda: {"ibgw_memory_peak_bytes": 1, "mem_available_kb": 2},
                own_clone=states["own_clone"], unit_env=lambda unit: UNIT_ENV[unit],
                firewall_status=states["twin"].parent / "ibgw-status" / "firewall.json")
