"""A second order set may not reach an auction the first one is already headed for.

WHY THIS FILE EXISTS
--------------------
CLAUDE.md hard rule 2 -- "the trade phase is not idempotent" -- was, until
2026-09-13, defended only by guards keyed on a heartbeat file and a wall-clock
date. Each was fixed after an incident with a particular shape, and the next
incident had a different one:

  2026-07-31  four armed runs stacked 79 MOC orders, invisible to openTrades()
  2026-09-10  a session slept, filed its beat the next morning, and the
              date-keyed same-day guard then REFUSED the legitimate 09-11
              session -- the guard was wrong in the safe direction that day,
              and nothing about its design made that the only direction

`OrdersAlreadyPending` asks the broker and the order map instead, so it holds
whatever the scheduler does. Each test below pins one property and, where there
is one, names the incident. Timestamps are the real `_order_map.csv` rows from
cef_live where a real row exists, so a failure reads as the day it describes.

NO BROKER, NO NETWORK, NO LIVE LEDGERS. The broker is built with `__new__`; the
order map is written into `tmp_path`.
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import pending_orders as po  # noqa: E402
from src.deploy.broker.ibkr import (  # noqa: E402
    IBKRBroker, NotArmed, OrdersAlreadyPending,
)
from src.deploy.sleeve import LONG, PositionTarget  # noqa: E402
from src.deploy.tests.test_option_order_path import _IbInsync  # noqa: E402

ET = dt.timezone(dt.timedelta(hours=-4))          # EDT, all dates below are Sept

CEF = ["AWF", "BIT", "JFR", "MHD", "MQY", "NAD", "NEA", "NVG"]


# -- stubs ------------------------------------------------------------------

class _Contract:
    def __init__(self, symbol):
        self.symbol = symbol
        self.localSymbol = symbol


class _Order:
    def __init__(self, action, qty, order_type="MOC", client_id=45, order_id=1,
                 perm_id=0):
        self.action, self.totalQuantity, self.orderType = action, qty, order_type
        self.clientId, self.orderId, self.permId = client_id, order_id, perm_id
        self.tif = ""


class _Trade:
    def __init__(self, symbol, action="BUY", qty=100, status="PreSubmitted",
                 **kw):
        self.contract = _Contract(symbol)
        self.order = _Order(action, qty, **kw)
        self.orderStatus = type("S", (), {"status": status})()
        self.fills = []


class _StubIB:
    """Answers the two open-order calls; records every placement."""

    def __init__(self, resting=(), all_open=None, raises=None):
        self._resting = list(resting)
        self._all_open = all_open
        self._raises = raises
        self.placed = []
        self.open_order_queries = 0

    def reqAllOpenOrders(self):
        self.open_order_queries += 1
        if self._raises:
            raise self._raises
        return list(self._resting if self._all_open is None else self._all_open)

    def openTrades(self):
        return list(self._resting)

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        t = _Trade(contract.symbol, order.action, order.totalQuantity)
        t.order = order
        return t


def _write_map(root: Path, rows):
    path = root / "_ibkr_shadow" / "_order_map.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["asof", "recorded_utc", "order_id", "perm_id", "client_id",
            "book_id", "sleeve", "instrument", "action", "qty"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


def _row(instrument, recorded_utc, action="BUY", qty="100",
         sleeve="cef_discount"):
    return {"asof": "", "recorded_utc": recorded_utc, "order_id": "1",
            "perm_id": "0", "client_id": "45", "book_id": "cef",
            "sleeve": sleeve, "instrument": instrument, "action": action,
            "qty": qty}


def _broker(tmp_path, ib, instruments=CEF):
    b = IBKRBroker.__new__(IBKRBroker)
    b._ib_insync = _IbInsync()
    b.ib = ib
    b._books_root = str(tmp_path)
    b._sleeves = {"cef_discount": {"instruments": list(instruments)}}
    b._live_positions = {"cef_discount": {}}
    b.verbose = False
    return b


# -- the incident shapes ----------------------------------------------------

def test_a_second_fire_is_refused_when_the_first_set_is_resting(tmp_path):
    """Hard rule 2, as the broker sees it: NAD BUY 1313 is resting for the close,
    and a second run would send it again."""
    ib = _StubIB(resting=[_Trade("NAD", "BUY", 1313)])
    b = _broker(tmp_path, ib)
    with pytest.raises(OrdersAlreadyPending, match="NAD"):
        b._refuse_if_orders_pending(
            now=dt.datetime(2026, 9, 11, 12, 0, tzinfo=ET))


def test_the_order_map_refuses_even_when_the_broker_query_is_blind(tmp_path):
    """2026-07-31: 79 stacked MOC orders were invisible to the open-order query.
    Our own record of transmitting is independent of that blindness.

    Real row: cef_live `_order_map.csv`, NAD BUY 1313 recorded
    2026-09-11T14:38:31Z (10:38 ET) -> the 2026-09-11 close.
    """
    _write_map(tmp_path, [_row("NAD", "2026-09-11T14:38:31.702971+00:00",
                               qty="1313.0")])
    b = _broker(tmp_path, _StubIB(resting=[]))
    with pytest.raises(OrdersAlreadyPending) as exc:
        b._refuse_if_orders_pending(
            now=dt.datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    msg = str(exc.value)
    assert "2026-09-11" in msg and "NAD" in msg
    assert "DISAGREE" in msg, "a blind broker query must be called out, not hidden"


def test_the_2026_09_11_session_would_NOT_have_been_refused(tmp_path):
    """The day the date-keyed guard got it wrong. The 09-10 set was sent 10:38
    on 09-11 and filled at the 09-11 close. At 22:00 that evening nothing is
    pending, and the broker-truth guard lets the session trade."""
    _write_map(tmp_path, [_row("NAD", "2026-09-11T14:38:31.702971+00:00",
                               qty="1313.0")])
    b = _broker(tmp_path, _StubIB(resting=[]))
    b._refuse_if_orders_pending(now=dt.datetime(2026, 9, 11, 22, 0, tzinfo=ET))
    assert b._pending_checked is True


def test_an_evening_set_is_pending_across_a_holiday_weekend(tmp_path):
    """Real row: PDO BUY 1212 recorded 2026-09-04T21:58:29Z = 17:58 ET Friday.
    Monday 09-07 is Labor Day, so its auction is Tuesday 09-08. A morning run
    on the holiday, or on the Tuesday before the close, must see it pending."""
    _write_map(tmp_path, [_row("PDO", "2026-09-04T21:58:29.398623+00:00",
                               qty="1212.0")])
    for now in (dt.datetime(2026, 9, 5, 9, 0, tzinfo=ET),
                dt.datetime(2026, 9, 7, 12, 0, tzinfo=ET),
                dt.datetime(2026, 9, 8, 8, 30, tzinfo=ET),
                dt.datetime(2026, 9, 8, 15, 59, tzinfo=ET)):
        b = _broker(tmp_path, _StubIB(), instruments=["PDO"])
        with pytest.raises(OrdersAlreadyPending, match="2026-09-08"):
            b._refuse_if_orders_pending(now=now)
    b = _broker(tmp_path, _StubIB(), instruments=["PDO"])
    b._refuse_if_orders_pending(now=dt.datetime(2026, 9, 8, 16, 1, tzinfo=ET))


def test_the_freeze_decides_which_auction_a_row_reached():
    """15:49 ET reaches today's close; 15:50 is the freeze and reaches the next
    session's. The constant is session_plan.MOC_CUTOFF_MIN, not re-derived."""
    rows = [_row("NVG", "2026-09-09T19:49:00+00:00"),     # 15:49 ET Wed
            _row("NVG", "2026-09-09T19:50:00+00:00")]     # 15:50 ET Wed
    now = dt.datetime(2026, 9, 9, 17, 0, tzinfo=ET)       # after Wed's close
    pend = po.pending_in_order_map(rows, ["NVG"], now)
    assert [p["auction"] for p in pend] == ["2026-09-10"]


