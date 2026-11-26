"""The independent review of `ibkr-twin-build` (2026-11-25), one test or more per finding, each end
to end on fakes on the 2026-11-27 early close. Each guard test was also run against a scratch copy
with its guard removed and failed there (the build's report lists them)."""
from __future__ import annotations

import datetime as dt
import io
import json
import types

import pytest

from quantt.session import records as rec
from quantt.twin import books, config, guard, run, verify
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_send import A, PRINTS, S, armed, world_and_books

DAY = "2026-11-27"


def started_path(st):
    return st["twin"] / DAY / "STARTED"


# -- 1. verify persistence: saved read, retry slots, UNBOOKED ------------------------------

def crossed_books(tmp_path, prints):
    """Core sells 50 NAD, C4 buys 50: fully crossed inside the account, so it books at the close."""
    st = F.make_states(tmp_path)
    w = F.World()
    mk = F.FakeMarket(F.et(2026, 11, 27, 12, 30, 5), F.nov_calendar(), prints=dict(prints))
    F.write_core_plan(st["cef"], "cef", S, A, {"NAD": -50, "PDI": 10}, {}, {"NAD": 12.1, "PDI": 19.9})
    F.write_core_plan(st["c4"], "c4", S, A, {"NAD": 50}, {}, {"NAD": 12.1})
    out = io.StringIO()
    d = F.deps_for(st, w, mk, F.env_for(st, DRY_RUN="0"), out=out)
    assert run.epoch(d) == 0
    armed(st)
    assert run.send(d) == 0, out.getvalue()
    assert {s for _, s, _ in w.placed} == {"PDI"}            # NAD never reaches the market
    w.fill_all_at({"PDI": 20.0}, F.et(2026, 11, 27, 12, 59, 50))
    return st, w, mk, d, out


def test_the_read_is_saved_and_a_later_slot_books_from_it_when_the_gateway_is_down(tmp_path):
    st, w, mk, d, out = crossed_books(tmp_path, {"PDI": 20.0})               # no NAD print yet
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 1 and "PENDING" in out.getvalue()
    saved = st["twin"] / DAY / verify.READ_FILE
    assert saved.exists() and oct(saved.stat().st_mode & 0o777) == "0o600"
    assert F.ACCOUNT not in saved.read_text()
    assert not json.loads((st["twin"] / "ledger.json").read_text())["session"]
    w.reachable = False                                                       # Gateway down at 18:30
    mk.prints["NAD"] = 12.0                                                    # the print has landed
    mk.now = F.et(2026, 11, 27, 18, 30, 5)
    assert verify.verify(d) == 0, out.getvalue()
    v = json.loads((st["twin"] / DAY / "verify.json").read_text())
    assert v["ledger_applied"] and v["ibkr_read"].startswith("saved")
    led = json.loads((st["twin"] / "ledger.json").read_text())["sleeves"]
    assert led["cef"]["shares"]["NAD"] == -50 and led["c4"]["shares"]["NAD"] == 50
    assert verify.verify(d) == 0 and "already verified" in out.getvalue()      # idempotent


def test_after_the_last_slot_a_missing_cross_print_is_unbooked_and_the_next_send_refuses(tmp_path):
    st, w, mk, d, out = crossed_books(tmp_path, {"PDI": 20.0})
    mk.now = F.et(2026, 11, 27, 23, 0, 5)
    assert verify.verify(d) == 1
    u = json.loads((st["twin"] / DAY / verify.UNBOOKED_FILE).read_text())
    assert u["symbols"] == ["NAD"] and "a person" not in u["reason"]
    assert "UNBOOKED" in (st["twin"] / "verify.log").read_text()
    mk.now = F.et(2026, 11, 30, 15, 30, 5)                                     # Monday's send
    assert run.send(d) == run.EXIT_REFUSED and "not booked" in out.getvalue()


def test_a_no_send_session_still_writes_slug_pnl(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, dry_run="1", legacy={"OLD": 10})
    assert run.send(d) == run.EXIT_DRY
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 0
    v = json.loads((st["twin"] / DAY / "verify.json").read_text())
    assert v["recorded"] and v["slug_pnl"]["legacy"] == 10 * PRINTS["OLD"]
    assert verify.verify(d) == 0 and "already verified" in out.getvalue()


