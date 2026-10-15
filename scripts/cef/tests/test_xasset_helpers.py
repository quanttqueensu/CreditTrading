"""The XASSET slate's position helpers in band_frontier.py, on synthetic inputs.

Each claim is about the code (CLAUDE.md: synthetic data tests a method, never the
market): month-ends are the last session of each month; a refreshed target is
held, and evaluate() earns it two sessions after it was decided; a NaN target is
refused rather than forward-filled; the block shuffle permutes whole blocks,
keeps every row, and is reproducible from its seed.
"""
import numpy as np
import pandas as pd
import pytest

from scripts.cef import band_frontier as bf


def _cal():
    return pd.bdate_range("2021-01-04", "2021-04-30")


def test_month_end_sessions_are_last_sessions():
    cal = _cal().delete(_cal().get_loc(pd.Timestamp("2021-03-31")))   # a missing month-end
    me = bf.month_end_sessions(cal)
    assert list(me.strftime("%Y-%m-%d")) == ["2021-01-29", "2021-02-26", "2021-03-30", "2021-04-30"]


def test_hold_from_refresh_holds_and_earns_two_sessions_later():
    cal = _cal()
    me = bf.month_end_sessions(cal)
    tgt = pd.DataFrame({"A": [1.0, -1.0, 0.5, 0.0]}, index=me)
    H = bf.hold_from_refresh(tgt, cal)
    assert (H.loc[:"2021-01-28", "A"] == 0).all()
    assert (H.loc["2021-01-29":"2021-02-25", "A"] == 1.0).all()
    assert (H.loc["2021-02-26":"2021-03-30", "A"] == -1.0).all()
    # H1: the target decided at the close of 2021-01-29 (a Friday) fills at the
    # close of Monday 02-01 and first earns Tuesday 02-02.
    R = pd.DataFrame({"A": 0.01}, index=cal)
    pnl = bf.evaluate(H, R)["pnl"]
    assert pnl.loc["2021-02-01"] == 0.0 and pnl.loc["2021-02-02"] == pytest.approx(0.01)
    assert pnl.loc["2021-03-01"] == pytest.approx(0.01)    # E + 1: still the old target
    assert pnl.loc["2021-03-02"] == pytest.approx(-0.01)   # the 02-26 target, earned from E + 2


def test_hold_from_refresh_refuses_nan_and_foreign_dates():
    cal = _cal()
    me = bf.month_end_sessions(cal)
    with pytest.raises(ValueError):
        bf.hold_from_refresh(pd.DataFrame({"A": [1.0, np.nan, 0.5, 0.0]}, index=me), cal)
    with pytest.raises(ValueError):
        bf.hold_from_refresh(pd.DataFrame({"A": [1.0]}, index=[pd.Timestamp("2021-01-31")]), cal)


def test_block_shuffle_permutes_whole_blocks_reproducibly():
    idx = pd.bdate_range("2021-01-04", periods=50)
    H = pd.DataFrame({"A": np.arange(50.0), "B": -np.arange(50.0)}, index=idx)
    a = bf.block_shuffle(H, 21, np.random.default_rng(7))
    b = bf.block_shuffle(H, 21, np.random.default_rng(7))
    pd.testing.assert_frame_equal(a, b)
    assert a.index.equals(H.index)
    assert sorted(a["A"]) == sorted(H["A"])                       # every row kept once
    assert (a["B"] == -a["A"]).all()                              # rows move whole
    # blocks move whole: consecutive values inside each output run of the input
    v = a["A"].values
    runs = np.split(v, np.where(np.diff(v) != 1)[0] + 1)
    assert sorted(len(r) for r in runs) == [8, 21, 21]
    # some draw actually moves something
    moved = any(not bf.block_shuffle(H, 21, np.random.default_rng(s)).equals(H) for s in range(5))
    assert moved
