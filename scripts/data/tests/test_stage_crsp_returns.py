"""`stage_crsp_cef_families.attach_returns` (C4's DG-C4-1, 2026-10-14).

The returns are attached to the (permno, date) rows the price build already
chose, so a price and its return can never come from two securities. The two
ways that could go wrong silently are a staged row with no `dsf` row (a price
with no return, which C4's H15 rule must see as a gap, not a zero) and two
`dsf` rows for one (permno, date) (an ambiguous return). Both must raise; a
NaN `ret` that CRSP itself publishes must pass through unfilled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.data.cef_families_common import FamiliesDataError  # noqa: E402
from scripts.data.stage_crsp_cef_families import attach_returns, attach_shrcd, verify_override  # noqa: E402


def _raw():
    d = pd.to_datetime(["2014-12-19", "2014-12-22", "2014-12-23"])
    return pd.DataFrame({"permno": [91745, 15136, 15136], "date": d, "ticker": "QQQX",
                         "prc": [19.71, 19.73, 19.68], "vol": [1.0, 1.0, 1.0], "cfacpr": 1.0})


def test_returns_attach_to_their_own_permno_and_a_published_nan_stays_nan():
    r = pd.DataFrame({"permno": [91745, 15136, 15136, 99999],
                      "date": pd.to_datetime(["2014-12-19", "2014-12-22", "2014-12-23", "2014-12-22"]),
                      "ret": [-0.0005, np.nan, -0.0025, 0.5], "retx": [-0.0005, np.nan, -0.0025, 0.5]})
    out = attach_returns(_raw(), r)
    assert len(out) == 3
    assert np.isnan(out.loc[out.date == "2014-12-22", "ret"].iloc[0])     # CRSP's first row: no fill
    assert out.loc[out.date == "2014-12-23", "ret"].iloc[0] == pytest.approx(-0.0025)
    assert 0.5 not in set(out["ret"].dropna())                             # another permno never leaks in


def test_a_staged_row_without_a_dsf_row_raises():
    r = pd.DataFrame({"permno": [91745, 15136], "date": pd.to_datetime(["2014-12-19", "2014-12-22"]),
                      "ret": [0.0, 0.0], "retx": [0.0, 0.0]})
    with pytest.raises(FamiliesDataError, match="no dsf row"):
        attach_returns(_raw(), r)


def test_two_dsf_rows_for_one_permno_date_raise():
    r = pd.DataFrame({"permno": [91745, 15136, 15136, 15136],
                      "date": pd.to_datetime(["2014-12-19", "2014-12-22", "2014-12-23", "2014-12-23"]),
                      "ret": [0.0, 0.0, 0.0, 0.1], "retx": [0.0, 0.0, 0.0, 0.1]})
    with pytest.raises(FamiliesDataError, match="two rows"):
        attach_returns(_raw(), r)



# --- the BTX override (2026-10-15) --------------------------------------------

def test_an_override_must_be_a_cef_that_prices_like_the_fund():
    d = pd.DataFrame(dict(date=pd.bdate_range("2021-03-26", periods=100), prc=np.linspace(20, 15, 100)))
    y = d.rename(columns={"prc": "close"})
    assert verify_override("BTX", d, {44}, y)["share"] == 1.0
    with pytest.raises(FamiliesDataError, match="share codes"):
        verify_override("BTX", d, {11}, y)
    with pytest.raises(FamiliesDataError, match="agrees"):
        verify_override("BTX", d, {44}, y.assign(close=y["close"] * 1.5))


def test_share_codes_come_from_the_name_record_in_force_on_the_date():
    rows = pd.DataFrame(dict(permno=[1, 1, 2], date=pd.to_datetime(["2020-01-02", "2022-01-03", "2020-01-02"])))
    names = pd.DataFrame(dict(permno=[1, 1], namedt=["2019-01-01", "2021-01-01"], nameenddt=["2020-12-31", "2024-12-31"],
                              shrcd=[14, 44]))
    out = attach_shrcd(rows, names)
    assert out["shrcd"].tolist()[:2] == [14, 44] and np.isnan(out["shrcd"].iloc[2])
