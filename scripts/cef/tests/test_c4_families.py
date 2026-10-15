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


# --- the 2026-10-14 distribution ruling -------------------------------------

def _nav(ticker="X", n=80, step=0.05, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-02", periods=n)
    v = 10 + np.cumsum(rng.normal(0, step, n))
    return pd.DataFrame({ticker: v}, index=idx)


def test_cefconnect_equal_to_alpaca_confirms_and_its_absence_does_not():
    nav = _nav()
    d = nav.index[70]
    bad = pd.DataFrame(dict(ticker=["X", "X"], date=[d, nav.index[75]], yfinance=[0.18, 0.18], alpaca=[0.06, 0.06]))
    cc = pd.DataFrame(dict(ticker=["X"], ex_date=[d], cc_amount=[0.0605], cc_records=[1]))
    T = c4.confirm_distributions(bad, cc, nav, {"X": set()})
    assert T.loc[0, "decision"] == "Alpaca (CEFConnect)" and T.loc[0, "cefconnect_reads"] == "= Alpaca"
    assert T.loc[1, "cefconnect_reads"] == "no record"
    assert T.loc[1, "decision"] in ("Alpaca (NAV drop)", "UNCONFIRMED")


def test_the_nav_drop_confirms_only_when_it_tells_the_sources_apart():
    nav = _nav(step=0.01)
    d = nav.index[70]
    nav.loc[d:, "X"] -= 0.06                                       # a 0.06 drop on the ex-date, sigma ~0.01
    bad = pd.DataFrame(dict(ticker=["X"], date=[d], yfinance=[0.18], alpaca=[0.06]))
    cc = pd.DataFrame(columns=["ticker", "ex_date", "cc_amount", "cc_records"])
    T = c4.confirm_distributions(bad, cc, nav, {"X": set()})
    assert T.loc[0, "decision"] == "Alpaca (NAV drop)"
    # sources 0.06 and 0.07 cannot be told apart by a 0.06 drop with sigma ~0.01
    bad2 = bad.assign(yfinance=[0.07])
    T2 = c4.confirm_distributions(bad2, cc, nav, {"X": set()})
    assert T2.loc[0, "decision"] == "UNCONFIRMED" and T2.loc[0, "nav_reads"] == "cannot tell the sources apart"


def test_a_repeated_nav_on_the_ex_date_is_unusable():
    nav = _nav()
    d = nav.index[70]
    nav.loc[d, "X"] = nav.loc[nav.index[69], "X"]
    bad = pd.DataFrame(dict(ticker=["X"], date=[d], yfinance=[0.18], alpaca=[0.06]))
    cc = pd.DataFrame(columns=["ticker", "ex_date", "cc_amount", "cc_records"])
    T = c4.confirm_distributions(bad, cc, nav, {"X": set()})
    assert T.loc[0, "nav_reads"].startswith("unusable") and T.loc[0, "decision"] == "UNCONFIRMED"


def test_holdout_actions_halt_on_any_unconfirmed_row_and_otherwise_take_alpaca():
    acts = pd.DataFrame(dict(date=pd.to_datetime(["2025-01-21", "2025-08-01", "2026-09-08"]), ticker=["IGR", "IGA", "IGR"],
                             dividends=[0.18, 0.085, 0.0], stock_splits=[0.0, 0.0, 1 / 3]))
    T = pd.DataFrame(dict(ticker=["IGR", "IGA", "IGA"], date=pd.to_datetime(["2025-01-21", "2025-08-01", "2025-08-04"]),
                          alpaca=[0.06, np.nan, 0.085], decision=["Alpaca (NAV drop)"] * 3))
    out = c4.holdout_actions(acts, T)
    assert out.loc[(out.ticker == "IGR") & (out.date == "2025-01-21"), "dividends"].item() == 0.06
    assert out.loc[(out.ticker == "IGA") & (out.date == "2025-08-01"), "dividends"].item() == 0.0
    assert out.loc[(out.ticker == "IGA") & (out.date == "2025-08-04"), "dividends"].item() == 0.085
    assert out.loc[(out.ticker == "IGR") & (out.date == "2026-09-08"), "stock_splits"].item() == pytest.approx(1 / 3)
    with pytest.raises(c4.GateError, match="halt"):
        c4.holdout_actions(acts, T.assign(decision=["Alpaca (NAV drop)", "UNCONFIRMED", "Alpaca (NAV drop)"]))
