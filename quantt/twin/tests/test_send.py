"""The twin's send, end to end on fakes, on the first armed session's calendar: Friday 2026-11-27,
a 13:00 early close (Thursday 2026-11-26 is Thanksgiving). Slots 12:30 and 12:40; refused from
12:45; the 15:30 / 15:40 fires that day are after the close and idle."""
from __future__ import annotations

import datetime as dt
import io
import json

import pytest

from quantt.twin import config, run
from quantt.twin.tests import fakes as F

S, A = dt.date(2026, 11, 27), dt.date(2026, 11, 25)
PRINTS = {"PDI": 20.0, "NAD": 12.0, "IWM": 230.0, "OLD": 5.0, "MHD": 11.0}


def world_and_books(tmp_path, *, legacy=None, now=None, dry_run="0", **env):
    st = F.make_states(tmp_path)
    w = F.World()
    if legacy:
        w.positions = dict(legacy)
    mk = F.FakeMarket(now or F.et(2026, 11, 27, 12, 30, 5), F.nov_calendar(), prints=dict(PRINTS),
                      daily={"OLD": 5.1})
    F.write_core_plan(st["cef"], "cef", S, A, {"PDI": 100, "NAD": -50}, {"PDI": 80}, {"PDI": 19.9, "NAD": 12.1})
    F.write_core_plan(st["c4"], "c4", S, A, {"MHD": 30, "NAD": 20}, {}, {"MHD": 11.0, "NAD": 12.1})
    F.write_events_plan(st["events"], S, A, {"specdiv_wait": {"IWM": -10, "PDI": 5}, "pead_small_long": {"IWM": -5}},
                        {}, {"IWM": 229.0, "PDI": 19.9})
    out = io.StringIO()
    d = F.deps_for(st, w, mk, F.env_for(st, DRY_RUN=dry_run, **env), out=out)
    assert run.epoch(d) == 0
    return st, w, mk, d, out


def armed(st):
    (st["twin"] / "AUTO_ARMED").write_text("")


# -- the calendar of the first armed session ------------------------------------------

def test_the_2026_11_27_calendar_gives_the_early_close_times():
    mk = F.FakeMarket(F.et(2026, 11, 27, 12, 0), F.nov_calendar())
    row, asof = run.session_for(mk, S)
    assert row["close"] == "13:00" and asof == A          # Thursday 26 Nov (Thanksgiving) is skipped
    t = config.times(config.close_et(S, row["close"]))
    assert [f"{x:%H:%M}" for x in t["slots"]] == ["12:30", "12:40"]
    assert f"{t['refuse_from']:%H:%M}" == "12:45" and f"{t['stop_batch']:%H:%M}" == "12:48"
    assert run.session_for(mk, dt.date(2026, 11, 26)) == (None, None)


@pytest.mark.parametrize("hm,want", [((12, 24), "early"), ((12, 30), "slot"), ((12, 40), "slot"), ((12, 44), "slot"),
                                     ((12, 45), "too_late"), ((12, 59), "too_late"), ((13, 0), "after_close"),
                                     ((15, 30), "after_close"), ((15, 40), "after_close")])
def test_slots_on_the_early_close(hm, want):
    close = config.close_et(S, "13:00")
    assert config.slot_state(F.et(2026, 11, 27, *hm), close) == want


@pytest.mark.parametrize("hm,want", [((12, 30), "early"), ((12, 40), "early"), ((15, 30), "slot"), ((15, 40), "slot"),
                                     ((15, 45), "too_late"), ((16, 0), "after_close")])
def test_slots_on_a_normal_close(hm, want):
    d = dt.date(2026, 11, 30)
    assert config.slot_state(F.et(2026, 11, 30, *hm), config.close_et(d, "16:00")) == want


def test_calendars_that_disagree_refuse():
    rows = [r for r in F.nov_calendar() if r["date"] != S]          # Alpaca says closed, NYSE rules say open
    with pytest.raises(run.TwinRefused, match="disagree"):
        run.session_for(F.FakeMarket(F.et(2026, 11, 27, 12), rows), S)


# -- the armed send -------------------------------------------------------------------