def test_a_ledger_changed_after_the_send_is_not_booked(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    assert run.send(d) == 0
    w.fill_all_at(dict(PRINTS), F.et(2026, 11, 27, 12, 59, 50))
    led = json.loads((st["twin"] / "ledger.json").read_text())
    led["sleeves"]["cef"] = {"shares": {}, "cash": 1.0, "stale_sessions": 0}
    (st["twin"] / "ledger.json").write_text(json.dumps(led))
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 1 and "sha differs" in out.getvalue()


# -- 2. a change of side: two orders, the closing one goes whatever happens to the opening one ----

def flip_books(tmp_path):
    st = F.make_states(tmp_path)
    w = F.World()
    w.positions = {"PDI": 60}
    mk = F.FakeMarket(F.et(2026, 11, 27, 12, 30, 5), F.nov_calendar(), prints={"PDI": 20.0})
    F.write_core_plan(st["cef"], "cef", S, A, {"PDI": -40}, {"PDI": 60}, {"PDI": 20.0})
    out = io.StringIO()
    d = F.deps_for(st, w, mk, F.env_for(st, DRY_RUN="0"), out=out)
    assert run.epoch(d) == 0                         # PDI 60 seeded as legacy
    led = json.loads((st["twin"] / "ledger.json").read_text())
    led["sleeves"]["cef"] = {"shares": {"PDI": 60}, "cash": 0.0, "stale_sessions": 0}
    del led["sleeves"]["legacy"]
    (st["twin"] / "ledger.json").write_text(json.dumps(led))
    armed(st)
    return st, w, mk, d, out


def test_a_refused_opening_short_does_not_block_the_closing_leg(tmp_path):
    st, w, mk, d, out = flip_books(tmp_path)
    w.reject_refs = {"twin-20261127-PDI-2"}
    real = F.stub_module(w).IB.placeOrder

    def place(self, con, order):
        t = real(self, con, order)
        if order.orderRef in w.reject_refs:
            w.open.remove(t)
            t.orderStatus.status = "Inactive"
        return t
    d.ibkr = _client_with(w, place=place)
    assert run.send(d) == 0
    assert [(s, o.action, o.totalQuantity, o.orderRef) for _, s, o in w.placed] == [
        ("PDI", "SELL", 60, "twin-20261127-PDI-1"), ("PDI", "SELL", 40, "twin-20261127-PDI-2")]
    assert [o.totalQuantity for o in (t.order for t in w.open)] == [60]       # the close still rests


def test_a_refused_closing_leg_stops_its_opening_leg(tmp_path):
    st, w, mk, d, out = flip_books(tmp_path)
    w.reject = {"PDI"}
    assert run.send(d) == 0
    assert [o.orderRef for _, _, o in w.placed] == ["twin-20261127-PDI-1"]
    assert "skipped_open_leg" in (st["twin"] / DAY / "orders.jsonl").read_text()


def _client_with(w, *, place=None):
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    mod = F.stub_module(w)
    if place is not None:
        mod.IB.placeOrder = place
    c = IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT)
    return lambda mode: IBKRClient(c, mode=mode, ib_module=mod, sleep=lambda s: None)


# -- 3. qualify in the dry path -----------------------------------------------------------------

def test_the_dry_check_names_a_symbol_ibkr_cannot_resolve(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, now=F.et(2026, 11, 28, 11, 0))
    w.unknown_symbols = {"MHD"}
    assert run.send(d, dry=True, session=S) == run.EXIT_DRY and w.placed == []
    assert "[contracts]" in out.getvalue() and "MHD" in out.getvalue()


# -- 4. target integrity for the core and C4 ------------------------------------------------------

def test_a_target_edited_without_an_order_holds_that_book_only(tmp_path):
    st = F.make_states(tmp_path)
    F.write_core_plan(st["cef"], "cef", S, A, {"PDI": 100}, {"PDI": 100}, {"PDI": 20.0})
    p = st["cef"] / DAY / "plan.json"
    plan = json.loads(p.read_text())
    plan["targets"]["PDI"]["target"] = 900                 # not hashed by plan_sha
    p.write_text(json.dumps(plan))
    r = books.read_session_book("cef", st["cef"], S, A)
    assert r.status == "hold" and "PDI" in r.why and "disagree" in r.why


def test_the_plans_own_notes_and_a_deferred_flip_pass_integrity():
    plan = {"targets": {"A": {"current": 5, "target": -5}, "B": {"current": 0, "target": 1},
                        "C": {"current": 0, "target": -3}},
            "orders": [{"symbol": "A", "current": 5, "target": 0, "reason": "flip deferred: closing leg only today"}],
            "notes": {"B": ["no trade: |delta| 1 x 2.0 below min_trade_usd 25"],
                      "C": ["not shortable today: no order sent for C"]}}
    assert books.target_integrity(plan) == []
    plan["notes"] = {}
    assert len(books.target_integrity(plan)) == 2


