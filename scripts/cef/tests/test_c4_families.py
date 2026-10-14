"""The gate logic of trial C4's script (`scripts/cef/c4_families.py`), on synthetic frames.

H15 on the P&L is the part that could fail silently: `evaluate()` multiplies the
held book by the return matrix and pandas' `sum` skips NaN, so a held position on
a name-day with no return would contribute nothing and nothing would error.
`check_held` must raise on that, must refuse a ruled name-day that is held, and
may zero a NaN only where the held weight is zero. `ruling_of` must cover exactly
the name-days the team lead ruled on (2026-10-14) and nothing else. Claims about
the code, never about the market.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cef import c4_families as c4


def _frames():
    idx = pd.bdate_range("2014-12-15", periods=10)
    H = pd.DataFrame(0.0, index=idx, columns=["QQQX", "ADX"])
    R = pd.DataFrame(0.001, index=idx, columns=["QQQX", "ADX"])
    return idx, H, R


def test_a_held_position_on_a_missing_return_raises():
    idx, H, R = _frames()
    H.loc[idx[2]:, "ADX"] = 0.1                        # held from idx[4] under shift(2)
    R.loc[idx[6], "ADX"] = np.nan
    with pytest.raises(c4.GateError, match="no primary return"):
        c4.check_held(H, R, "t")


def test_a_nan_under_a_zero_weight_becomes_zero_and_nothing_else_moves():
    idx, H, R = _frames()
    H.loc[:, "ADX"] = 0.1
    R.loc[idx[0], "ADX"] = np.nan                      # row 0 is never held under shift(2)
    R.loc[idx[5], "QQQX"] = np.nan                     # QQQX is never held
    out = c4.check_held(H, R, "t")
    assert out.loc[idx[0], "ADX"] == 0.0 and out.loc[idx[5], "QQQX"] == 0.0
    assert (out.loc[idx[1]:, "ADX"] == 0.001).all()


def test_a_ruled_name_day_that_is_held_raises_even_with_a_return():
    idx, H, R = _frames()
    H.loc[:, "QQQX"] = 0.05                            # QQQX held on 2014-12-22 (ruled: cannot be)
    with pytest.raises(c4.GateError, match="ruling"):
        c4.check_held(H, R, "t")


def test_the_ruling_covers_exactly_the_ruled_name_days():
    Row = pd.Series
    f = lambda t, d: c4.ruling_of(type("r", (), {"ticker": t, "date": pd.Timestamp(d)})())  # noqa: E731
    assert f("GRX", "2007-06-20").startswith("ruled") and f("GRX", "2007-06-29").startswith("ruled")
    assert f("GRX", "2007-07-02") == ""
    assert f("QQQX", "2014-12-22").startswith("ruled") and f("QQQX", "2014-12-23") == ""
    assert "Alpaca" in f("IGR", "2026-09-08") and "Alpaca" in f("IGR", "2026-09-09")
    assert f("IGR", "2026-09-10") == "" and f("TY", "2025-12-12") == ""
    assert "R-S only" in f("ACV", "2015-05-22")
    assert Row is pd.Series


def test_block_sums_drop_the_partial_last_block():
    x = pd.Series(np.arange(50, dtype=float), index=pd.bdate_range("2020-01-01", periods=50))
    b = c4.block_sums(x, 21)
    assert len(b) == 2 and b.iloc[0] == sum(range(21)) and b.iloc[1] == sum(range(21, 42))