def test_an_armed_send_writes_started_before_the_first_order_and_sends_moc(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, legacy={"OLD": 10})
    armed(st)
    seen = []
    w.before_place = lambda con, o: seen.append((st["twin"] / "2026-11-27" / "STARTED").exists())
    assert run.send(d) == 0, out.getvalue()
    assert seen and all(seen), "an order went before STARTED"
    got = sorted((s, o.action, o.totalQuantity, o.orderType, o.tif) for _, s, o in w.placed)
    assert got == [("IWM", "SELL", 15, "MOC", "DAY"), ("MHD", "BUY", 30, "MOC", "DAY"), ("NAD", "SELL", 30, "MOC", "DAY"),
                   ("OLD", "SELL", 10, "MOC", "DAY"), ("PDI", "BUY", 105, "MOC", "DAY")]
    st_rec = json.loads((st["twin"] / "2026-11-27" / "STARTED").read_text())
    assert {s["slug"] for s in st_rec["slugs"]} == {"cef", "c4", "events/specdiv_wait", "events/pead_small_long", "legacy"}
    intents = [json.loads(x) for x in (st["twin"] / "2026-11-27" / "orders.jsonl").read_text().splitlines()]
    assert all(r["close_et"].startswith("2026-11-27T13:00") for r in intents if r["event"] == "intent")


