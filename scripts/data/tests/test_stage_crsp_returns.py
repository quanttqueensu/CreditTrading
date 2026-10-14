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
from scripts.data.stage_crsp_cef_families import attach_returns  # noqa: E402


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
