"""The third release check (6376a3a, 2026-11-26): an accepted order must never lose its ids, and the
account id must never reach a log. Plus the FX bar's own bound, the kept ledger evidence, and the
residual's unpriced names."""
from __future__ import annotations

import datetime as dt
import io
import json
import logging

import pytest

from quantt.broker import ibkr as I
from quantt.twin import ledger_view, run, verify
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_fx import BARS, BP, LEDGER, NLV, cad_send
from quantt.twin.tests.test_send import armed, world_and_books
from quantt.twin.tests.test_verify import FILLS

DAY = "2026-11-27"


# -- 1. the ids of an order that is live are written before anything can fail ----------------------

def test_a_warned_order_whose_requery_fails_is_still_booked_when_it_fills(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.warn = {"IWM": (404, "open")}                         # live at IBKR, held for a locate

    def before(con, order):
        if con.symbol == "IWM":
            w.requery_error = TimeoutError()               # the re-query after placeOrder hangs
    w.before_place = before
    run.send(d)
    day = st["twin"] / DAY
    send = run.started_send_record(day)
    assert send["stopped"] and "IWM" in send["stopped"], out.getvalue()          # stopped, ambiguously
    rows = [json.loads(x) for x in (day / "orders.jsonl").read_text().splitlines()]
    sub = [r for r in rows if r["event"] == "submitted" and r["symbol"] == "IWM"]
    assert sub and sub[0]["order_id"] is not None and sub[0]["client_id"] == 31
    placed = [r for r in rows if r["event"] == "placed" and r["symbol"] == "IWM"]
    assert placed and placed[0]["accepted"] is None and placed[0]["error_after_submit"] is True
    assert not any(r["event"] == "error" for r in rows)
    w.requery_error = None
    w.fill_all_at(FILLS, F.et(2026, 11, 27, 12, 59, 50))
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    verify.verify(d)
    v = json.loads((day / "verify.json").read_text())
    assert "FOREIGN" not in v["reason"] and v["ledger_applied"], v["reason"]
    assert ledger_view(st["twin"])["events/specdiv_wait"]["shares"]["IWM"] == -10      # its fill is booked


def test_a_crash_after_placeorder_is_booked_from_the_submitted_line(tmp_path, monkeypatch):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)

    def crash(trade):
        raise RuntimeError("stub: the process dies after placeOrder returned")
    monkeypatch.setattr(I.IBKRClient, "_status_of", staticmethod(crash))
    run.send(d)
    day = st["twin"] / DAY
    rows = [json.loads(x) for x in (day / "orders.jsonl").read_text().splitlines()]
    first = [r for r in rows if r["event"] == "submitted"]
    assert len(first) == 1 and not any(r["event"] == "placed" for r in rows)      # only the ids survived
    assert any(r["event"] == "error" for r in rows)
    monkeypatch.undo()
    w.fill_all_at(FILLS, F.et(2026, 11, 27, 12, 59, 50))
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    verify.verify(d)
    v = json.loads((day / "verify.json").read_text())
    assert "FOREIGN" not in v["reason"] and v["ledger_applied"], v["reason"]


def test_an_error_after_placeorder_returns_the_ids_never_raises():
    w = F.World()
    w.warn = {"PDI": (404, "open")}
    c = I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT), mode="trade", ib_module=F.stub_module(w),
                     sleep=lambda s: None).connect()
    c.qualify(["PDI"])
    seen = []

    def submitted(ids):                                     # the session is lost right after placeOrder:
        seen.append(ids)                                    # _find_open's _need() raises NotConnected
        c.ib = None
    r = c.place_moc("PDI", 10, "sell", "twin-20261127-PDI-1", on_submitted=submitted)
    assert seen and seen[0]["order_id"] == r["order_id"] and seen[0]["order_ref"] == "twin-20261127-PDI-1"
    assert r["accepted"] is None and r["order_id"] is not None and r["error_after_submit"]
    assert any("NotConnected" in m for m in r["messages"])
    c2 = I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 32, F.ACCOUNT), mode="trade", ib_module=F.stub_module(w),
                      sleep=lambda s: None).connect()
    c2.qualify(["PDI"])
    w.requery_error = TimeoutError()                        # a hung re-query: the session is dropped
    r2 = c2.place_moc("PDI", 10, "sell", "twin-20261127-PDI-2")
    assert r2["accepted"] is None and r2["error_after_submit"] and c2.ib is None


# -- 2. the account id never reaches a log -------------------------------------------------------------

def test_ib_asyncs_trade_warnings_and_cancels_never_log_the_account(capfd, caplog):
    ib_async = pytest.importorskip("ib_async")
    I.install_log_redaction(F.ACCOUNT)
    ib = ib_async.IB()
    w = ib.wrapper
    w.clientId = 31
    for oid, code in ((7, 404), (8, 201)):                   # a warning, then a rejection (Canceled order)
        order = ib_async.Order(orderId=oid, clientId=31, account=F.ACCOUNT, action="SELL", totalQuantity=10,
                               orderType="MOC", tif="DAY")
        w.trades[(31, oid)] = ib_async.Trade(contract=ib_async.Stock("IWM", "SMART", "USD"), order=order,
                                             orderStatus=ib_async.OrderStatus(orderId=oid, status="PreSubmitted"))
        with caplog.at_level(logging.INFO):
            w.error(oid, code, "held while IBKR locates shares", "")
    got = capfd.readouterr()
    assert F.ACCOUNT not in got.err and F.ACCOUNT not in got.out and F.ACCOUNT not in caplog.text
    assert "<account>" in caplog.text                       # the trade was logged, redacted