# -- fail closed ------------------------------------------------------------

def test_a_broker_query_that_raises_refuses(tmp_path):
    b = _broker(tmp_path, _StubIB(raises=TimeoutError("reqAllOpenOrders")))
    with pytest.raises(OrdersAlreadyPending, match="could not ask the broker"):
        b._refuse_if_orders_pending(now=dt.datetime(2026, 9, 14, 9, tzinfo=ET))


def test_an_unparseable_timestamp_on_our_symbol_refuses(tmp_path):
    _write_map(tmp_path, [_row("NVG", "yesterday-ish")])
    b = _broker(tmp_path, _StubIB())
    with pytest.raises(OrdersAlreadyPending, match="unparseable"):
        b._refuse_if_orders_pending(now=dt.datetime(2026, 9, 14, 9, tzinfo=ET))


def test_a_naive_timestamp_refuses():
    with pytest.raises(po.PendingOrdersUnknown, match="naive"):
        po.pending_in_order_map([_row("NVG", "2026-09-09T19:49:00")], ["NVG"],
                                dt.datetime(2026, 9, 9, 17, tzinfo=ET))


def test_an_unreadable_trade_refuses():
    broken = type("T", (), {"contract": _Contract("NVG")})()   # no orderStatus
    with pytest.raises(po.PendingOrdersUnknown):
        po.resting_at_broker([broken], ["NVG"])


