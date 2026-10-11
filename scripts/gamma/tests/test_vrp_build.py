"""Guards on the TLT implied-vol build and the FRED parser (no network).

WHY THESE
---------
* `forward_rv` is compared with an implied vol struck at t's close, so its value
  at t must use returns strictly AFTER t (t+1..t+21). An off-by-one here would
  put day t's own return into "forward" realised vol and bias IV-RV on exactly
  the days that matter (a jump day). Pinned with a spike.
* The Black-76 inversion must return the vol that priced the option, and NaN --
  never a neighbour's vol -- when the price is below intrinsic.
* FRED marks non-publication days with "" or "."; those are dropped, and any
  other non-numeric value raises rather than becoming NaN.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.gamma import tlt_atm_iv as T          # noqa: E402
from scripts.gamma import fetch_fred as F          # noqa: E402


def test_forward_rv_uses_only_returns_after_t():
    idx = pd.bdate_range("2024-01-01", periods=60)
    r = pd.Series(0.0, index=idx)
    r.iloc[30] = 0.05                                   # one spike on day 30
    rv = T.forward_rv(r, h=21)
    assert rv.iloc[30] == 0.0                           # day 30's own return is NOT forward
    assert rv.iloc[29] > 0.0                            # it is forward for day 29 ...
    assert rv.iloc[9] > 0.0 and rv.iloc[8] == 0.0       # ... and for days 9..29 only
    assert rv.iloc[-21:].isna().all()                   # fewer than 21 forward returns: NaN
    assert math.isclose(rv.iloc[29], math.sqrt(252 / 21 * math.log1p(0.05) ** 2))


@pytest.mark.parametrize("cp,K", [("C", 92.0), ("P", 88.0)])
def test_black76_inversion_round_trips(cp, K):
    F_, T_, DF = 90.0, 30 / 365, math.exp(-0.04 * 30 / 365)
    px = T.b76(F_, K, T_, DF, 0.14, cp)
    assert abs(T.implied_vol(px, F_, K, T_, DF, cp) - 0.14) < 1e-6


def test_black76_inversion_refuses_a_price_below_intrinsic():
    F_, T_, DF = 90.0, 30 / 365, 1.0
    assert np.isnan(T.implied_vol(1.0, F_, 88.0, T_, DF, "C"))   # intrinsic is 2.0


def test_fred_drops_only_the_two_missing_markers():
    raw = "observation_date,DGS1MO\n2024-01-01,\n2024-01-02,5.55\n2024-01-03,.\n2024-01-04,5.54\n"
    df = F.parse("DGS1MO", raw)
    assert list(df["date"].dt.day) == [2, 4]
    assert list(df["value"]) == [5.55, 5.54]


def test_fred_raises_on_any_other_non_numeric_value():
    with pytest.raises(ValueError):
        F.parse("DGS1MO", "observation_date,DGS1MO\n2024-01-02,n/a\n")


def test_fred_refuses_the_truncating_baml_series():
    with pytest.raises(F.FetchError, match="BAML"):
        F.fetch("BAMLH0A0HYM2")