def test_every_twin_entry_point_installs_the_redaction_before_connecting():
    import inspect
    from quantt.twin import __main__ as M
    src = inspect.getsource(M.main)
    assert src.index("install_log_redaction(") < src.index("_feed_deps(env)") < src.index("_deps(env)")
    assert "install_log_redaction(self.config.account)" in inspect.getsource(I.IBKRClient.connect)


# -- non-blocking: the FX bar's own bound; the kept ledger evidence; the residual's unpriced names -----

def test_a_slow_fx_bar_is_fx_unmeasured_not_a_logout(tmp_path):
    st, w, mk, d, out = cad_send(tmp_path, fx_bars=[])        # ib_async after its own timeout: no bars
    d.out = io.StringIO()
    assert run.probe(d) == 0
    assert w.fx_timeout == I.FX_BAR_TIMEOUT_S < I.REQUEST_TIMEOUT_S
    g = json.loads((st["twin"] / "status.json").read_text())["gateway"]
    assert g["logged_in"] is True and "FX UNMEASURED" in g["fx"]["why"]
    st2, w2, mk2, d2, out2 = cad_send(tmp_path / "b", fx_bars=BARS)
    w2.fx_raise = TimeoutError()                              # even a hung bar: still not a logout
    d2.out = io.StringIO()
    run.probe(d2)
    g2 = json.loads((st2["twin"] / "status.json").read_text())["gateway"]
    assert g2["logged_in"] is True and "FX UNMEASURED" in g2["fx"]["why"]


def test_the_ledgers_contradiction_is_kept_beside_the_bar(tmp_path):
    inverted = {**LEDGER, "USD": (1 / 1.40, 500_000.0)}
    st, w, mk, d, out = cad_send(tmp_path, ledger=inverted, fx_bars=BARS)
    assert run.send(d) == run.EXIT_SENT, out.getvalue()
    fx = run.started_send_record(st["twin"] / DAY)["buying_power"]["fx"]
    assert fx["source"] == "ibkr_fx_bar:USDCAD:MIDPOINT"


def test_the_ledgers_contradiction_is_in_the_status(tmp_path):
    inverted = {**LEDGER, "USD": (1 / 1.40, 500_000.0)}
    st, w, mk, d, out = cad_send(tmp_path, ledger=inverted, fx_bars=BARS)
    from quantt.twin.run import with_fx_bar
    c = d.ibkr("read").connect()
    s = with_fx_bar(d, c, c.account_summary())
    assert s["fx"]["source"] == "ibkr_fx_bar:USDCAD:MIDPOINT"
    assert s["fx"]["row_evidence"]["direction_check"].startswith("CONTRADICTS")


def test_the_residual_names_the_unpriced_holdings(tmp_path):
    new = {"sleeves": {"cef": {"shares": {"PDI": 100, "NAD": -50}, "cash": 0.0}}}
    summ = {"net_liquidation": NLV, "base_currency": "USD", "usd_per_base": 1.0, "fx": {}}
    r = verify._nlv(tmp_path, summ, new, {"cef": None}, 0.0, 0, dt.date(2026, 11, 27), prices={"PDI": 20.0})
    assert r["residual_usd"] is None and r["unpriced"] == ["NAD"] and "1 held symbol(s) with no official close (NAD)" in r["why"]


# ---- release check of 85f5a1e (2026-11-26): the contradiction reaches the RECORDS, and the account
# id never rides out on an exception's text.

def test_the_ledgers_contradiction_reaches_send_json_and_status_json(tmp_path):
    """A CONTRADICTS between IBKR's ledger row and its USDCAD bar must be in what is kept, not only
    in the return value (CLAUDE.md: two sources that disagree are reported, never dropped)."""
    from quantt.twin.tests.test_fx import BARS as FX_BARS, cad_send as fx_cad_send
    inverted = {**LEDGER, "USD": (1 / 1.40, 500_000.0)}
    st, w, mk, d, out = fx_cad_send(tmp_path, ledger=inverted, fx_bars=FX_BARS)
    assert run.send(d) == run.EXIT_SENT, out.getvalue()
    kept = run.started_send_record(st["twin"] / "2026-11-27")["buying_power"]["fx"]
    assert kept["row_evidence"]["direction_check"].startswith("CONTRADICTS")
    d.out = io.StringIO()
    assert run.probe(d) == 0
    g = json.loads((st["twin"] / "status.json").read_text())["gateway"]
    assert g["fx"]["row_evidence"]["direction_check"].startswith("CONTRADICTS")


def test_a_sync_error_naming_the_account_reaches_no_file_and_no_stdout(tmp_path):
    """ib_async's connect sync names the account ("account updates for <id>", ib.py around 2072) in
    the ConnectionError it raises; the twin's refusal is written to status.json, send.json and stdout."""
    from quantt.twin.tests.test_fx import cad_send as fx_cad_send
    st, w, mk, d, out = fx_cad_send(tmp_path)
    w.sync_error = f"account updates for {F.ACCOUNT} request timed out"
    assert run.send(d) == run.EXIT_REFUSED
    d.out2 = io.StringIO()
    d.out = d.out2
    run.probe(d)
    assert F.ACCOUNT not in out.getvalue() and F.ACCOUNT not in d.out2.getvalue()
    for p in st["twin"].rglob("*"):
        if p.is_file():
            assert F.ACCOUNT not in p.read_text(errors="ignore"), p
