"""The release check of 8f9d026 (2026-11-26): five twin defects, each test failing on the code it fixes.

1. A warning (ib_async's ValidationError) on a live order stopped the batch.
2. A backup run's record replaced the record of the run that wrote STARTED, so verify passed a part-sent day.
3. An approval was written under today's date, whatever session it was read for.
4. status.json's last_send was overwritten by every IDLE run.
5. A failed initial sync at connect was only logged, leaving an empty positions cache.
"""
from __future__ import annotations

import datetime as dt
import inspect
import json
import re

import pytest

from quantt.broker import ibkr as I
from quantt.twin import config, run, verify
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_send import S, armed, world_and_books
from quantt.twin.tests.test_verify import FILLS

DAY = "2026-11-27"


def trade_client(w):
    t = {"now": 0.0}

    def mono():
        t["now"] += 0.5
        return t["now"]
    c = I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT), mode="trade", ib_module=F.stub_module(w),
                     sleep=lambda s: None, monotonic=mono).connect()
    c.qualify(["PDI"])
    return c


# -- 1. a warning is not a rejection ---------------------------------------------------------------

def test_the_warning_codes_are_the_installed_librarys():
    wrapper = pytest.importorskip("ib_async.wrapper")
    src = inspect.getsource(wrapper.Wrapper.error)
    codes = re.search(r"warningCodes = frozenset\(\{([0-9, ]+)\}\)", src).group(1)
    assert I.IB_WARNING_CODES == frozenset(int(x) for x in codes.split(","))
    assert "2100 <= errorCode < 2200" in src and I.IB_WARNING_RANGE == (2100, 2200)
    assert "OrderStatus.ValidationError" in src and I.VALIDATION_ERROR == "ValidationError"


def test_validation_error_then_submitted_is_accepted_with_the_warning():
    w = F.World()
    w.warn = {"PDI": (404, "Submitted")}
    r = trade_client(w).place_moc("PDI", 10, "sell", "twin-20261127-PDI-1")
    assert r["accepted"] is True and r["status"] == "Submitted" and r["warnings"] == [404]


def test_validation_error_only_with_the_order_resting_is_accepted():
    w = F.World()
    w.warn = {"PDI": (404, "open")}
    r = trade_client(w).place_moc("PDI", 10, "sell", "twin-20261127-PDI-1")
    assert r["accepted"] is True and r["found_open"] and r["status"] == "ValidationError" and r["warnings"] == [404]


def test_validation_error_with_the_order_absent_is_ambiguous_never_refused():
    w = F.World()
    w.warn = {"PDI": (404, "absent")}
    r = trade_client(w).place_moc("PDI", 10, "sell", "twin-20261127-PDI-1")
    assert r["accepted"] is None and not r["found_open"] and r["requeries"] == 2


def test_a_real_rejection_is_refused():
    w = F.World()
    w.reject = {"PDI"}
    assert trade_client(w).place_moc("PDI", 10, "sell", "twin-20261127-PDI-1")["accepted"] is False
    w = F.World()
    w.warn = {"PDI": (404, "Cancelled")}                     # a warning, then IBKR cancels it
    r = trade_client(w).place_moc("PDI", 10, "sell", "twin-20261127-PDI-1")
    assert r["accepted"] is False and r["status"] == "Cancelled"


