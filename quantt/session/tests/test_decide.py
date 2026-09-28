"""decide.py: the promises that turn weights into shares without drift or guessing.

Each test pins one rule from decide.py's docstring that a plausible edit would
break silently: rounding to nearest instead of toward zero, re-sizing a band
HOLD through a price (the 2026-09-08 dust orders), sending both flip legs in
one session against Alpaca's verified guidance, shorting an unshortable name,
or a plan_sha that moves with prose instead of with what is sent.
"""
import datetime as dt
import json

import pytest

from quantt.session import decide as dec
from src.deploy.sleeve import FLAT, LONG, SHORT, PositionTarget

D = dt.date(2026, 9, 29)
UNI = ("AAA", "BBB", "CCC")


def T(sym, side=FLAT, *, w=None, q=None, reason="r"):
    return PositionTarget(instrument=sym, side=side, weight=w, qty=q, reason=reason)


def run(targets, positions=None, equity=100_000.0, closes=None, shortable=None, **kw):
    closes = closes if closes is not None else {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}
    shortable = shortable if shortable is not None else {s: True for s in UNI}
    kw.setdefault("min_trade_usd", 0.0)
    return dec.decide(targets, positions or {}, equity, closes, shortable,
                      session_date=D, universe=UNI, cid_prefix="cef", **kw)


def flat_rest(*ts):
    have = {t.instrument for t in ts}
    return list(ts) + [T(s) for s in UNI if s not in have]


# ---------------------------------------------------------------- sizing

def test_weight_rounds_toward_zero_both_sides():
    # 0.1 * 100000 / 30 = 333.33 -> 333 ; -0.1 * 100000 / 30 = -333.33 -> -333.
    # 0.0299 * 100000 / 10 = 299.0 -> 299; 0.02999*1e5/10 = 299.9 -> 299 (not 300).
    d = run(flat_rest(T("CCC", LONG, w=0.1), T("AAA", LONG, w=0.02999),
                      T("BBB", SHORT, w=-0.0333333)))
    tg = {s: v["target"] for s, v in d.targets.items()}
    assert tg == {"AAA": 299, "BBB": -166, "CCC": 333}


def test_short_rounds_toward_zero_not_floor():
    # -0.1*1e5/30 = -333.33: floor would give -334 (sells a share past its weight).
    d = run(flat_rest(T("CCC", SHORT, w=-0.1)))
    (o,) = d.orders
    assert (o.side, o.qty) == ("sell", 333)


def test_side_weight_sign_conflict_raises():
    # PositionTarget's constructor checks only a qty's sign; decide checks the weight's.
    with pytest.raises(dec.DecisionError, match="disagrees"):
        run(flat_rest(T("AAA", LONG, w=-0.05)))


def test_missing_close_for_weight_target_raises_naming_it():
    with pytest.raises(dec.DecisionError, match="BBB"):
        run(flat_rest(T("BBB", LONG, w=0.05)), closes={"AAA": 10.0, "CCC": 30.0})


def test_equity_must_be_positive_measured():
    for bad in (0.0, -1.0, float("nan"), None, True):
        with pytest.raises(dec.DecisionError):
            run(flat_rest(), equity=bad)


# ------------------------------------------------------- holds and netting

def test_qty_hold_is_exact_and_sends_nothing_even_if_price_moved():
    # A band HOLD of -137 against a holding of -137 must produce no order no
    # matter what close is passed -- a weight round trip would not.
    d = run(flat_rest(T("AAA", SHORT, q=-137)), positions={"AAA": -137},
            closes={"AAA": 12.3456, "BBB": 20.0, "CCC": 30.0})
    assert d.orders == ()
    assert d.targets["AAA"]["kind"] == "qty"


def test_qty_hold_needs_no_close():
    d = run(flat_rest(T("AAA", LONG, q=50)), positions={"AAA": 50},
            closes={"BBB": 20.0, "CCC": 30.0})
    assert d.orders == ()


def test_fractional_qty_target_raises():
    with pytest.raises(dec.DecisionError, match="whole"):
        run(flat_rest(T("AAA", LONG, q=10.5)), positions={"AAA": 10})


def test_one_netted_order_per_symbol():
    d = run(flat_rest(T("AAA", LONG, w=0.05)), positions={"AAA": 200})
    (o,) = d.orders          # 500 target - 200 held
    assert (o.symbol, o.side, o.qty, o.leg, o.client_order_id) == \
        ("AAA", "buy", 300, 1, "cef-20260929-AAA-1")


