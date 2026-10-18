"""The counting helpers of `scripts/events/ss_credit_catalogue_counts.py`, on synthetic inputs.

WHY THESE TESTS
---------------
* `episodes` is what turns stress DAYS into independent EPISODES, and breadth
  claims rest on it. Two failures matter: days a few sessions apart counted as
  separate events (inflated breadth), and a flagged date that is not on the
  session calendar silently mapped to the wrong place (it must raise).
* `per_year` must keep "absent" and "zero" apart. A year inside a panel's
  coverage with no event is a measured zero; a year outside it is unknown and
  must stay NaN, or a short panel reads as a quiet market.
* The name regexes are a census tool. An ADR ("American Depositary Shares")
  must not count as a preferred, a preferred ETF must not count as an issue,
  and a convertible note must not count as a baby bond.
Synthetic inputs test the code, not the market. No network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import ss_credit_catalogue_counts as c


def _cal(n=30):
    return pd.bdate_range("2020-01-01", periods=n)


def test_episodes_merge_days_closer_than_gap():
    cal = _cal()
    flagged = pd.Series([cal[2], cal[4], cal[20]])
    eps = c.episodes(flagged, cal, gap=10)
    assert len(eps) == 2
    assert eps[0] == (cal[2], cal[4], 2)
    assert eps[1] == (cal[20], cal[20], 1)


def test_episodes_split_at_gap():
    cal = _cal()
    # exactly `gap` sessions apart is a new episode; one fewer is the same one
    assert len(c.episodes(pd.Series([cal[0], cal[10]]), cal, gap=10)) == 2
    assert len(c.episodes(pd.Series([cal[0], cal[9]]), cal, gap=10)) == 1


def test_episodes_refuse_date_off_calendar():
    cal = _cal()
    with pytest.raises(ValueError):
        c.episodes(pd.Series([pd.Timestamp("2020-01-04")]), cal, gap=5)   # a Saturday


def test_episodes_empty_and_bad_gap():
    cal = _cal()
    assert c.episodes(pd.Series([], dtype="datetime64[ns]"), cal, gap=5) == []
    with pytest.raises(ValueError):
        c.episodes(pd.Series([cal[0]]), cal, gap=0)


def test_per_year_keeps_absent_apart_from_zero():
    df = pd.DataFrame({"d": pd.to_datetime(["2011-03-01", "2011-04-01", "2013-02-01"])})
    y = c.per_year(df, "d", 2010, 2014)
    assert np.isnan(y.loc[2010, "n"])            # before the panel: unknown
    assert y.loc[2011, "n"] == 2
    assert y.loc[2012, "n"] == 0                 # inside coverage, no event: a measured zero
    assert y.loc[2013, "n"] == 1
    assert np.isnan(y.loc[2014, "n"])            # after the panel: unknown


@pytest.mark.parametrize("name,kind", [
    ("Wells Fargo & Company Depositary Shares, each representing a 1/1,000th interest in a share of Preferred Stock", "preferred"),
    ("Shell plc American Depositary Shares (Each represents two Ordinary shares)", None),
    ("Invesco Preferred ETF", None),
    ("Oxford Lane Capital Corp. 6.75% Notes due 2031", "baby_bond"),
    ("Prudential Financial, Inc. 5.950% Junior Subordinated Notes due 2062", "baby_bond"),
    ("Acme Corp 5.0% Convertible Senior Notes due 2030", None),
])
def test_name_classification(name, kind):
    assert c.classify_name(name) == kind