def test_a_short_held_for_a_locate_does_not_stop_the_batch(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.warn = {"IWM": (404, "open")}                          # IWM opens a short: held while IBKR locates
    assert run.send(d) == run.EXIT_SENT, out.getvalue()
    send = run.started_send_record(st["twin"] / DAY)
    assert send["stopped"] is None and send["sent"] == len(send["orders"])
    placed = [json.loads(x) for x in (st["twin"] / DAY / "orders.jsonl").read_text().splitlines()
              if json.loads(x)["event"] == "placed"]
    iwm = [p for p in placed if p["symbol"] == "IWM"]
    assert iwm and iwm[0]["accepted"] is True and iwm[0]["warnings"] == [404]


def test_a_warned_then_cancelled_first_leg_sends_no_second_leg(tmp_path):
    """Release check of 300b884: the order must be found in the GATEWAY's answer, never in the client's
    own cache (openTrades), which holds every order it just placed until a done status arrives."""
    st, w, mk, d, out = world_and_books(tmp_path, legacy={"NAD": 40})     # NAD: +40 now, -30 wanted
    armed(st)
    w.warn = {"NAD": (321, "Cancelled")}                     # leg 1 warned, then IBKR cancels it
    run.send(d)
    nad = [o for _, sym, o in w.placed if sym == "NAD"]
    assert len(nad) == 1, out.getvalue()                     # leg 1 only: the opening leg never goes
    events = [json.loads(x) for x in (st["twin"] / DAY / "orders.jsonl").read_text().splitlines()]
    assert any(e["event"] == "skipped_open_leg" and e["symbol"] == "NAD" for e in events)
    placed = [e for e in events if e["event"] == "placed" and e["symbol"] == "NAD"]
    assert placed[0]["accepted"] is False and placed[0]["warnings"] == [321]


def test_the_open_order_query_never_reads_the_clients_own_cache():
    w = F.World()
    w.warn = {"PDI": (404, "open")}
    c = trade_client(w)

    def cache(*a):
        raise AssertionError("openTrades (the client's own cache) was read to judge an order")
    c.ib.openTrades = cache
    r = c.place_moc("PDI", 10, "sell", "twin-20261127-PDI-1")
    assert r["accepted"] is True and r["found_open"]          # found in reqAllOpenOrders, the Gateway's answer


# -- 2. the record of the run that wrote STARTED is never overwritten ------------------------------

def stop_on(symbol, w):
    def before(con, order):
        if con.symbol == symbol:
            raise ConnectionError("stub: the socket dropped while placing")
    w.before_place = before


def test_a_failed_first_send_then_a_refused_backup_still_fails_verify(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.reject = {"MHD"}
    stop_on("PDI", w)
    first = run.send(d)
    assert first not in (run.EXIT_SENT, run.EXIT_NOTHING), out.getvalue()
    mk.now = F.et(2026, 11, 27, 12, 40, 5)
    assert run.send(d) == run.EXIT_REFUSED                   # the backup refuses on STARTED ...
    day = st["twin"] / DAY
    assert run.started_send_record(day)["stopped"]           # ... and the first's record stands
    assert any(p.name.startswith("send_1240") for p in day.iterdir())
    w.fill_all_at(FILLS, F.et(2026, 11, 27, 12, 59, 50))
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 1, out.getvalue()
    v = json.loads((day / "verify.json").read_text())
    assert not v["ok"] and "the send stopped" in v["reason"] and "1 rejected" in v["reason"]


def test_a_crash_after_started_fails_verify_whatever_the_backup_writes(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)

    def crash(con, order):
        raise SystemExit("stub: the process was killed after STARTED")
    w.before_place = crash
    with pytest.raises(SystemExit):
        run.send(d)
    day = st["twin"] / DAY
    assert (day / "STARTED").exists() and not (day / "send.json").exists()
    w.before_place = None
    mk.now = F.et(2026, 11, 27, 12, 40, 5)
    assert run.send(d) == run.EXIT_REFUSED
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 1, out.getvalue()
    v = json.loads((day / "verify.json").read_text()) if (day / "verify.json").exists() else None
    assert "send.json does not" in out.getvalue() or (v and "send.json does not" in v["reason"])


# -- 3. an approval names its session ---------------------------------------------------------------

def dry_sha(d, session):
    import io
    d.out = io.StringIO()
    assert run.send(d, dry=True, session=session) == run.EXIT_DRY
    return re.search(r"plan_sha ([0-9a-f]{64})", d.out.getvalue()).group(1)


def test_approving_tomorrows_session_today_arms_tomorrow_only(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, now=F.et(2026, 11, 25, 18, 0), dry_run="0")
    sha = dry_sha(d, S)
    assert run.approve(d, session=S, sha=sha) == 0           # read on Wednesday, for Friday
    assert json.loads((st["twin"] / DAY / "APPROVED").read_text())["session_date"] == DAY
    assert not (st["twin"] / "2026-11-25" / "APPROVED").exists()
    mk.now = F.et(2026, 11, 27, 12, 30, 5)
    assert run.send(d) == run.EXIT_SENT and w.placed


def test_todays_approval_does_not_arm_another_session(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, dry_run="0")      # Friday 12:30
    sha = dry_sha(d, S)
    assert run.approve(d, session=S, sha=sha) == 0
    monday = st["twin"] / "2026-11-30"
    monday.mkdir()
    (monday / "APPROVED").write_text((st["twin"] / DAY / "APPROVED").read_text())   # copied, not approved
    mk.now = F.et(2026, 11, 30, 15, 30, 5)
    run.send(d)
    rec_ = run.latest_send_record(monday) or {}
    assert any(r["gate"] == "arming" and "approves session 2026-11-27" in r["detail"] for r in rec_.get("refusals", []))


def test_approve_refuses_a_past_session_and_a_day_that_does_not_trade(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    assert run.approve(d, session=dt.date(2026, 11, 25), sha="0" * 64) == run.EXIT_REFUSED      # past
    assert run.approve(d, session=dt.date(2026, 11, 26), sha="0" * 64) == run.EXIT_REFUSED      # holiday
    assert run.approve(d, session=None, sha="0" * 64) == run.EXIT_REFUSED
    from quantt.twin.__main__ import main
    with pytest.raises(SystemExit):
        main(["approve", "--sha", "0" * 64])                    # --session is required, no default


# -- 4. an idle run does not hide the last session send ---------------------------------------------

def test_an_idle_run_keeps_the_last_session_send(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    assert run.send(d) == run.EXIT_SENT
    mk.now = F.et(2026, 11, 27, 12, 40, 5)
    assert run.send(d) == run.EXIT_IDLE                      # DONE: the backup idles
    s = json.loads((st["twin"] / "status.json").read_text())
    assert s["last_send"]["exit"] == "IDLE" and s["last_session_send"]["exit"] == "SENT"
    from ops import daily_page as dp
    from ops import prod_state as ps
    lines = dict(ps.twin_lines({"units": {"value": {}}, "status": {"value": s}}))
    assert lines["  last session send"].startswith("2026-11-27 SENT")       # orient, not the idle run
    assert dp.twin_block(s)["last_send"]["exit"] == "SENT"                   # the daily page


# -- 5. a failed sync at connect raises -----------------------------------------------------------

def test_the_installed_connect_takes_raise_sync_errors():
    ib = pytest.importorskip("ib_async.ib")
    assert "raiseSyncErrors" in inspect.signature(ib.IB.connect).parameters


def test_a_failed_positions_sync_refuses_the_connection():
    w = F.World()
    w.positions = {"PDI": 100}
    w.sync_error = "positions request timed out"
    c = I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 32, F.ACCOUNT), mode="read", ib_module=F.stub_module(w),
                     sleep=lambda s: None)
    with pytest.raises(I.NotConnected, match="positions request timed out"):
        c.connect()


# -- release check of 300b884: no open- or completed-order requests at connect ------------------------

@pytest.mark.parametrize("mode", ["read", "trade"])
def test_no_client_asks_for_open_or_completed_orders_at_connect(mode):
    w = F.World()
    I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 33, F.ACCOUNT), mode=mode, ib_module=F.stub_module(w),
                 sleep=lambda s: None).connect()
    kw = w.connect_kwargs[-1]
    sf = F.StartupFetch
    assert kw["raiseSyncErrors"] is True and kw["fetchFields"] is not None
    assert not kw["fetchFields"] & sf.ORDERS_OPEN and not kw["fetchFields"] & sf.ORDERS_COMPLETE
    assert kw["fetchFields"] & sf.POSITIONS and kw["fetchFields"] & sf.ACCOUNT_UPDATES


def test_the_fetch_flags_are_the_installed_librarys_names():
    ib = pytest.importorskip("ib_async.ib")
    assert {m.name for m in ib.StartupFetch} == {m.name for m in F.StartupFetch}
    assert "fetchFields" in inspect.signature(ib.IB.connect).parameters


def test_the_guard_still_asks_the_gateway_for_open_orders():
    w = F.World()
    calls = []
    mod = F.stub_module(w)
    real = mod.IB.reqAllOpenOrders

    def counted(self):
        calls.append(1)
        return real(self)
    mod.IB.reqAllOpenOrders = counted
    c = I.IBKRClient(I.IBKRConfig("127.0.0.1", 4002, 33, F.ACCOUNT), mode="read", ib_module=mod,
                     sleep=lambda s: None).connect()
    c.open_orders()
    assert calls == [1]
