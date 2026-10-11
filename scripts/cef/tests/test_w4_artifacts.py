"""Tests for the W4 artifact battery's alignment and parsing helpers.

WHY THESE AND NOT THE NUMBERS. The battery's figures depend on panels that move
and are gitignored; the parts that can be wrong silently are the alignment of
forward windows (a window that starts at t+1 instead of t+2 is the shift(1)
incident of 2026-09-10 again), the rank-correlation machinery, the holdout
guard, and the two parsers that turn fetched text into factor returns. Each is
pinned here on synthetic input -- a statement about the code, never about the
market (CLAUDE.md data rules).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from scripts.cef import w4_artifacts as w4
from scripts.data.fetch_ff_factors import FactorFetchError, crsp_vintage, parse_french_csv
from scripts.data.fetch_pastor_liquidity import LiquidityFetchError, parse as parse_ps


def _frame(n=12, k=3, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-05", periods=n)
    return pd.DataFrame(rng.normal(0, 0.01, (n, k)), index=idx, columns=list("ABC")[:k])


def test_fwd_is_the_shift2_window():
    r = _frame()
    f = w4.fwd(r, 2, 3)
    # row t holds the move from close t+1 to close t+3: returns of rows t+2, t+3
    for t in range(len(r) - 3):
        exp = (1 + r.iloc[t + 2]) * (1 + r.iloc[t + 3]) - 1
        assert np.allclose(f.iloc[t].values, exp.values)
    assert f.iloc[-3:].isna().all().all()          # needs data past the end: NaN, never filled


def test_fwd_propagates_nan_and_refuses_t0():
    r = _frame()
    r.iloc[5, 0] = np.nan
    f = w4.fwd(r, 2, 3)
    assert np.isnan(f.iloc[2, 0]) and np.isnan(f.iloc[3, 0])
    with pytest.raises(ValueError):
        w4.fwd(r, 0, 1)                            # a window starting at t itself is lookahead


def test_fwd_log_matches_fwd():
    r = _frame()
    assert np.allclose(np.expm1(w4.fwd_log(r, 2, 4)).dropna(), w4.fwd(r, 2, 4).dropna())


def test_ic_series_equals_scipy_spearman():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2016-01-04", periods=40)
    S = pd.DataFrame(rng.normal(size=(40, 8)), index=idx)
    F = pd.DataFrame(rng.normal(size=(40, 8)), index=idx)
    M = pd.DataFrame(rng.random((40, 8)) > 0.2, index=idx)
    ic = w4.ic_series(S, F, M, idx, min_n=5)
    for d, v in ic.items():
        m = M.loc[d]
        assert np.isclose(v, stats.spearmanr(S.loc[d][m], F.loc[d][m]).statistic)
    # dates with fewer than min_n valid names are dropped, not scored
    thin = M.sum(axis=1) < 5
    assert not set(ic.index) & set(idx[thin])


def test_fm_slopes_equal_per_date_ols():
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2016-01-04", periods=10)
    S = pd.DataFrame(rng.normal(size=(10, 7)), index=idx)
    F = 0.3 * S + pd.DataFrame(rng.normal(size=(10, 7)), index=idx)
    M = pd.DataFrame(True, index=idx, columns=S.columns)
    b = w4.fm_slopes(S, F, M, idx)
    for d in idx:
        assert np.isclose(b[d], np.polyfit(S.loc[d], F.loc[d], 1)[0])


def test_assert_fit_refuses_the_holdout():
    w4._assert_fit(pd.Series(1.0, index=pd.to_datetime(["2022-12-30"])))
    with pytest.raises(AssertionError):
        w4._assert_fit(pd.Series(1.0, index=pd.to_datetime(["2023-01-03"])))


def test_bond_holidays_are_columbus_and_weekday_veterans():
    idx = pd.bdate_range("2021-01-01", "2022-12-31")
    got = w4.bond_holidays(idx)
    assert pd.Timestamp("2021-10-11") in got and pd.Timestamp("2022-10-10") in got   # 2nd Mondays
    assert pd.Timestamp("2021-11-11") in got and pd.Timestamp("2022-11-11") in got   # Thu, Fri
    assert len(got) == 4
    # 2018-11-11 was a Sunday: observed Monday the 12th; 2017-11-11 a Saturday: none
    got = w4.bond_holidays(pd.bdate_range("2017-01-01", "2018-12-31"))
    assert pd.Timestamp("2018-11-12") in got
    assert not [d for d in got if d.month == 11 and d.year == 2017]
    assert len(got) == 3        # Columbus 2017, Columbus 2018, Veterans (observed) 2018


FRENCH_DAILY = """This file was created by using the 202608 CRSP database.
The Tbill return is ...

,Mkt-RF,SMB,HML,RMW,CMA,RF
20220103,    0.71,   -0.22,    0.80,   -0.10,    0.40,    0.00
20220104,   -0.10,    0.50,    2.10,    0.60,    1.20,    0.00

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

FRENCH_MONTHLY = """This file was created using the 202608 CRSP database.

,Mkt-RF,SMB,HML,RMW,CMA,RF
202201,   -6.25,   -4.00,   12.80,    0.70,    7.70,    0.00
202202,   -2.29,    2.20,    3.10,   -0.20,    3.00,    0.00

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RMW,CMA,RF
  2022,  -21.58,   -6.00,   25.80,   33.00,    5.40,    1.43
"""


def test_french_parser_daily_and_monthly():
    d = parse_french_csv(FRENCH_DAILY, ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"], 8)
    assert list(d.date) == list(pd.to_datetime(["2022-01-03", "2022-01-04"]))
    assert d["Mkt-RF"].iloc[0] == 0.71                 # percent as published; caller divides once
    m = parse_french_csv(FRENCH_MONTHLY, ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"], 6)
    assert len(m) == 2                                  # the annual block is skipped by rule
    assert m.date.iloc[0] == pd.Timestamp("2022-01-31")  # month-end stamp
    assert crsp_vintage(FRENCH_DAILY) == "202608"


def test_french_parser_refuses_a_changed_header_or_missing_code():
    with pytest.raises(FactorFetchError):
        parse_french_csv(FRENCH_DAILY, ["Mkt-RF", "SMB", "HML", "CMA", "RMW", "RF"], 8)
    bad = FRENCH_DAILY.replace("   -0.22,", "  -99.99,")
    with pytest.raises(FactorFetchError):
        parse_french_csv(bad, ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"], 8)


PASTOR = """% LIQUIDITY FACTORS OF PASTOR AND STAMBAUGH (JPE 2003) UPDATED THROUGH DEC 2025
% Month	Agg Liq.	Innov Liq (eq8)	Traded Liq (LIQ_V)
196712	 -0.01	  0.02	-99
196801	 -0.02	  0.01	 0.0123
196802	  0.03	 -0.01	-0.0040
"""


def test_pastor_parser_keeps_pre_start_missing_as_nan():
    df, through = parse_ps(PASTOR)
    assert through == "DEC 2025"
    assert np.isnan(df.liq_v.iloc[0]) and df.liq_v.iloc[1] == 0.0123
    assert df.date.iloc[1] == pd.Timestamp("1968-01-31")


def test_pastor_parser_refuses_missing_after_start():
    with pytest.raises(LiquidityFetchError):
        parse_ps(PASTOR.replace("-0.0040", "-99"))