def test_inactive_counts_as_resting_and_only_done_states_do_not():
    trades = [_Trade("NVG", status=s) for s in
              ("Filled", "Cancelled", "ApiCancelled", "Inactive",
               "PreSubmitted", "Submitted", "PendingCancel")]
    got = sorted(r["status"] for r in po.resting_at_broker(trades, ["NVG"]))
    assert got == ["Inactive", "PendingCancel", "PreSubmitted", "Submitted"]


# -- scope: never a false positive that costs a session ----------------------

def test_another_books_symbol_does_not_refuse(tmp_path):
    """phase0/benchmarks trade credit ETFs in the same account. A resting HYG
    order is not a pending CEF order set."""
    _write_map(tmp_path, [_row("HYG", "2026-09-14T13:00:00+00:00",
                               sleeve="null_trader")])
    b = _broker(tmp_path, _StubIB(resting=[_Trade("HYG", status="Submitted")]))
    b._refuse_if_orders_pending(now=dt.datetime(2026, 9, 14, 12, tzinfo=ET))


def test_the_check_runs_once_so_a_sibling_sleeve_cannot_trip_on_this_run(tmp_path):
    """benchmarks runs bench_b1_hyg and bench_b6_ew_credit in ONE process and
    both trade HYG. Sleeve 1's own after-hours order must not refuse sleeve 2."""
    ib = _StubIB()
    b = _broker(tmp_path, ib, instruments=["HYG"])
    now = dt.datetime(2026, 9, 14, 17, 25, tzinfo=ET)
    b._refuse_if_orders_pending(now=now)
    ib._resting = [_Trade("HYG", status="PreSubmitted")]         # our own order
    b._refuse_if_orders_pending(now=now)                          # no raise
    assert ib.open_order_queries == 1


def test_held_but_unregistered_instruments_are_in_scope(tmp_path):
    """A leg the sleeve still holds is one place_targets may flatten, so a
    resting order on it counts even if the universe no longer lists it."""
    b = _broker(tmp_path, _StubIB(resting=[_Trade("FCT", "SELL", 50)]),
                instruments=["NVG"])
    b._live_positions = {"cef_discount": {"FCT": 50.0}}
    with pytest.raises(OrdersAlreadyPending, match="FCT"):
        b._refuse_if_orders_pending(now=dt.datetime(2026, 9, 14, 9, tzinfo=ET))


# -- wiring: the real place_targets refuses before its first transmission ----

def test_place_targets_transmits_nothing_when_a_set_is_pending(tmp_path):
    """Not `_refuse_if_orders_pending` in isolation: the real `place_targets`,
    with every other gate stubbed open, must raise before `placeOrder`."""
    ib = _StubIB(resting=[_Trade("NVG", "BUY", 250)])
    b = _broker(tmp_path, ib)
    b._armed = True
    b._bond_instruments = set()
    b._refuse_if_ledger_is_behind = lambda *a, **k: None
    b._record_order_attribution = lambda *a, **k: None
    b._fills_from_trade = lambda *a, **k: []
    b._backfill_perm_ids = lambda *a, **k: None
    b._resolve_qty = lambda pt, *a, **k: pt.qty
    tgt = [PositionTarget(instrument="NVG", side=LONG, qty=250.0,
                          meta={"order_type": "MOC"})]
    with pytest.raises(OrdersAlreadyPending):
        b.place_targets("cef_discount", tgt, "2026-09-11", market_state=None)
    assert ib.placed == [], "an order was transmitted before the refusal"


def test_place_targets_still_transmits_when_nothing_is_pending(tmp_path):
    """The guard's no-op: an empty broker and an empty map change nothing."""
    ib = _StubIB()
    b = _broker(tmp_path, ib)
    b._armed = True
    b._bond_instruments = set()
    b._refuse_if_ledger_is_behind = lambda *a, **k: None
    b._record_order_attribution = lambda *a, **k: None
    b._fills_from_trade = lambda *a, **k: []
    b._backfill_perm_ids = lambda *a, **k: None
    b._resolve_qty = lambda pt, *a, **k: pt.qty
    tgt = [PositionTarget(instrument="NVG", side=LONG, qty=250.0,
                          meta={"order_type": "MOC"})]
    b.place_targets("cef_discount", tgt, "2026-09-11", market_state=None)
    assert [(c.symbol, o.action, float(o.totalQuantity), o.orderType)
            for c, o in ib.placed] == [("NVG", "BUY", 250.0, "MOC")]


def test_refusal_is_a_NotArmed_so_every_existing_handler_treats_it_as_no_trade():
    assert issubclass(OrdersAlreadyPending, NotArmed)


def test_run_book_stands_down_on_it_without_writing_a_halt():
    """run_book must catch it around the trade phase and return a distinct rc.
    Read from source: the live path cannot be driven without a broker."""
    src = (REPO / "src" / "deploy" / "run_book.py").read_text()
    i = src.index("except OrdersAlreadyPending")
    block = src[i:i + 600]
    assert "return 5" in block
    assert "write_halt" not in block