def test_flat_target_closes_whole_position():
    d = run(flat_rest(), positions={"BBB": -40})
    (o,) = d.orders
    assert (o.symbol, o.side, o.qty) == ("BBB", "buy", 40)


def test_min_trade_usd_drops_small_delta_strictly_below():
    # delta 1 share of AAA at 10 = $10. min 10 -> kept (not strictly below); 10.01 -> dropped.
    ts = flat_rest(T("AAA", LONG, q=101))
    assert len(run(ts, positions={"AAA": 100}, min_trade_usd=10.0).orders) == 1
    d = run(ts, positions={"AAA": 100}, min_trade_usd=10.01)
    assert d.orders == () and "min_trade_usd" in d.notes["AAA"][0]


# ------------------------------------------------------------------- flips

def test_flip_default_is_deferred_closing_leg_only():
    assert dec.FLIP_SAME_SESSION is False
    d = run(flat_rest(T("AAA", SHORT, w=-0.05)), positions={"AAA": 120})
    (o,) = d.orders
    assert (o.side, o.qty, o.leg, o.target) == ("sell", 120, 1, 0)
    assert o.client_order_id == "cef-20260929-AAA-1"
    assert any(n.startswith("flip deferred") for n in d.notes["AAA"])


def test_flip_deferred_short_to_long():
    d = run(flat_rest(T("BBB", LONG, w=0.05)), positions={"BBB": -30})
    (o,) = d.orders
    assert (o.side, o.qty, o.target) == ("buy", 30, 0)


def test_flip_same_session_two_legs_same_side():
    d = run(flat_rest(T("AAA", SHORT, w=-0.05)), positions={"AAA": 120},
            flip_same_session=True)
    assert [(o.leg, o.side, o.qty, o.client_order_id) for o in d.orders] == [
        (1, "sell", 120, "cef-20260929-AAA-1"), (2, "sell", 500, "cef-20260929-AAA-2")]


# ------------------------------------------------------------ shortability

def test_not_shortable_open_short_sends_nothing_and_logs():
    d = run(flat_rest(T("AAA", SHORT, w=-0.05), T("BBB", LONG, w=0.05)),
            shortable={"AAA": False, "BBB": True, "CCC": True})
    assert [o.symbol for o in d.orders] == ["BBB"]
    assert any("not shortable" in n for n in d.notes["AAA"])


def test_not_shortable_increase_short_blocked_but_cover_allowed():
    sh = {"AAA": False, "BBB": False, "CCC": True}
    d = run(flat_rest(T("AAA", SHORT, q=-80), T("BBB", SHORT, q=-20)),
            positions={"AAA": -50, "BBB": -50}, shortable=sh)
    assert [(o.symbol, o.side, o.qty) for o in d.orders] == [("BBB", "buy", 30)]


def test_deferred_flip_to_short_needs_no_shortable():
    # The only order today closes the long; nothing opens a short.
    d = run(flat_rest(T("AAA", SHORT, w=-0.05)), positions={"AAA": 120},
            shortable={"AAA": False, "BBB": True, "CCC": True})
    assert [(o.symbol, o.side, o.qty) for o in d.orders] == [("AAA", "sell", 120)]


def test_same_session_flip_to_unshortable_sends_nothing_for_symbol():
    d = run(flat_rest(T("AAA", SHORT, w=-0.05)), positions={"AAA": 120},
            shortable={"AAA": False, "BBB": True, "CCC": True}, flip_same_session=True)
    assert d.orders == ()


def test_unmeasured_shortable_raises():
    with pytest.raises(dec.DecisionError, match="AAA"):
        run(flat_rest(T("AAA", SHORT, w=-0.05)), shortable={"BBB": True})


def test_shortable_must_be_bool():
    with pytest.raises(dec.DecisionError, match="bool"):
        run(flat_rest(T("AAA", SHORT, w=-0.05)), shortable={"AAA": 1, "BBB": True, "CCC": True})


# ----------------------------------------------------- targets completeness

def test_missing_target_raises_not_flat():
    with pytest.raises(dec.DecisionError, match="no target"):
        run([T("AAA"), T("BBB")])


def test_non_universe_target_raises():
    with pytest.raises(dec.DecisionError, match="not in the frozen universe"):
        run(flat_rest(T("ZZZ", LONG, w=0.1)))


