"""E1's event helpers in band_frontier.py (`event_hold`, `event_turnover`), on synthetic inputs.

Each claim is about the code (CLAUDE.md: synthetic data tests a method, never the
market). PREREG_E1 §6.4 declares both helpers and what each must refuse:

* a leg decided on the session before its fill earns from the session after the
  fill (shift(2) through `evaluate()`), and its last earned return is two
  sessions after its last decision row;
* a leg whose fill is not strictly after its announcement raises (lookahead);
* a NaN weight, a row outside the calendar, and a last row before the first raise;
* legs on one permno are summed (an acquirer in two groups is netted);
* a conversion is not charged as two trades: only the residual is, and a
  genuine trade on the same row on the same acquirer is still charged.

The lookahead test was checked to fail against a helper that tested `fill >=
ann` instead of `fill > ann` (2026-10-19, by editing the comparison locally).
"""
import numpy as np
import pandas as pd
import pytest

from scripts.cef import band_frontier as bf


def _cal():
    return pd.bdate_range("2021-03-01", "2021-03-31")


def _leg(p, first, last, w, ann):
    return {"permno": p, "first": pd.Timestamp(first), "last": pd.Timestamp(last), "weight": w,
            "ann": pd.Timestamp(ann)}


def test_leg_earns_from_the_session_after_its_fill():
    cal = _cal()
    # Announced Friday 03-05; decided that evening (row 03-05); fills at the close
    # of Monday 03-08; earns Tuesday 03-09 onward. Last decision row 03-17, so the
    # last return earned is that of 03-19 (two sessions later).
    H = bf.event_hold([_leg(1, "2021-03-05", "2021-03-17", 0.5, "2021-03-05")], cal)
    R = pd.DataFrame({1: 0.01}, index=cal)
    pnl = bf.evaluate(H, R)["pnl"]
    assert pnl.loc[:"2021-03-08"].abs().sum() == 0.0
    assert pnl.loc["2021-03-09"] == pytest.approx(0.005)
    assert pnl.loc["2021-03-19"] == pytest.approx(0.005)
    assert pnl.loc["2021-03-22":].abs().sum() == 0.0
    assert int((pnl != 0).sum()) == 9            # 03-09 .. 03-19 inclusive


def test_fill_on_the_announcement_day_raises():
    cal = _cal()
    # Decided on 03-04 fills at the close of 03-05, the announcement day itself:
    # that trades on a filing at a close it may have followed.
    with pytest.raises(AssertionError, match="lookahead"):
        bf.event_hold([_leg(1, "2021-03-04", "2021-03-10", 1.0, "2021-03-05")], cal)
    # A weekend announcement: the decision row is Friday, the fill Monday, after A.
    H = bf.event_hold([_leg(1, "2021-03-05", "2021-03-10", 1.0, "2021-03-06")], cal)
    assert H.loc["2021-03-05", 1] == 1.0


@pytest.mark.parametrize("leg, match", [
    (dict(permno=1, first="2021-03-05", last="2021-03-10", weight=np.nan, ann="2021-03-04"), "NaN"),
    (dict(permno=1, first="2021-03-06", last="2021-03-10", weight=1.0, ann="2021-03-04"), "outside"),
    (dict(permno=1, first="2021-03-10", last="2021-03-05", weight=1.0, ann="2021-03-04"), "before"),
    (dict(permno=1, first="2021-03-31", last="2021-03-31", weight=1.0, ann="2021-03-04"), "last session"),
])
def test_bad_legs_raise(leg, match):
    leg = {k: (pd.Timestamp(v) if k in ("first", "last", "ann") else v) for k, v in leg.items()}
    with pytest.raises(ValueError, match=match):
        bf.event_hold([leg], _cal())


def test_legs_on_one_permno_are_summed():
    cal = _cal()
    H = bf.event_hold([_leg(9, "2021-03-05", "2021-03-12", -0.5, "2021-03-04"),
                       _leg(9, "2021-03-10", "2021-03-19", -0.25, "2021-03-09"),
                       _leg(1, "2021-03-05", "2021-03-12", 0.5, "2021-03-04")], cal)
    assert H.loc["2021-03-09", 9] == -0.5
    assert H.loc["2021-03-11", 9] == -0.75
    assert H.loc["2021-03-15", 9] == -0.25
    assert H.loc["2021-03-22", 9] == 0.0


def test_conversion_is_charged_the_residual_not_two_legs():
    cal = _cal()
    legs = [_leg(1, "2021-03-05", "2021-03-17", 0.5, "2021-03-04"),
            _leg(9, "2021-03-05", "2021-03-17", -0.5, "2021-03-04")]
    H = bf.event_hold(legs, cal)
    conv = pd.DataFrame([{"row": pd.Timestamp("2021-03-18"), "target": 1, "acquirer": 9,
                          "weight": 0.5, "residual": 0.004}])
    t = bf.event_turnover(H, conv)
    assert t.loc["2021-03-05"] == pytest.approx(1.0)       # entry: both legs
    assert t.loc["2021-03-18"] == pytest.approx(0.004)     # conversion: the residual only
    assert t.sum() == pytest.approx(1.004)
    # evaluate()'s own turnover would charge the exit as 1.0 more
    assert bf.evaluate(H, pd.DataFrame(0.0, index=cal, columns=H.columns))["turn_series"].sum() == pytest.approx(2.0)


def test_conversion_beside_a_genuine_trade_on_the_acquirer():
    cal = _cal()
    # Group A converts on 03-18 while a second group enters a short on the same
    # acquirer that same row: the acquirer's ΔH is +0.5 - 0.3 = +0.2, of which
    # +0.5 is the conversion; the genuine trade is the -0.3 entry.
    legs = [_leg(1, "2021-03-05", "2021-03-17", 0.5, "2021-03-04"),
            _leg(9, "2021-03-05", "2021-03-17", -0.5, "2021-03-04"),
            _leg(2, "2021-03-18", "2021-03-26", 0.3, "2021-03-17"),
            _leg(9, "2021-03-18", "2021-03-26", -0.3, "2021-03-17")]
    H = bf.event_hold(legs, cal)
    conv = pd.DataFrame([{"row": pd.Timestamp("2021-03-18"), "target": 1, "acquirer": 9,
                          "weight": 0.5, "residual": 0.0}])
    t = bf.event_turnover(H, conv)
    assert t.loc["2021-03-18"] == pytest.approx(0.6)       # 0.3 long target 2 + 0.3 new short


def test_conversion_that_does_not_close_its_leg_raises():
    cal = _cal()
    H = bf.event_hold([_leg(1, "2021-03-05", "2021-03-17", 0.5, "2021-03-04"),
                       _leg(9, "2021-03-05", "2021-03-17", -0.5, "2021-03-04")], cal)
    bad = pd.DataFrame([{"row": pd.Timestamp("2021-03-17"), "target": 1, "acquirer": 9,
                         "weight": 0.5, "residual": 0.0}])
    with pytest.raises(AssertionError, match="not by the converted weight"):
        bf.event_turnover(H, bad)
    with pytest.raises(ValueError, match="weight"):
        bf.event_turnover(H, bad.assign(row=pd.Timestamp("2021-03-18"), weight=0.0))
