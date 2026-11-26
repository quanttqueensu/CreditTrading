"""The IBKR paper client (quantt/broker/ibkr.py) on a stub `ib_async`: no library, no socket.

Each test pins one refusal the module docstring promises. The account id used is a made-up
paper-shaped string; no test reads a real one."""
from __future__ import annotations

import ast
import datetime as dt
import types
from pathlib import Path

import pytest

from quantt.broker import ibkr as I
from quantt.twin.tests import fakes as F

REPO = Path(__file__).resolve().parents[2]


def cfg(**kw):
    base = dict(host="127.0.0.1", port=4002, client_id=31, account=F.ACCOUNT)
    base.update(kw)
    return I.IBKRConfig(**base)


def client(world, mode="read"):
    return I.IBKRClient(cfg(), mode=mode, ib_module=F.stub_module(world), sleep=lambda s: None)


# -- paper only ---------------------------------------------------------------

@pytest.mark.parametrize("port", sorted(I.LIVE_PORTS))
def test_a_live_port_is_refused(port):
    with pytest.raises(I.NotPaper, match="LIVE"):
        cfg(port=port)


def test_only_the_paper_ports_are_accepted():
    assert I.PAPER_PORTS == {4002, 7497} and not (I.PAPER_PORTS & I.LIVE_PORTS)
    for p in (4002, 7497):
        cfg(port=p)
    with pytest.raises(I.NotPaper):
        cfg(port=5000)


def test_an_account_id_that_is_not_paper_shaped_is_refused_without_printing_it():
    with pytest.raises(I.NotPaper) as e:
        cfg(account="U7654321")
    assert "U7654321" not in str(e.value)


def test_every_setting_is_required_and_none_is_defaulted():
    full = {I.ENV_HOST: "127.0.0.1", I.ENV_PORT: "4002", I.ENV_CLIENT_ID: "31", I.ENV_ACCOUNT: F.ACCOUNT}
    assert I.IBKRConfig.from_env(full).port == 4002
    for k in I.REQUIRED_ENV:
        env = {**full}
        del env[k]
        with pytest.raises(I.MissingSetting, match=k):
            I.IBKRConfig.from_env(env)


def test_the_account_is_never_in_repr():
    c = client(F.World())
    assert F.ACCOUNT not in repr(c) and F.ACCOUNT not in repr(c.config)


# -- connect -------------------------------------------------------------------

def test_a_login_that_does_not_manage_the_account_is_refused_and_names_no_id():
    w = F.World()
    w.accounts = ["DU9999999"]
    with pytest.raises(I.WrongAccount) as e:
        client(w).connect()
    assert F.ACCOUNT not in str(e.value) and "DU9999999" not in str(e.value)


def test_an_unreachable_gateway_is_not_connected():
    w = F.World()
    w.reachable = False
    with pytest.raises(I.NotConnected, match="not logged in"):
        client(w).connect()


def test_a_read_client_passes_readonly_to_the_library():
    w = F.World()
    client(w, "read").connect()
    client(w, "trade").connect()
    assert [c.readonly for c in w.connections] == [True, False]


def test_the_library_is_imported_inside_connect_only():
    tree = ast.parse((REPO / "quantt/broker/ibkr.py").read_text())
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name for n in top for a in getattr(n, "names", [])} | {getattr(n, "module", "") for n in top}
    assert not any(str(x).startswith(("ib_async", "ib_insync")) for x in names)
    assert "ib_insync" not in (REPO / "quantt/broker/ibkr.py").read_text().replace("never ib_insync", "") \
        .replace("bare `ib_insync`", "").replace("the `ib_insync` fallback", "")


# -- orders ---------------------------------------------------------------------

def test_place_moc_sends_an_moc_day_order_with_its_ref_and_account():
    w = F.World()
    c = client(w, "trade").connect()
    c.qualify(["PDI"])
    r = c.place_moc("PDI", 10, "buy", "twin-20261127-PDI")
    (_, sym, o), = w.placed
    assert (sym, o.action, o.totalQuantity, o.orderType, o.tif, o.orderRef, o.account) == \
        ("PDI", "BUY", 10, "MOC", "DAY", "twin-20261127-PDI", F.ACCOUNT)
    assert r["accepted"] is True and r["perm_id"] and r["order_id"]