def test_the_backup_slot_idles_after_a_finished_send_and_refuses_after_an_unfinished_one(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    assert run.send(d) == 0
    n = len(w.placed)
    mk.now = F.et(2026, 11, 27, 12, 40, 5)
    assert run.send(d) == run.EXIT_IDLE and len(w.placed) == n
    (st["twin"] / "2026-11-27" / "DONE").unlink()            # as if the first send died after STARTED
    assert run.send(d) == run.EXIT_REFUSED and len(w.placed) == n
    assert "STARTED exists" in out.getvalue()


def test_the_backup_refuses_on_an_open_order_it_did_not_place(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    other = F.stub_module(w).IB()
    other.connect("127.0.0.1", 4002, clientId=77)
    con = F.stub_module(w).Stock("NAD", "SMART", "USD")
    o = F.stub_module(w).Order()
    o.action, o.totalQuantity, o.orderType = "BUY", 1313, "MOC"
    other.placeOrder(con, o)
    n = len(w.placed)
    assert run.send(d) == run.EXIT_REFUSED and len(w.placed) == n
    assert "open order(s) on the account" in out.getvalue()


@pytest.mark.parametrize("hm,code", [((12, 46), run.EXIT_REFUSED), ((15, 30), run.EXIT_IDLE), ((15, 40), run.EXIT_IDLE),
                                     ((12, 20), run.EXIT_IDLE)])
def test_outside_the_slots_nothing_is_sent(tmp_path, hm, code):
    st, w, mk, d, out = world_and_books(tmp_path, now=F.et(2026, 11, 27, *hm))
    armed(st)
    assert run.send(d) == code and w.placed == []


def test_dry_run_1_always_wins(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, dry_run="1")
    armed(st)
    assert run.send(d) == run.EXIT_DRY and w.placed == []
    assert all(c.readonly for c in w.connections), "a dry send opened a trading session"
    assert (st["twin"] / "2026-11-27" / "DRY_DONE").exists()


def test_staging_never_transmits_even_armed_with_dry_run_0(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, **{config.ENV_STAGING: "1"})
    armed(st)
    assert run.send(d) == run.EXIT_DRY and w.placed == []
    assert "[staging]" in out.getvalue()


def test_the_dry_check_sends_nothing_whatever_dry_run_says_on_any_day(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path, now=F.et(2026, 11, 28, 11, 0))      # Saturday
    armed(st)
    assert run.send(d, dry=True, session=S) == run.EXIT_DRY and w.placed == []
    txt = out.getvalue()
    assert "plan_sha" in txt and "MOC order(s)" in txt and "nothing was transmitted" in txt


def test_the_dry_check_simulates_the_epoch_when_none_is_recorded(tmp_path):
    st = F.make_states(tmp_path)
    w = F.World()
    w.positions = {"OLD": 10}
    mk = F.FakeMarket(F.et(2026, 11, 28, 11, 0), F.nov_calendar(), prints=dict(PRINTS), daily={"OLD": 5.1})
    F.write_core_plan(st["cef"], "cef", S, A, {"PDI": 1}, {}, {"PDI": 20.0})
    out = io.StringIO()
    d = F.deps_for(st, w, mk, F.env_for(st, DRY_RUN="0"), out=out)
    assert run.send(d, dry=True, session=S) == run.EXIT_DRY and w.placed == []
    assert "SIMULATED" in out.getvalue() and "OLD" in out.getvalue()


def test_not_armed_is_dry(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    assert run.send(d) == run.EXIT_DRY and w.placed == []
    assert "[arming]" in out.getvalue()


def test_an_approval_must_name_exactly_the_list_sent(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    assert run.approve(d, sha="0" * 64) == 0
    assert run.send(d) == run.EXIT_DRY and w.placed == []          # wrong sha: arming refuses
    sha = json.loads((st["twin"] / "2026-11-27" / "plan.json").read_text())["plan_sha"]
    (st["twin"] / "2026-11-27" / "DRY_DONE").unlink()
    assert run.approve(d, sha=sha) == 0
    assert run.send(d) == 0 and w.placed


def test_a_logged_out_gateway_is_a_refused_missed_session_shown_in_status(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.reachable = False
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    s = json.loads((st["twin"] / "status.json").read_text())
    assert s["gateway"]["logged_in"] is False


def test_buying_power_short_of_the_need_refuses_and_records_the_factor(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.bp = 3000.0
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    plan = json.loads((st["twin"] / "2026-11-27" / "plan.json").read_text())
    assert plan["buying_power"]["factor_needed"] < 1 and "fit.py" in out.getvalue()


def test_a_ledger_that_disagrees_with_ibkr_refuses(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.positions["PDI"] = 7                       # something traded the account that the twin did not book
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []
    assert "[ledger]" in out.getvalue()


def test_a_halted_book_holds_and_the_others_trade(tmp_path, monkeypatch):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    (st["events"] / "HALT").write_text("stop\n")
    assert run.send(d) == 0
    syms = {s for _, s, _ in w.placed}
    assert "IWM" not in syms and {"PDI", "NAD", "MHD"} <= syms


def test_a_twin_halt_refuses_everything(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    (st["twin"] / "HALT").write_text("stop\n")
    assert run.send(d) == run.EXIT_REFUSED and w.placed == []


def test_a_rejected_short_is_skipped_and_the_rest_go(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.reject = {"IWM"}
    assert run.send(d) == 0
    send = json.loads((st["twin"] / "2026-11-27" / "send.json").read_text())
    assert [r["symbol"] for r in send["rejected"]] == ["IWM"] and send["rejected"][0]["opens_short"]
    assert send["sent"] == 3


def test_an_unacknowledged_order_stops_the_batch_and_is_never_resent(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    w.silent = {"PDI"}
    t = [0.0]

    def mono():
        t[0] += 1.0
        return t[0]
    from quantt.broker.ibkr import IBKRClient, IBKRConfig
    mod = F.stub_module(w)
    c = IBKRConfig("127.0.0.1", 4002, 31, F.ACCOUNT)
    d.ibkr = lambda mode: IBKRClient(c, mode=mode, ib_module=mod, sleep=lambda s: None, monotonic=mono)
    assert run.send(d) == run.EXIT_FAIL
    assert [s for _, s, _ in w.placed].count("PDI") == 1
    mk.now = F.et(2026, 11, 27, 12, 40, 5)
    n = len(w.placed)
    assert run.send(d) == run.EXIT_REFUSED and len(w.placed) == n


def test_the_state_directory_must_be_the_twins(tmp_path):
    st, w, mk, d, out = world_and_books(tmp_path)
    d.state = st["cef"]
    assert run.send(d) == run.EXIT_REFUSED


def test_a_halt_corporate_action_mode_holds_the_book(tmp_path, monkeypatch):
    st, w, mk, d, out = world_and_books(tmp_path)
    armed(st)
    from quantt.twin import books
    monkeypatch.setattr(books, "ca_mode", lambda name, clone: "halt" if name == "cef" else None)
    monkeypatch.setattr(run, "_ca_gate", lambda *a, **k: ({"status": "BLOCKING", "mode": "halt"},
                                                          "corporate-action gate (halt): a split"))
    assert run.send(d) == 0
    plan = json.loads((st["twin"] / "2026-11-27" / "plan.json").read_text())
    assert plan["books"]["cef"]["status"] == "hold"
    assert "PDI" in {s for _, s, _ in w.placed}            # events still buys its PDI
