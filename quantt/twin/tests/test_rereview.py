"""The re-review of the twin (2026-11-25) and the switch branch's review: one test or more per item,
each end to end on fakes. Each was also run on a scratch copy with its fix removed and failed there."""
from __future__ import annotations

import datetime as dt
import io
import json
import types

import pytest

from quantt.session import records as rec
from quantt.twin import books, run, verify
from quantt.twin.tests import fakes as F
from quantt.twin.tests.test_review_fixes import crossed_books
from quantt.twin.tests.test_send import A, S, armed, world_and_books

DAY = "2026-11-27"


def halt(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# HALT\n## 2026-11-27  stop for the test\n")


# -- 1. a saved read is never overwritten; a past session never reads IBKR ------------------------

def test_a_saved_read_is_never_overwritten_and_ibkr_is_not_asked_again(tmp_path):
    st, w, mk, d, out = crossed_books(tmp_path, {"PDI": 20.0})
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 1 and "PENDING" in out.getvalue()
    saved = (st["twin"] / DAY / verify.READ_FILE).read_bytes()
    n = len(w.connections)
    w.executions.append(w.executions[0])                       # something later at IBKR must not be seen
    mk.prints["NAD"] = 12.0
    mk.now = F.et(2026, 11, 27, 18, 30, 5)
    assert verify.verify(d) == 0, out.getvalue()
    assert (st["twin"] / DAY / verify.READ_FILE).read_bytes() == saved
    assert len(w.connections) == n, "IBKR was read again although a read was saved"


def test_a_reboot_that_missed_the_evening_slots_is_caught_up_next_morning_from_the_saved_read(tmp_path):
    st, w, mk, d, out = crossed_books(tmp_path, {"PDI": 20.0})
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 1                                # PENDING: NAD's print not in yet
    mk.prints["NAD"] = 12.0                                      # 18:30, 20:30, 23:00 missed (a reboot)
    n = len(w.connections)
    w.executions.append(types.SimpleNamespace(                  # Monday's execution: never F's
        execution=types.SimpleNamespace(execId="MON", side="BOT", shares=1.0, price=5.0, permId=777, orderId=9,
                                        clientId=0, orderRef="", acctNumber=F.ACCOUNT, time=F.et(2026, 11, 30, 6, 0)),
        contract=types.SimpleNamespace(symbol="ZZZ", localSymbol="ZZZ", secType="STK", currency="USD"),
        commissionReport=None, time=F.et(2026, 11, 30, 6, 0)))
    mk.now = F.et(2026, 11, 30, 7, 0, 5)                         # Monday's 07:00 timer run
    assert verify.verify(d) == 0, out.getvalue()
    assert len(w.connections) == n
    v = json.loads((st["twin"] / DAY / "verify.json").read_text())
    assert v["ledger_applied"] and v["ibkr_read"].startswith("saved")
    assert "not yet" in out.getvalue()                           # Monday's own session is not over


# -- 2. halts and settings from the books' clone ---------------------------------------------------

def test_a_global_halt_in_the_books_clone_stops_the_whole_twin(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    halt(st["books_clone"] / "ops" / "HALT.md")
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    assert "books_clone/ops/HALT.md" in out.getvalue()


def test_a_twin_halt_in_its_own_clone_stops_it(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    halt(st["own_clone"] / "ops" / "HALT_twin.md")
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []


def test_a_book_halt_in_the_books_clone_holds_that_book_only(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    halt(st["books_clone"] / "ops" / "HALT_c4.md")
    assert run.send(d) == 0
    syms = {s for _, s, _ in w.placed}
    assert "MHD" not in syms and {"PDI", "IWM"} <= syms


def test_the_books_clone_is_required(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    del d.env["QUANTT_BOOKS_CLONE"]
    assert run.send(d) == run.EXIT_REFUSED and "QUANTT_BOOKS_CLONE" in out.getvalue()


def test_the_events_minimum_and_the_ca_mode_come_from_the_books_clone(tmp_path):
    st = F.make_states(tmp_path)
    bc = st["books_clone"]
    p = bc / "ops/sleeves/events_sleeves.json"
    ev = json.loads(p.read_text())
    ev["min_order_usd"] = 1000
    p.write_text(json.dumps(ev))
    assert run.events_min_usd(bc) == 1000.0
    q = bc / "ops/books/cef_discount_book.json"
    cb = json.loads(q.read_text())
    cb["corporate_actions"]["mode"] = "halt"
    q.write_text(json.dumps(cb))
    assert books.ca_mode("cef", bc) == "halt"


def test_the_events_minimum_as_wired_in_the_send(tmp_path):
    """Events wants +1 PDI ($19.90 < the events book's $25): no events order; the core's PDI goes."""
    st = F.make_states(tmp_path)
    w = F.World()
    mk = F.FakeMarket(F.et(2026, 11, 27, 12, 30, 5), F.nov_calendar(), prints={"PDI": 20.0, "IWM": 230.0})
    F.write_events_plan(st["events"], S, A, {"specdiv_wait": {"PDI": 1, "IWM": -10}}, {}, {"PDI": 19.9, "IWM": 229.0})
    out = io.StringIO()
    d = F.deps_for(st, w, mk, F.env_for(st, DRY_RUN="0"), out=out)
    assert run.epoch(d) == 0
    armed(st)
    assert run.send(d) == 0, out.getvalue()
    assert [s for _, s, _ in w.placed] == ["IWM"]
    plan = json.loads((st["twin"] / DAY / "plan.json").read_text())
    assert plan["events_below_minimum"] == ["PDI"]


# -- 3. the allocation when the second leg fails ------------------------------------------------------

def test_a_refused_second_leg_leaves_legacy_cef_and_the_account_flat(tmp_path):
    """legacy +200 NAD, cef targets -50: leg 1 SELL 200 fills, leg 2 refused -> legacy 0, cef 0, account 0."""
    st = F.make_states(tmp_path)
    w = F.World()
    w.positions = {"NAD": 200}
    mk = F.FakeMarket(F.et(2026, 11, 27, 12, 30, 5), F.nov_calendar(), prints={"NAD": 12.0})
    F.write_core_plan(st["cef"], "cef", S, A, {"NAD": -50}, {}, {"NAD": 12.1})
    out = io.StringIO()
    d = F.deps_for(st, w, mk, F.env_for(st, DRY_RUN="0"), out=out)
    assert run.epoch(d) == 0
    armed(st)
    mod = F.stub_module(w)
    real = mod.IB.placeOrder

    def place(self, con, order):
        t = real(self, con, order)
        if order.orderRef.endswith("-2"):
            w.open.remove(t)
            t.orderStatus.status = "Inactive"
        return t
    mod.IB.placeOrder = place
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    d.ibkr = lambda mode: IBKRClient(IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT), mode=mode, ib_module=mod,
                                     sleep=lambda s: None)
    assert run.send(d) == 0, out.getvalue()
    w.fill_all_at({"NAD": 11.98}, F.et(2026, 11, 27, 12, 59, 50))
    assert w.positions == {}
    mk.now = F.et(2026, 11, 27, 17, 45, 5)
    assert verify.verify(d) == 0, out.getvalue()
    led = json.loads((st["twin"] / "ledger.json").read_text())["sleeves"]
    assert led["legacy"]["shares"] == {} and led.get("cef", {"shares": {}})["shares"] == {}


# -- 5. the buying-power fit relaxes only its own opening symbols ---------------------------------------

def test_a_binding_fit_excuses_only_an_opening_symbol_without_an_order():
    plan = {"bp_scale": {"binding": "buying_power"}, "orders": [], "notes": {},
            "targets": {"OPEN": {"current": 0, "target": 10}, "CUT": {"current": 10, "target": 0}}}
    bad = books.target_integrity(plan)
    assert len(bad) == 1 and bad[0].startswith("CUT")


# -- the books' own arming (rule 4 at the twin) ------------------------------------------------------

def test_a_book_whose_own_send_is_dry_holds_only_its_slugs(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    env = dict(F.UNIT_ENV, **{"quantt-cef-session.service": "DRY_RUN=1 QUANTT_STATE_DIR=/x"})
    d.unit_env = lambda unit: env[unit]
    assert run.send(d) == 0
    syms = {s for _, s, _ in w.placed}
    assert "NAD" not in {s for _, s, o in w.placed if o.action == "SELL" and o.totalQuantity == 70}
    plan = json.loads((st["twin"] / DAY / "plan.json").read_text())
    assert plan["books"]["cef"]["status"] == "hold" and "DRY_RUN=1" in plan["books"]["cef"]["why"]
    assert "rule 4" in plan["books"]["cef"]["why"] and {"MHD", "IWM"} <= syms


def test_a_book_without_its_own_auto_armed_holds(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    (st["c4"] / "AUTO_ARMED").unlink()
    assert run.send(d) == 0
    assert "MHD" not in {s for _, s, _ in w.placed}
    plan = json.loads((st["twin"] / DAY / "plan.json").read_text())
    assert "AUTO_ARMED" in plan["books"]["c4"]["why"]


def test_a_book_halted_by_its_state_file_holds(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    (st["events"] / "HALT").write_text("why\n")
    assert run.send(d) == 0
    assert "IWM" not in {s for _, s, _ in w.placed}


def test_an_unreadable_send_unit_holds_its_book_named_and_nothing_is_guessed(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)

    def unit_env(unit):
        if unit == "quantt-events-send.service":
            raise RuntimeError("systemctl show exited 1")
        return F.UNIT_ENV[unit]
    d.unit_env = unit_env
    assert run.send(d) == 0
    plan = json.loads((st["twin"] / DAY / "plan.json").read_text())
    assert plan["books"]["events"]["status"] == "hold" and "could not be read" in plan["books"]["events"]["why"]
    assert "IWM" not in {s for _, s, _ in w.placed}


def test_the_send_units_are_the_installers_names():
    from pathlib import Path
    assert books.send_unit("cef") == "quantt-cef-session.service"
    assert books.send_unit("c4") == "quantt-c4-session.service"
    script = (Path(__file__).resolve().parents[3] / "quantt/sleeves/deploy/install_events_vm.sh").read_text()
    assert f" {books.EVENTS_SEND_UNIT} " in script.split('SERVICES="', 1)[1].split('"', 1)[0].join("  ")