def test_a_malformed_plan_holds_that_book_and_the_others_trade(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    (st["c4"] / DAY / "plan.json").write_text("{not json")
    assert run.send(d) == 0
    assert "MHD" not in {s for _, s, _ in w.placed} and "PDI" in {s for _, s, _ in w.placed}


# -- 5. one end-to-end send test per guard ----------------------------------------------------------

def test_guard_batch_cutoff_stops_sending_at_close_minus_12(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    t = [F.et(2026, 11, 27, 12, 44, 0)]
    mk.now = t[0]

    def clock_later():
        t[0] = t[0] + dt.timedelta(minutes=2)              # each read of the local clock moves on
        return t[0].astimezone(dt.timezone.utc)
    d.utcnow = clock_later
    assert run.send(d) == run.EXIT_FAIL
    assert len(w.placed) < 5 and "cutoff" in (st["twin"] / DAY / "orders.jsonl").read_text()


def test_guard_started_is_checked_again_under_the_lock(tmp_path, monkeypatch):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    real = guard.transmit_lock.__enter__

    def enter(self):
        started_path(st).write_text("{}")                    # a second process got there first
        return real(self)
    monkeypatch.setattr(guard.transmit_lock, "__enter__", enter)
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []


def test_guard_an_unbooked_earlier_session_refuses(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    old = rec.day_dir(st["twin"], dt.date(2026, 11, 25))
    (old / "STARTED").write_text("{}")
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    assert "not booked" in out.getvalue()


def test_guard_the_order_log_refuses_as_wired(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    day = rec.day_dir(st["twin"], S)
    rec.append_jsonl(day / "orders.jsonl", {"event": "intent", "order_ref": "twin-x", "symbol": "NAD", "side": "buy",
                                            "qty": 1313, "session_date": DAY, "close_et": "2026-11-27T13:00:00-05:00"})
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    assert "order log records 1 order(s)" in out.getvalue()


def test_guard_an_execution_today_refuses(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.executions.append(types.SimpleNamespace(
        execution=types.SimpleNamespace(execId="M1", side="BOT", shares=1.0, price=5.0, permId=1, orderId=1, clientId=0,
                                        orderRef="", acctNumber=F.ACCOUNT, time=F.et(2026, 11, 27, 10, 0)),
        contract=types.SimpleNamespace(symbol="ZZZ", localSymbol="ZZZ", secType="STK", currency="USD"),
        commissionReport=None, time=F.et(2026, 11, 27, 10, 0)))
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    assert "execution(s) on the account today" in out.getvalue()


def test_an_execution_before_midnight_et_is_not_today(tmp_path):
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    w = F.World()
    w.executions.append(types.SimpleNamespace(
        execution=types.SimpleNamespace(execId="Y", side="BOT", shares=1.0, price=5.0, permId=1, orderId=1, clientId=0,
                                        orderRef="", acctNumber=F.ACCOUNT, time=F.et(2026, 11, 26, 23, 59)),
        contract=types.SimpleNamespace(symbol="ZZZ", localSymbol="ZZZ", secType="STK", currency="USD"),
        commissionReport=None, time=F.et(2026, 11, 26, 23, 59)))
    c = IBKRClient(IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT), mode="read", ib_module=F.stub_module(w)).connect()
    assert c.executions_today(since=run.midnight_et(S)) == []


# -- 7, 10, 13, 14 ---------------------------------------------------------------------------------

def test_the_probe_records_memory_in_status(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    assert run.probe(d) == 0
    g = json.loads((st["twin"] / "status.json").read_text())["gateway"]
    assert g["ibgw_memory_peak_bytes"] == 1 and g["mem_available_kb"] == 2


def test_the_epoch_refuses_once_any_set_has_started(tmp_path):
    st = F.make_states(tmp_path)
    (rec.day_dir(st["twin"], S) / "STARTED").write_text("{}")
    d = F.deps_for(st, F.World(), F.FakeMarket(F.et(2026, 11, 28, 11), F.nov_calendar()), F.env_for(st))
    assert run.epoch(d) == run.EXIT_REFUSED and not (st["twin"] / "EPOCH.json").exists()


def test_a_failed_positions_read_still_writes_a_send_record(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.positions = {"OPT": 1}
    real = F.stub_module(w).IB.positions

    def bad_positions(self, account=""):
        return [types.SimpleNamespace(account=F.ACCOUNT, position=1.0, contract=types.SimpleNamespace(
            symbol="OPT", localSymbol="OPT", secType="OPT", currency="USD"))]
    mod = F.stub_module(w)
    mod.IB.positions = bad_positions
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    d.ibkr = lambda mode: IBKRClient(IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT), mode=mode, ib_module=mod)
    assert run.send(d) == run.EXIT_REFUSED
    send = json.loads((st["twin"] / DAY / "send.json").read_text())
    assert send["refusals"][0]["gate"] == "ibkr_read"


@pytest.mark.parametrize("day,close", [(dt.date(2026, 11, 27), "13:00"), (dt.date(2026, 12, 24), "13:00"),
                                       (dt.date(2026, 11, 30), "16:00"), (dt.date(2026, 12, 31), "16:00"),
                                       (dt.date(2026, 7, 2), "16:00"), (dt.date(2027, 7, 2), "16:00"),
                                       (dt.date(2027, 11, 26), "13:00"), (dt.date(2027, 12, 23), "16:00"),
                                       (dt.date(2028, 7, 3), "13:00"), (dt.date(2028, 11, 24), "13:00")])
def test_the_expected_close(day, close):
    """NYSE's dated list (hours-calendars page, read 2026-11-26), not a yearly rule."""
    assert config.expected_close(day) == close


def test_a_year_without_an_early_close_list_refuses():
    with pytest.raises(LookupError, match="no NYSE early-close list for 2029"):
        config.expected_close(dt.date(2029, 1, 2))


def test_a_calendar_close_the_repo_does_not_expect_refuses():
    rows = [dict(r, close="16:00") if r["date"] == S else r for r in F.nov_calendar()]
    with pytest.raises(run.TwinRefused, match="expects 13:00"):
        run.session_for(F.FakeMarket(F.et(2026, 11, 27, 12), rows), S)