def test_duplicate_target_raises():
    with pytest.raises(dec.DecisionError, match="two targets"):
        run(flat_rest(T("AAA"), T("AAA")))


# --------------------------------------------------------------- plan_sha

def _book():
    return flat_rest(T("AAA", LONG, w=0.05), T("BBB", SHORT, w=-0.05), T("CCC", LONG, w=0.02))


def test_plan_sha_deterministic_and_order_is_the_transmit_sequence():
    a = run(_book())
    b = run(list(reversed(_book())))
    assert a.plan_sha == b.plan_sha
    assert a.orders == dec.transmit_sequence(a.orders)


def test_transmit_sequence_keeps_running_net_near_zero_not_alphabetical():
    # Review 2026-09-28: alphabetical order + stop-on-first-failure left an
    # arbitrary one-sided slice. Longs A,B,C and shorts X,Y,Z of equal notional
    # must alternate, SELL first on a tie, so any stopping point is within one
    # order of neutral.
    uni = ("A", "B", "C", "X", "Y", "Z")
    ts = [T("A", LONG, w=0.05), T("B", LONG, w=0.05), T("C", LONG, w=0.05),
          T("X", SHORT, w=-0.05), T("Y", SHORT, w=-0.05), T("Z", SHORT, w=-0.05)]
    d = dec.decide(ts, {}, 100_000.0, {s: 10.0 for s in uni}, {s: True for s in uni},
                   session_date=D, universe=uni, cid_prefix="cef", min_trade_usd=0.0)
    assert [(o.symbol, o.side) for o in d.orders] == [
        ("X", "sell"), ("A", "buy"), ("Y", "sell"), ("B", "buy"), ("Z", "sell"), ("C", "buy")]
    net, worst = 0.0, 0.0
    for o in d.orders:
        net += o.signed_qty * o.est_price
        worst = max(worst, abs(net))
    assert worst == pytest.approx(5000.0)


def test_transmit_sequence_never_puts_flip_leg2_before_leg1():
    # leg 2 is the smaller notional, so the net rule alone would send it first
    a = dec.Order("AAA", "sell", 90, 1, "cef-20260929-AAA-1", 90, 0, 10.0, "r")
    b = dec.Order("AAA", "sell", 10, 2, "cef-20260929-AAA-2", 0, -10, 10.0, "r")
    c = dec.Order("BBB", "buy", 50, 1, "cef-20260929-BBB-1", 0, 50, 10.0, "r")
    seq = dec.transmit_sequence([b, c, a])
    ids = [o.client_order_id for o in seq]
    assert ids.index("cef-20260929-AAA-1") < ids.index("cef-20260929-AAA-2")


def test_plan_sha_ignores_prose_but_not_what_is_sent():
    a = run(_book())
    prose = [PositionTarget(t.instrument, t.side, weight=t.weight, qty=t.qty,
                            reason="different words") for t in _book()]
    assert run(prose).plan_sha == a.plan_sha
    # one share different (equity nudged so AAA 500 -> 501) changes the hash
    assert run(_book(), equity=100_200.0).plan_sha != a.plan_sha
    # another session date changes the ids and the hash
    other = dec.decide(_book(), {}, 100_000.0, {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0},
                       {s: True for s in UNI}, session_date=D + dt.timedelta(days=1),
                       universe=UNI, cid_prefix="cef", min_trade_usd=0.0)
    assert other.plan_sha != a.plan_sha


def test_plan_sha_is_sha256_of_canonical_wire_json():
    import hashlib
    a = run(_book())
    canon = json.dumps([o.wire() for o in a.orders], sort_keys=True, separators=(",", ":"))
    assert a.plan_sha == hashlib.sha256(canon.encode()).hexdigest()
    assert all(o.wire()["type"] == "market" and o.wire()["time_in_force"] == "cls"
               for o in a.orders)


def test_orders_are_positive_ints():
    for o in run(_book()).orders:
        assert type(o.qty) is int and o.qty > 0


def test_universe_and_target_order_do_not_change_the_list():
    a = run(_book())
    b = dec.decide(list(reversed(_book())), {}, 100_000.0,
                   {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}, {s: True for s in UNI},
                   session_date=D, universe=tuple(reversed(UNI)), cid_prefix="cef",
                   min_trade_usd=0.0)
    assert [o.client_order_id for o in b.orders] == [o.client_order_id for o in a.orders]
    assert b.plan_sha == a.plan_sha
