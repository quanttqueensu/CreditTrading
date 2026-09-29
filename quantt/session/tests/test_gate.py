"""gate.py: every refusal, one at a time, from a baseline that passes all nine.

`good()` builds facts on which `evaluate` returns nothing; each test changes ONE
fact and asserts the refusal names the gate it belongs to. That is what makes a
mutation of any single gate visible: the baseline test fails if a gate refuses
too much, and the gate's own test fails if it refuses too little.
"""
import dataclasses
import datetime as dt

import pytest

from quantt.session import gate as gt
from quantt.session.decide import Order

ET = gt.ET
D = dt.date(2026, 9, 29)          # a Tuesday
ASOF = dt.date(2026, 9, 28)
UNI = ("AAA", "BBB", "CCC")


def order(sym, side, qty, leg=1, cur=0, tgt=None, px=10.0):
    if tgt is None:
        tgt = cur + (qty if side == "buy" else -qty)
    return Order(symbol=sym, side=side, qty=qty, leg=leg,
                 client_order_id=f"cef-{D:%Y%m%d}-{sym}-{leg}", current=cur, target=tgt,
                 est_price=px, reason="t")


def good(**over):
    f = gt.GateFacts(
        env_dry_run="0", approve_sha="abc", auto_armed=False, plan_sha="abc",
        halts=[],
        clock_ts=dt.datetime(2026, 9, 29, 8, 30, tzinfo=ET), session_date=D,
        calendar_today=[{"date": D, "open": "09:30", "close": "16:00"}],
        nyse_trading_today=True,
        asof=ASOF, refresh_exit=0, close_dates={s: ASOF for s in UNI},
        nav_dates={s: ASOF for s in UNI},
        started_exists=False, orders_recent=[], orders_open=[], cid_prefix="cef",
        orders=(order("AAA", "buy", 100), order("BBB", "sell", 50)),
        positions={}, shortable={s: True for s in UNI}, shorting_enabled=True,
        closes={"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}, equity=100_000.0,
        buying_power=200_000.0, max_gross_usd=260_000.0, max_gross_stress=1.8,
        universe=UNI,
        account_flags={"trading_blocked": False, "account_blocked": False,
                       "trade_suspended_by_user": False})
    return dataclasses.replace(f, **over)


def gates(f):
    return [r.gate for r in gt.evaluate(f)]


def test_baseline_passes_every_gate():
    assert gt.evaluate(good()) == []


def test_all_nine_are_evaluated_not_just_the_first():
    f = good(env_dry_run="1", approve_sha="nope", halts=[{"reason": "x", "scope": "global"}],
             refresh_exit=4, started_exists=True)
    assert {"dry_run", "arming", "halt", "data", "no_set_in_auction"} <= set(gates(f))


# ------------------------------------------------------------ 1 dry run

@pytest.mark.parametrize("v", [None, "", "1", "false", "False", "no", " 0", "0 ", "00", "O"])
def test_dry_run_everything_but_exact_zero_is_dry(v):
    assert gates(good(env_dry_run=v)) == ["dry_run"]


def test_dry_run_exact_zero_arms():
    assert "dry_run" not in gates(good(env_dry_run="0"))


# -------------------------------------------------------------- 2 arming

def test_approve_mismatch_refuses():
    assert gates(good(approve_sha="deadbeef")) == ["arming"]


def test_approve_mismatch_refuses_even_with_auto_armed():
    assert gates(good(approve_sha="deadbeef", auto_armed=True)) == ["arming"]


def test_auto_armed_arms_without_approve():
    assert gates(good(approve_sha=None, auto_armed=True)) == []


def test_neither_approve_nor_auto_armed_refuses():
    assert gates(good(approve_sha=None, auto_armed=False)) == ["arming"]


# ---------------------------------------------------------------- 3 halt

def test_halt_refuses():
    r = gt.evaluate(good(halts=[{"reason": "manual", "scope": "cef", "path": "ops/HALT_cef.md"}]))
    assert [x.gate for x in r] == ["halt"] and "manual" in r[0].detail


# --------------------------------------------------------------- 4 clock

def test_clock_after_1545_refuses():
    assert gates(good(clock_ts=dt.datetime(2026, 9, 29, 15, 45, tzinfo=ET))) == ["clock"]


def test_clock_1544_passes():
    assert gates(good(clock_ts=dt.datetime(2026, 9, 29, 15, 44, 59, tzinfo=ET))) == []


def test_clock_early_close_uses_calendar_minus_ten():
    cal = [{"date": D, "open": "09:30", "close": "13:00"}]
    assert gates(good(calendar_today=cal,
                      clock_ts=dt.datetime(2026, 9, 29, 12, 50, tzinfo=ET))) == ["clock"]
    assert gates(good(calendar_today=cal,
                      clock_ts=dt.datetime(2026, 9, 29, 12, 49, tzinfo=ET))) == []


def test_clock_is_read_in_et_from_utc():
    # 19:46 UTC = 15:46 EDT
    assert gates(good(clock_ts=dt.datetime(2026, 9, 29, 19, 46,
                                           tzinfo=dt.timezone.utc))) == ["clock"]


def test_clock_evening_run_refuses_next_day_auction():
    # After 19:00 ET Alpaca queues cls for the NEXT day's auction [V].
    assert "clock" in gates(good(clock_ts=dt.datetime(2026, 9, 29, 20, 0, tzinfo=ET)))


# The evening side (team lead 2026-09-29): an order for D's auction may go from
# 19:15 ET on the as-of date. Alpaca rejects cls 15:50-19:00 and queues after
# 19:00 into the next day's auction [V].

def test_clock_evening_of_the_asof_date_passes():
    assert gates(good(clock_ts=dt.datetime(2026, 9, 28, 22, 0, tzinfo=ET))) == []
    assert gates(good(clock_ts=dt.datetime(2026, 9, 29, 0, 30, tzinfo=ET))) == []


def test_clock_evening_window_opens_at_1915_not_before():
    assert gates(good(clock_ts=dt.datetime(2026, 9, 28, 19, 15, tzinfo=ET))) == []
    assert gates(good(clock_ts=dt.datetime(2026, 9, 28, 19, 14, 59, tzinfo=ET))) == ["clock"]


def test_clock_between_asof_close_and_queue_open_refuses():
    # 15:50-19:00 ET Alpaca rejects cls outright [V]
    assert gates(good(clock_ts=dt.datetime(2026, 9, 28, 17, 0, tzinfo=ET))) == ["clock"]


def test_clock_before_the_asof_date_refuses():
    assert gates(good(clock_ts=dt.datetime(2026, 9, 27, 22, 0, tzinfo=ET))) == ["clock"]


def test_clock_friday_evening_for_monday_auction_passes():
    mon, fri = dt.date(2026, 10, 5), dt.date(2026, 10, 2)
    base = dict(session_date=mon, asof=fri,
                calendar_today=[{"date": mon, "open": "09:30", "close": "16:00"}],
                close_dates={s: fri for s in UNI}, nav_dates={s: fri for s in UNI},
                orders=())
    assert gates(good(clock_ts=dt.datetime(2026, 10, 2, 22, 0, tzinfo=ET), **base)) == []
    assert gates(good(clock_ts=dt.datetime(2026, 10, 3, 0, 59, tzinfo=ET), **base)) == []
    assert gates(good(clock_ts=dt.datetime(2026, 10, 5, 0, 0, tzinfo=ET), **base)) == []
    assert gates(good(clock_ts=dt.datetime(2026, 10, 5, 15, 45, tzinfo=ET), **base)) == ["clock"]


def test_clock_refuses_the_daytime_of_an_intervening_non_trading_day():
    # review 2026-09-29: Alpaca documents no cls routing for a Saturday afternoon
    # or a holiday morning [U]; the window is only the as-of evening + session day.
    mon, fri = dt.date(2026, 10, 5), dt.date(2026, 10, 2)
    base = dict(session_date=mon, asof=fri,
                calendar_today=[{"date": mon, "open": "09:30", "close": "16:00"}],
                close_dates={s: fri for s in UNI}, nav_dates={s: fri for s in UNI},
                orders=())
    for t in (dt.datetime(2026, 10, 3, 1, 0, tzinfo=ET), dt.datetime(2026, 10, 3, 16, 30, tzinfo=ET),
              dt.datetime(2026, 10, 4, 22, 0, tzinfo=ET)):
        assert gates(good(clock_ts=t, **base)) == ["clock"], t
    fri_b, wed = dt.date(2026, 11, 27), dt.date(2026, 11, 25)       # Thanksgiving between
    base2 = dict(base, session_date=fri_b, asof=wed,
                 calendar_today=[{"date": fri_b, "open": "09:30", "close": "13:00"}],
                 close_dates={s: wed for s in UNI}, nav_dates={s: wed for s in UNI})
    assert gates(good(clock_ts=dt.datetime(2026, 11, 26, 10, 0, tzinfo=ET), **base2)) == ["clock"]
    assert gates(good(clock_ts=dt.datetime(2026, 11, 25, 22, 0, tzinfo=ET), **base2)) == []


def test_in_send_window_matches_the_gate():
    cut = gt.cutoff_et(D, "16:00")
    assert gt.in_send_window(dt.datetime(2026, 9, 28, 22, 0, tzinfo=ET), ASOF, cut)
    assert gt.in_send_window(dt.datetime(2026, 9, 29, 15, 44, tzinfo=ET), ASOF, cut)
    assert not gt.in_send_window(dt.datetime(2026, 9, 29, 15, 45, tzinfo=ET), ASOF, cut)
    assert not gt.in_send_window(dt.datetime(2026, 9, 28, 19, 0, tzinfo=ET), ASOF, cut)


def test_clock_not_a_trading_day_refuses():
    assert "clock" in gates(good(calendar_today=[], nyse_trading_today=False))


def test_clock_calendars_disagree_refuses():
    assert "clock" in gates(good(nyse_trading_today=False))
    assert "clock" in gates(good(calendar_today=[], nyse_trading_today=True))


def test_clock_wrong_date_refuses():
    assert "clock" in gates(good(clock_ts=dt.datetime(2026, 9, 30, 8, 30, tzinfo=ET)))


# ---------------------------------------------------------------- 5 data

def test_data_refresh_nonzero_refuses():
    assert gates(good(refresh_exit=4)) == ["data"]


def test_data_skip_refresh_still_needs_asof_closes():
    assert gates(good(refresh_exit=None)) == []
    stale = {**{s: ASOF for s in UNI}, "BBB": dt.date(2026, 9, 25)}
    assert gates(good(refresh_exit=None, close_dates=stale)) == ["data"]


def test_data_missing_close_refuses():
    cd = {"AAA": ASOF, "BBB": ASOF}
    assert gates(good(close_dates=cd)) == ["data"]


def test_data_skip_refresh_close_asof_but_nav_a_day_old_refuses():
    # Review 2026-09-28: a close dated as-of with the NAV one day older made the
    # sleeve emit that name FLAT ("below min weight"); --skip-refresh bypasses the
    # fetcher's completeness check, so gate 5 must see the NAV date itself.
    nd = {**{s: ASOF for s in UNI}, "BBB": dt.date(2026, 9, 25)}
    rs = gt.evaluate(good(refresh_exit=None, nav_dates=nd))
    assert [r.gate for r in rs] == ["data"]
    assert "NAV not dated 2026-09-28" in rs[0].detail and "BBB" in rs[0].detail


def test_data_missing_nav_refuses():
    nd = {"AAA": ASOF, "BBB": ASOF, "CCC": None}
    rs = gt.evaluate(good(nav_dates=nd))
    assert [r.gate for r in rs] == ["data"] and "no NAV at all for ['CCC']" in rs[0].detail


def test_data_refresh_timeout_string_refuses():
    rs = gt.evaluate(good(refresh_exit="timed out after 60s"))
    assert [r.gate for r in rs] == ["data"] and "did not complete" in rs[0].detail


# ------------------------------------------------------ 6 no set in auction

def test_started_refuses():
    assert gates(good(started_exists=True)) == ["no_set_in_auction"]


def test_alpaca_order_with_todays_prefix_refuses_even_if_filled():
    o = {"client_order_id": "cef-20260929-AAA-1", "status": "filled",
         "time_in_force": "cls", "symbol": "AAA"}
    assert gates(good(orders_recent=[o])) == ["no_set_in_auction"]


def test_yesterdays_prefix_does_not_refuse():
    o = {"client_order_id": "cef-20260928-AAA-1", "status": "filled",
         "time_in_force": "cls", "symbol": "AAA"}
    assert gates(good(orders_recent=[o])) == []


def test_any_open_non_cls_order_refuses_too():
    o = {"client_order_id": "manual-probe", "status": "new", "time_in_force": "day",
         "symbol": "AAA"}
    assert gates(good(orders_open=[o])) == ["no_set_in_auction"]


def test_any_open_cls_order_refuses():
    o = {"client_order_id": "manual-xyz", "status": "new", "time_in_force": "cls",
         "symbol": "ZZZ"}
    assert gates(good(orders_open=[o])) == ["no_set_in_auction"]


# ------------------------------------------------------- 7 shortability

def test_short_open_on_unshortable_refuses():
    assert gates(good(shortable={"AAA": True, "BBB": False, "CCC": True})) == ["shortability"]


def test_short_open_with_shorting_disabled_refuses():
    assert gates(good(shorting_enabled=False)) == ["shortability"]


def test_cover_on_unshortable_passes():
    f = good(orders=(order("BBB", "buy", 50, cur=-100),), positions={"BBB": -100},
             shortable={"AAA": True, "BBB": False, "CCC": True})
    assert gates(f) == []


# ------------------------------------------------------------ 8 exposure

def test_gross_over_usd_cap_refuses():
    assert gates(good(max_gross_usd=1_000.0)) == ["exposure"]


def test_gross_over_stress_multiple_refuses():
    # gross = 100*10 + 50*20 = 2000; 0.01 * 100000 = 1000
    assert gates(good(max_gross_stress=0.01)) == ["exposure"]


def test_stress_cap_absent_is_not_applied():
    assert gates(good(max_gross_stress=None)) == []


def test_gross_counts_held_positions_after_orders():
    f = good(positions={"CCC": 5000}, max_gross_usd=150_000.0)   # 5000*30 = 150k + 2k
    assert gates(f) == ["exposure"]


def test_buying_power_refuses_with_short_multiplier():
    # need = 100*10 + 50*20*1.03 = 2030
    assert gates(good(buying_power=2029.0)) == ["exposure"]
    assert gates(good(buying_power=2030.0)) == []


def test_closing_orders_consume_no_buying_power():
    f = good(orders=(order("AAA", "sell", 100, cur=100),), positions={"AAA": 100},
             buying_power=0.0)
    assert gates(f) == []


def test_unpriced_position_refuses():
    f = good(positions={"CCC": 10}, closes={"AAA": 10.0, "BBB": 20.0})
    assert gates(f) == ["exposure"]


# -------------------------------------------------------------- 9 sanity

def test_opposite_side_orders_refuse():
    f = good(orders=(order("AAA", "buy", 10), order("AAA", "sell", 5, leg=2)))
    assert "sanity" in gates(f)


def test_non_universe_symbol_refuses():
    o = Order(symbol="ZZZ", side="buy", qty=1, leg=1, client_order_id="cef-20260929-ZZZ-1",
              current=0, target=1, est_price=10.0, reason="t")
    assert "sanity" in gates(good(orders=(o,), closes={"AAA": 10.0, "BBB": 20.0,
                                                        "CCC": 30.0, "ZZZ": 1.0}))


@pytest.mark.parametrize("q", [0, -5, 1.0, True])
def test_non_positive_int_qty_refuses(q):
    o = dataclasses.replace(order("AAA", "buy", 1), qty=q)
    assert "sanity" in gates(good(orders=(o,)))


def test_wrong_date_in_client_id_refuses():
    o = dataclasses.replace(order("AAA", "buy", 1), client_order_id="cef-20260928-AAA-1")
    assert "sanity" in gates(good(orders=(o,)))


def test_stray_position_refuses():
    assert "sanity" in gates(good(positions={"NAD": 10}, closes={"AAA": 10.0, "BBB": 20.0,
                                                                  "CCC": 30.0, "NAD": 5.0}))


@pytest.mark.parametrize("flag", ["trading_blocked", "account_blocked", "trade_suspended_by_user"])
def test_blocked_account_refuses(flag):
    flags = {"trading_blocked": False, "account_blocked": False, "trade_suspended_by_user": False}
    flags[flag] = True
    assert gates(good(account_flags=flags)) == ["sanity"]


def test_refusal_names_a_real_gate():
    with pytest.raises(ValueError):
        gt.Refusal("made_up", "x")
