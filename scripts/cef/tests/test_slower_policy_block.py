"""The 2026-10-07 slower-policy block must never compute a 2023+ number, and its
phase-shifted calendar must be `calendar()` at phase 0.

Synthetic panel: the claim is about the code, not the market.
"""
import numpy as np
import pandas as pd
import pytest

from scripts.cef import band_frontier as bf


def _panel(start="2021-06-01", n=600, k=6, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    cols = [f"T{i}" for i in range(k)]
    T = pd.DataFrame(rng.normal(size=(n, k)).cumsum(axis=0) * 0.05, index=idx, columns=cols)
    R = pd.DataFrame(rng.normal(scale=0.01, size=(n, k)), index=idx, columns=cols)
    return T, R


def test_fit_only_drops_every_holdout_date():
    T, R = _panel()                                  # spans 2021 .. 2023
    assert T.index.max() >= bf.HOLDOUT_START         # vacuous otherwise
    Tf, Rf = bf.fit_only(T, R)
    assert Tf.index.max() < bf.HOLDOUT_START
    assert Rf.index.max() < bf.HOLDOUT_START
    assert len(Tf) == int((T.index < bf.HOLDOUT_START).sum())


def test_calendar_offset_zero_is_calendar():
    T, _ = _panel()
    pd.testing.assert_frame_equal(bf.calendar_offset(T, 21, 0), bf.calendar(T, 21))


def test_calendar_offset_refreshes_on_its_phase():
    T, _ = _panel()
    H = bf.calendar_offset(T, 21, 5)
    assert (H.iloc[:5] == 0.0).all().all()           # flat before first refresh
    pd.testing.assert_series_equal(H.iloc[5], T.iloc[5], check_names=False)
    pd.testing.assert_series_equal(H.iloc[25], T.iloc[5], check_names=False)
    pd.testing.assert_series_equal(H.iloc[26], T.iloc[26], check_names=False)
    with pytest.raises(ValueError):
        bf.calendar_offset(T, 21, 21)


def test_match_band_width_hits_turnover_and_refuses_unreachable():
    T, R = _panel(seed=2)
    target = bf.evaluate(bf.band(T, 0.05), R)["turn"]
    b = bf.match_band_width(T, R, target)
    got = bf.evaluate(bf.band(T, b), R)["turn"]
    assert abs(got / target - 1) <= bf.MATCH_TOL
    with pytest.raises(ValueError):
        bf.match_band_width(T, R, 1e6)
