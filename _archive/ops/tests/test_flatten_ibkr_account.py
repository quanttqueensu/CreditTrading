"""The IBKR flatten: MOC only, dry run by default, and it cannot run twice.

Every test uses a fake broker injected in place of `_connect`; the root
conftest's netguard fails any test that opens a socket. The properties pinned
are the ones order-path rules 1-4 exist for: an order type other than MOC, a
default that transmits, a second armed run, DRY_RUN=1 losing, a position closed
silently in part.
"""
import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest

from ops import flatten_ibkr_account as fl

ET = fl.ET
OPEN_DAY = dt.datetime(2026, 9, 29, 10, 0, tzinfo=ET)          # a Tuesday


def pos(sym, qty, sec="STK", cur="USD", acct="DU1", con=None):
    return NS(account=acct, position=qty,
              contract=NS(symbol=sym, secType=sec, currency=cur, conId=con or hash(sym) % 10**6))


class FakeIBI:
    class Order:
        pass

    class Contract:
        def __init__(self, conId, exchange):
            self.conId, self.exchange = conId, exchange


class FakeIB:
    def __init__(self, positions, open_orders=()):
        self._pos, self._open = positions, list(open_orders)
        self.placed, self.readonly = [], None

    def positions(self):
        return self._pos

    def reqAllOpenOrders(self):
        return self._open

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        return NS(order=NS(orderId=len(self.placed)), orderStatus=NS(status="PreSubmitted"))

    def sleep(self, s):
        pass

    def disconnect(self):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "OUT_DIR", tmp_path)
    monkeypatch.setattr(fl, "REPO", tmp_path.parent)
    monkeypatch.delenv("DRY_RUN", raising=False)

    class _Now(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return OPEN_DAY
    monkeypatch.setattr(fl.dt, "datetime", _Now)
    box = {}

    def install(ib):
        def connect(readonly):
            ib.readonly = readonly
            return FakeIBI, ib
        monkeypatch.setattr(fl, "_connect", connect)
        box["ib"] = ib
        return ib
    return install


BOOK = [pos("PDI", 1200), pos("NVG", -3400), pos("HYG", 50)]


def test_the_default_run_connects_read_only_and_sends_nothing(env):
    ib = env(FakeIB(BOOK))
    assert fl.main([]) == 0
    assert ib.readonly is True and ib.placed == []


def test_every_order_is_moc_day_and_exactly_reverses_the_position(env):
    ib = env(FakeIB(BOOK))
    assert fl.main(["--transmit", "--account", "DU1"]) == 0
    assert ib.readonly is False
    got = {c.conId: (o.action, o.totalQuantity, o.orderType, o.tif) for c, o in ib.placed}
    want = {p.contract.conId: ("SELL" if p.position > 0 else "BUY", abs(p.position), "MOC", "DAY")
            for p in BOOK}
    assert got == want
    assert all(c.exchange == "SMART" for c, _ in ib.placed)


def test_a_second_transmit_the_same_day_is_refused(env):
    ib = env(FakeIB(BOOK))
    assert fl.main(["--transmit", "--account", "DU1"]) == 0
    n = len(ib.placed)
    assert fl.main(["--transmit", "--account", "DU1"]) == 2
    assert len(ib.placed) == n


def test_the_record_is_written_before_the_first_order_goes(env, tmp_path):
    seen = {}

    class Spy(FakeIB):
        def placeOrder(self, contract, order):
            if not self.placed:
                rec = json.loads((tmp_path / f"{OPEN_DAY.date()}.json").read_text())
                seen["started"] = rec.get("transmit_started")
            return super().placeOrder(contract, order)
    env(Spy(BOOK))
    fl.main(["--transmit", "--account", "DU1"])
    assert seen["started"]


def test_open_orders_at_the_broker_refuse_before_anything_is_sent(env):
    resting = NS(contract=NS(symbol="PDI"), order=NS(action="SELL", totalQuantity=100,
                 orderType="MOC", clientId=45), orderStatus=NS(status="PreSubmitted"))
    ib = env(FakeIB(BOOK, [resting]))
    assert fl.main(["--transmit", "--account", "DU1"]) == 2
    assert ib.placed == []


def test_dry_run_1_always_wins(env, monkeypatch):
    ib = env(FakeIB(BOOK))
    monkeypatch.setenv("DRY_RUN", "1")
    assert fl.main(["--transmit", "--account", "DU1"]) == 3
    assert ib.placed == []


def test_transmit_needs_the_account_the_broker_reports(env):
    ib = env(FakeIB(BOOK))
    assert fl.main(["--transmit"]) == 3
    assert fl.main(["--transmit", "--account", "DU999"]) == 2
    assert ib.placed == []


@pytest.mark.parametrize("bad", [pos("HYG  260116C00080000", 2, sec="OPT"),
                                 pos("XIU", 100, cur="CAD"),
                                 pos("PTY", 10.5)])
def test_anything_not_closable_by_moc_refuses_the_whole_plan(env, bad):
    ib = env(FakeIB(BOOK + [bad]))
    assert fl.main(["--transmit", "--account", "DU1"]) == 2
    assert ib.placed == []


def test_two_accounts_in_one_session_refuse():
    with pytest.raises(fl.Refused, match="accounts"):
        fl.build_plan([pos("PDI", 1, acct="DU1"), pos("PTY", 1, acct="DU2")])


@pytest.mark.parametrize("when,ok", [
    (dt.datetime(2026, 9, 29, 15, 39, tzinfo=ET), True),
    (dt.datetime(2026, 9, 29, 15, 40, tzinfo=ET), False),    # the cutoff
    (dt.datetime(2026, 11, 27, 12, 39, tzinfo=ET), True),    # day after Thanksgiving
    (dt.datetime(2026, 11, 27, 12, 40, tzinfo=ET), False),   # early close
    (dt.datetime(2026, 12, 24, 13, 0, tzinfo=ET), False),    # Christmas Eve
    (dt.datetime(2026, 10, 3, 10, 0, tzinfo=ET), False),     # a Saturday
    (dt.datetime(2026, 11, 26, 10, 0, tzinfo=ET), False),    # Thanksgiving
])
def test_the_moc_window(when, ok):
    if ok:
        fl.check_window(when)
    else:
        with pytest.raises(fl.Refused):
            fl.check_window(when)


def test_zero_rows_are_ignored_and_a_flat_account_sends_nothing(env):
    ib = env(FakeIB([pos("PDI", 0)]))
    assert fl.main(["--transmit", "--account", "DU1"]) in (0, 2)   # 2 only if no account seen
    assert ib.placed == []


def test_verify_reports_not_flat_with_nonzero_exit(env):
    env(FakeIB([pos("PDI", 5)]))
    assert fl.main(["--verify"]) == 1
    env(FakeIB([]))
    assert fl.main(["--verify"]) == 0
