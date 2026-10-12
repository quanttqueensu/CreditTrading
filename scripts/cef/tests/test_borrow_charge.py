"""`borrow_charge()` -- the borrow leg of plan item 0.5, pinned on synthetic input.

WHY THESE TESTS. The charge is only as good as its alignment with `evaluate()`:
the short a book PAYS for must be the short it EARNS on, `H.shift(2)`. A charge
on `H` or `H.shift(1)` would bill positions the book does not yet hold, which is
the shift(1) incident of 2026-09-10 in a new place. The other ways it can be
wrong silently are the calendar-day accrual (a weekend is three days of fee at
both brokers), which day's fee applies, charging longs, and a missing fee
turning into a zero. Each is a statement about the code, never about the market
(CLAUDE.md data rules).

The alignment test was checked to FAIL with `H.shift(1)` in `borrow_charge`
before it was kept, and the gap test to fail with the gap mask removed (a NaN
fee silently charged nothing and `covered_share` read 1.0).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cef import band_frontier as BF


def _book(n=12, start="2021-03-01"):
    idx = pd.bdate_range(start, periods=n)          # 2021-03-01 is a Monday
    H = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
    return idx, H


def _fees(idx, a=10.0, b=10.0):
    return pd.DataFrame({"A": a, "B": b}, index=idx)


def test_charge_starts_two_sessions_after_the_decision():
    """Decide at k, fill at close k+1, first borrowed overnight is k+1 -> k+2."""
    idx, H = _book()
    k = 4                                            # a Friday decision
    H.iloc[k:, 0] = -0.5
    out = BF.borrow_charge(H, _fees(idx))
    c = out["cost"]
    assert (c.iloc[:k + 2] == 0).all(), "charged before the short was filled"
    days = pd.Series(idx, index=idx).diff().dt.days
    exp = 0.5 * 0.10 * BF.BORROW_COLLATERAL_MARKUP * days / BF.BORROW_DAY_COUNT
    assert np.allclose(c.iloc[k + 2:], exp.iloc[k + 2:])
    # the short it bills is exactly the short evaluate() earns on
    held = (-H.shift(2).fillna(0.0)).clip(lower=0).sum(axis=1)
    assert np.allclose(out["short"], held)


def test_a_weekend_row_is_three_days():
    idx, H = _book()
    H.iloc[:, 0] = -1.0
    c = BF.borrow_charge(H, _fees(idx))["cost"]
    one = 1.0 * 0.10 * BF.BORROW_COLLATERAL_MARKUP / BF.BORROW_DAY_COUNT
    mondays = [i for i, d in enumerate(idx) if d.dayofweek == 0 and i >= 2]
    others = [i for i, d in enumerate(idx) if d.dayofweek != 0 and i >= 2]
    assert mondays and others
    assert np.allclose(c.iloc[mondays], 3 * one)
    assert np.allclose(c.iloc[others], one)


def test_the_fee_in_force_is_the_previous_sessions():
    """A fee change on session m bills from row m+1 (the m -> m+1 overnight)."""
    idx, H = _book()
    H.iloc[:, 0] = -1.0
    fee = _fees(idx)
    m = 7
    fee.iloc[m:, 0] = 30.0
    c = BF.borrow_charge(H, fee)["cost"]
    days = pd.Series(idx, index=idx).diff().dt.days
    unit = BF.BORROW_COLLATERAL_MARKUP * days / BF.BORROW_DAY_COUNT
    assert np.isclose(c.iloc[m], 0.10 * unit.iloc[m])
    assert np.isclose(c.iloc[m + 1], 0.30 * unit.iloc[m + 1])


def test_longs_pay_nothing():
    idx, H = _book()
    H.iloc[:, 0] = +0.7
    H.iloc[:, 1] = -0.2
    out = BF.borrow_charge(H, _fees(idx, a=50.0, b=10.0))
    days = pd.Series(idx, index=idx).diff().dt.days
    exp = 0.2 * 0.10 * BF.BORROW_COLLATERAL_MARKUP * days / BF.BORROW_DAY_COUNT
    assert np.allclose(out["cost"].iloc[2:], exp.iloc[2:])


def test_a_missing_fee_is_reported_not_charged_zero_quietly():
    idx, H = _book()
    H.iloc[:, 0] = -0.4
    H.iloc[:, 1] = -0.1
    fee = _fees(idx)
    fee.iloc[5, 0] = np.nan                         # bills row 6
    fee.iloc[5, 1] = np.nan
    out = BF.borrow_charge(H, fee)
    assert np.isclose(out["uncovered"].iloc[6], 0.5)
    assert out["uncovered"].drop(idx[6]).eq(0).all()
    assert out["covered_share"] < 1.0
    assert np.isclose(out["covered_share"], 1 - 0.5 / out["short"].sum())
    assert out["cost"].iloc[6] == 0.0               # excluded, and SAID so above


def test_a_nan_fee_with_no_short_is_not_a_gap():
    idx, H = _book()
    H.iloc[:, 0] = -0.4
    fee = _fees(idx)
    fee.iloc[:, 1] = np.nan                         # B is never short
    out = BF.borrow_charge(H, fee)
    assert out["covered_share"] == 1.0
    assert out["uncovered"].eq(0).all()


def test_a_name_with_no_fee_source_raises():
    idx, H = _book()
    with pytest.raises(ValueError, match="no column"):
        BF.borrow_charge(H, pd.DataFrame({"A": 1.0}, index=idx))