def test_a_read_client_cannot_place_cancel_or_cancel_all():
    w = F.World()
    c = client(w, "read").connect()
    c.qualify(["PDI"])
    with pytest.raises(I.ReadOnlyClient):
        c.place_moc("PDI", 10, "buy", "twin-x")
    with pytest.raises(I.ReadOnlyClient):
        c.cancel(1)
    with pytest.raises(I.ReadOnlyClient):
        c.global_cancel()
    assert w.placed == [] and w.cancelled == 0 and w.global_cancels == 0


@pytest.mark.parametrize("qty", [0, -5, 1.5, True])
def test_no_fractional_or_non_positive_quantity(qty):
    c = client(F.World(), "trade").connect()
    c.qualify(["PDI"])
    with pytest.raises(ValueError):
        c.place_moc("PDI", qty, "buy", "twin-x")


def test_an_unqualified_symbol_is_never_sent():
    c = client(F.World(), "trade").connect()
    with pytest.raises(ValueError, match="qualify"):
        c.place_moc("PDI", 1, "buy", "twin-x")


def test_a_rejection_and_a_silence_are_told_apart():
    w = F.World()
    w.reject, w.silent = {"NAD"}, {"MHD"}
    t = [0.0]

    def mono():
        t[0] += 1.0
        return t[0]
    c = I.IBKRClient(cfg(), mode="trade", ib_module=F.stub_module(w), sleep=lambda s: None, monotonic=mono)
    c.connect()
    c.qualify(["NAD", "MHD"])
    assert c.place_moc("NAD", 1, "sell", "a")["accepted"] is False
    assert c.place_moc("MHD", 1, "buy", "b")["accepted"] is None


# -- reads ----------------------------------------------------------------------

def test_open_orders_union_both_calls_across_client_ids():
    """2026-07-31: openTrades() showed one client's orders only. The union sees another client's."""
    w = F.World()
    other = client(w, "trade").connect()
    other.config = cfg(client_id=99)
    other.ib.client_id = 99
    other.qualify(["NAD"])
    other.place_moc("NAD", 1313, "buy", "x")
    w.blind_all_open = True              # the all-orders call misses it ...
    me = client(w, "read").connect()
    assert me.open_orders() == []        # ... and so does openTrades for this client: the known blind spot
    w.blind_all_open = False
    assert [o["symbol"] for o in me.open_orders()] == ["NAD"]


def test_a_failed_open_order_query_is_unknown_not_empty():
    w = F.World()
    c = client(w).connect()
    c.ib.reqAllOpenOrders = lambda: (_ for _ in ()).throw(ConnectionError("x"))
    with pytest.raises(I.OpenOrdersUnknown):
        c.open_orders()


def test_done_states_match_the_installed_library():
    OrderStatus = pytest.importorskip("ib_async.order").OrderStatus
    assert I.DONE_STATUSES == frozenset(OrderStatus.DoneStates)


def test_a_defaulted_commission_report_is_none_not_zero():
    w = F.World()
    c = client(w, "trade").connect()
    c.qualify(["PDI"])
    c.place_moc("PDI", 5, "buy", "r")
    w.fill_all_at({"PDI": 20.0}, dt.datetime(2026, 11, 27, 18, tzinfo=dt.timezone.utc))
    w.executions[0].commissionReport = types.SimpleNamespace(execId="", commission=0.0, currency="")
    ex, = client(w).connect().executions_today(since=F.et(2026, 11, 27, 0, 0))
    assert ex["commission"] is None and ex["qty"] == 5 and ex["side"] == "buy"


def test_a_position_that_is_not_a_usd_stock_raises():
    w = F.World()
    c = client(w).connect()
    c.ib.positions = lambda account="": [types.SimpleNamespace(
        account=F.ACCOUNT, position=1.0,
        contract=types.SimpleNamespace(symbol="XYZ", localSymbol="XYZ", secType="OPT", currency="USD"))]
    with pytest.raises(I.UnexpectedReply, match="not a USD stock"):
        c.positions()


def test_a_non_usd_base_uses_ibkrs_own_rate_or_none():
    w = F.World()
    w.base = "CAD"
    assert client(w).connect().account_summary()["usd_per_base"] is None
    w.usd_rate = 1.40
    assert abs(client(w).connect().account_summary()["usd_per_base"] - 1 / 1.40) < 1e-12


def test_share_classes_map_both_ways():
    assert I.to_ib_symbol("BRK.B") == "BRK B" and I.from_ib_symbol("BRK B") == "BRK.B"
