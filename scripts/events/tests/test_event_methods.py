"""The four places the 2026-10-11 event re-runs corrected the 2026-10-09 scratch code.

WHY THIS FILE EXISTS
--------------------
`scripts/events/` rebuilt two agents' deleted scratch analyses (merger pairs,
term-CEF pull-to-par; `results/events/REPRO_CEF_EVENTS_2026-10-11.md`). Each
correction below replaced a silent behaviour, and each could quietly come back:

  * `window_return` replaced `ret.fillna(0)`. A missing CRSP return is not a
    zero; it is either bridged by the next return (CRSP's convention, tested
    on the data by `bridging_check`) or unknown. Back-sliding to a fill would
    make an unknowable window look measured.
  * `weekly(zero_fill_empty=False)` replaced `resample("W-WED").prod() - 1`,
    which turns a week with no valid return into a 0% week in a regression.
  * `universe_permnos` keeps EVERY permno that carried a universe ticker; the
    original matched tickers only, and so let SBW -> ESD (ESD is today's EMD,
    a comparison-set fund) into its return statistics.
  * the term-CEF census rules: the pre-2026-10-11 filter (TERM or " 20xx")
    missed abbreviated, 19xx-dated and tender-clause funds.

Every test was checked to FAIL against the behaviour it guards before it was
kept: the window test against a zero fill, the weekly test against the plain
resample, the holdout test against a one-permno-per-ticker match, the census
test against the old two-pattern filter. Synthetic data only: these test the
code, not the market. No network (the root conftest blocks it).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.data import term_cef_census as census
from scripts.events import crsp_events as ce
from scripts.events import merger_pairs as mp
from scripts.events import term_pull_to_par as tp


def _series(prices, rets):
    idx = pd.bdate_range("2020-01-06", periods=len(prices))
    return pd.DataFrame({"prc": prices, "ret": rets}, index=idx)


def test_window_return_bridges_an_interior_gap_and_never_zero_fills_an_unknown():
    # Prices 10 -> (missing) -> 11: CRSP reports ret NaN on the missing day and
    # 11/10-1 on the next. Compounding the valid returns gives +10%.
    s = _series([10.0, np.nan, 11.0], [np.nan, np.nan, 0.10])
    val, nmiss, status = mp.window_return(s, s.index[0], s.index[2])
    assert status == "bridged" and nmiss == 1 and val == pytest.approx(0.10)
    # Missing return on the LAST day: the window's end value is unknown. The
    # zero fill would report +0%; the corrected function must refuse.
    s2 = _series([10.0, 10.5, np.nan], [np.nan, 0.05, np.nan])
    val2, _, status2 = mp.window_return(s2, s2.index[0], s2.index[2])
    assert np.isnan(val2) and "last day" in status2
    assert mp.window_return_zero_fill(s2, s2.index[0], s2.index[2]) == pytest.approx(0.05)
    # No price at the window's start: the first valid return would span from
    # an earlier price, so the window is unknown.
    s3 = _series([np.nan, 10.0, 10.2], [np.nan, np.nan, 0.02])
    assert np.isnan(mp.window_return(s3, s3.index[0], s3.index[2])[0])


def test_window_return_refuses_a_gap_longer_than_crsp_bridges():
    n = mp.MAX_GAP + 3
    prices = [10.0] + [np.nan] * (mp.MAX_GAP + 1) + [10.0]
    rets = [np.nan] + [np.nan] * (mp.MAX_GAP + 1) + [0.0]
    s = _series(prices, rets)
    assert len(s) == n
    val, _, status = mp.window_return(s, s.index[0], s.index[-1])
    assert np.isnan(val) and "gap" in status


def test_weekly_returns_leave_an_empty_week_missing():
    idx = pd.bdate_range("2021-01-04", "2021-01-29")
    r = pd.Series(0.01, index=idx)
    r.loc["2021-01-14":"2021-01-20"] = np.nan  # one whole Thu..Wed week without a valid return
    fixed = tp.weekly(r, zero_fill_empty=False)
    orig = tp.weekly(r, zero_fill_empty=True)
    empty = pd.Timestamp("2021-01-20")
    assert np.isnan(fixed.loc[empty])
    assert orig.loc[empty] == 0.0  # the original's silent 0% week, kept only for reproduction


def test_universe_permnos_keeps_every_fund_that_carried_the_ticker(monkeypatch):
    nm = pd.DataFrame({
        "permno": [1, 2, 3, 4],
        "ticker": ["EMD", "EMD", "BGT", "BGT"],
        "shrcd": [14, 14, 14, 14],
        "namedt": pd.to_datetime(["2003-01-01", "2016-12-19", "1990-12-20", "2004-08-30"]),
        "nameendt": pd.to_datetime(["2016-12-16", "2024-12-31", "2002-12-20", "2024-12-31"]),
    })
    uni = pd.DataFrame({"ticker": ["EMD", "BGT"], "start": ["2003-12-04", "2004-08-30"]})
    monkeypatch.setattr(ce, "universe", lambda: uni)
    up = ce.universe_permnos(nm)
    assert up["EMD"] == [1, 2]          # both funds that were "EMD" while the panel ran
    assert up["BGT"] == [4]             # the 1990s BGT (permno 3) is a different fund
    monkeypatch.setattr(ce, "universe", lambda: pd.DataFrame({"ticker": ["ZZZ"], "start": ["2010-01-01"]}))
    with pytest.raises(LookupError):
        ce.universe_permnos(nm)


def test_daily_refuses_rows_inside_the_time_holdout(monkeypatch):
    bad = pd.DataFrame({"permno": [1], "date": ["2023-01-03"], "prc": [10.0], "ret": [0.0], "retx": [0.0],
                        "vol": [1.0], "shrout": [1.0], "cfacpr": [1.0]})
    monkeypatch.setattr(ce, "_pull", lambda *a, **k: bad.copy())
    with pytest.raises(AssertionError, match="holdout"):
        ce.daily([1])


@pytest.mark.parametrize("ticker,name,rule", [
    ("JHA", "NUVEEN HIGH INC DEC18 TRGT TM FD", "abbrev"),
    ("HYI", "WESTERN ASSET HIGH YLD DEF OP FD", "abbrev"),
    ("XFLT", "X A I OCTAGON FL RT & ALT INC TT", "abbrev"),
    ("TGB", "TRIPLE A & GOVT SER 1997", "year"),
    ("PDO", "P I M C O DYNAMIC INC OPP FUND", "tender_list"),
])
def test_census_finds_the_groups_the_old_filter_missed(ticker, name, rule):
    old = ("TERM" in name) or bool(pd.Series([name]).str.contains(r" 20[0-9][0-9]", regex=True).iloc[0])
    assert not old, "the case must be one the pre-2026-10-11 filter missed"
    assert rule in census.match_rules(name, ticker)


def test_census_does_not_match_a_plain_perpetual_fund():
    assert census.match_rules("NUVEEN MUNICIPAL VALUE FUND", "NUV") == []
