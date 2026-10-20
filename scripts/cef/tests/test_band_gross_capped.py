"""`band_gross_capped` is `band` plus the sleeve's gross ceiling, and nothing else.

Two properties, both of which a plausible bug breaks: with no ceiling it must be
`band()` exactly (so the v7 numbers are comparable to every band number in this
repo), and with a ceiling the held book must never exceed it while keeping every
name's sign and the ratio between names on the day it binds.
Synthetic panel: the claim is about the code, not the market.
"""
import numpy as np
import pandas as pd

from scripts.cef import band_frontier as bf


def _targets(seed=0, n=300, k=8):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, k)).cumsum(axis=0) * 0.05
    x = x - x.mean(axis=1, keepdims=True)          # dollar-neutral, like the sleeve
    return pd.DataFrame(x, index=pd.bdate_range("2020-01-01", periods=n),
                        columns=[f"T{i}" for i in range(k)])


def test_no_ceiling_is_band_exactly():
    T = _targets()
    pd.testing.assert_frame_equal(bf.band_gross_capped(T, 0.048, np.inf), bf.band(T, 0.048))


def test_a_binding_ceiling_holds_and_only_scales():
    T = _targets(seed=1) * 3.0                     # gross well above the ceiling
    cap = 1.8
    H = bf.band_gross_capped(T, 0.048, cap)
    assert (H.abs().sum(axis=1) <= cap + 1e-12).all()
    assert (H.abs().sum(axis=1) > cap - 1e-9).any(), "the ceiling never bound -- vacuous test"
    # Scaling, not re-selection: after the ceiling binds, no name flips sign
    # relative to the uncapped band's decision on the first binding day.
    U = bf.band(T, 0.048)
    first = int(np.argmax(U.abs().sum(axis=1).values > cap))
    assert (np.sign(H.iloc[first]) == np.sign(U.iloc[first])).all()
    ratio = H.iloc[first] / U.iloc[first].replace(0, np.nan)
    assert np.nanmax(ratio) - np.nanmin(ratio) < 1e-12


# --- `unshortable` (added 2026-10-19, results/ops/IBKR_WORTH_IT_2026-10-19.md) ---
# The live runner's gate 7 skips an order that opens or enlarges a short in a
# name the broker will not lend, and lets a reduction or close through; an
# existing short is kept. These tests pin that, and pin `None` to the loop as it
# was before the argument existed.

def _old_loop(T, b, cap):
    """band_gross_capped exactly as it stood before 2026-10-19, copied here so
    the default path is compared with the old code, not with itself."""
    from src.deploy.sleeves.cef_discount import _cap_gross
    A, cur = T.values, np.zeros(T.shape[1])
    H = np.zeros_like(A)
    for i in range(len(A)):
        gap = A[i] - cur
        mv = np.abs(gap) > b
        cur = cur.copy()
        cur[mv] = A[i][mv] - np.sign(gap[mv]) * b
        if np.isfinite(cap):
            w, _ = _cap_gross(pd.Series(cur, index=T.columns), cap)
            cur = w.values
        H[i] = cur
    return pd.DataFrame(H, index=T.index, columns=T.columns)


def _flags(T, names, value=True):
    return pd.DataFrame(value, index=T.index, columns=list(names)).astype(bool)


def test_unshortable_none_is_the_old_loop_exactly():
    for seed, scale in ((0, 1.0), (2, 3.0)):
        T = _targets(seed=seed) * scale
        for cap in (1.8, np.inf):
            pd.testing.assert_frame_equal(bf.band_gross_capped(T, 0.048, cap),
                                          _old_loop(T, 0.048, cap))


def test_all_false_flags_change_nothing():
    T = _targets(seed=3) * 3.0
    pd.testing.assert_frame_equal(bf.band_gross_capped(T, 0.048, 1.8, unshortable=_flags(T, T.columns, False)),
                                  bf.band_gross_capped(T, 0.048, 1.8))


def test_a_never_lendable_name_is_never_short_and_the_rest_are_untouched_until_the_cap():
    T = _targets(seed=4)
    H0 = bf.band_gross_capped(T, 0.048, np.inf)
    assert (H0["T0"] < 0).any(), "T0 is never short in the base -- vacuous test"
    H = bf.band_gross_capped(T, 0.048, np.inf, unshortable=_flags(T, ["T0"]))
    assert (H["T0"] >= 0).all()
    # without a ceiling the other names' band paths do not depend on T0
    pd.testing.assert_frame_equal(H.drop(columns="T0"), H0.drop(columns="T0"))
    # and T0 is the base path wherever the base is long or flat
    assert np.allclose(H["T0"].where(H0["T0"] >= 0), H0["T0"].where(H0["T0"] >= 0), equal_nan=True)


def test_a_held_short_is_kept_may_shrink_and_may_not_grow_while_blocked():
    idx = pd.bdate_range("2021-01-04", periods=6)
    # target for A: short -0.30, deeper -0.50, shallower -0.10, long +0.20; B mirrors it
    a = [-0.30, -0.50, -0.50, -0.10, 0.20, -0.40]
    T = pd.DataFrame({"A": a, "B": [-x for x in a]}, index=idx)
    blk = pd.DataFrame({"A": [False, True, True, True, True, True]}, index=idx)
    H = bf.band_gross_capped(T, 0.0, np.inf, unshortable=blk)["A"].tolist()
    # day 0 lendable: short to -0.30. day 1 blocked: deeper refused, held at -0.30.
    # day 3 blocked: shrink to -0.10 allowed. day 4: long +0.20 allowed.
    # day 5 blocked: a long may be sold to flat, never through it.
    assert H == [-0.30, -0.30, -0.30, -0.10, 0.20, 0.0]


def test_the_floor_is_yesterdays_held_book_not_flat_and_not_today():
    """Two wrong versions this must reject: flooring at 0 (closes a held short
    the broker never recalled) and flooring at today's band move (lets a short
    grow). Shown here so a regression to either fails by name."""
    idx = pd.bdate_range("2021-01-04", periods=3)
    T = pd.DataFrame({"A": [-0.30, -0.30, -0.60], "B": [0.30, 0.30, 0.60]}, index=idx)
    blk = pd.DataFrame({"A": [False, True, True]}, index=idx)
    H = bf.band_gross_capped(T, 0.0, np.inf, unshortable=blk)["A"].tolist()
    assert H[1] == -0.30, "flooring at 0 would have closed a short nobody recalled"
    assert H[2] == -0.30, "flooring at today's move would have let the short grow"


def test_the_ceiling_never_opens_a_blocked_short():
    T = _targets(seed=5) * 4.0
    H = bf.band_gross_capped(T, 0.048, 1.8, unshortable=_flags(T, ["T1", "T2"]))
    assert (H[["T1", "T2"]] >= 0).all().all()
    assert (H.abs().sum(axis=1) <= 1.8 + 1e-12).all()


def test_bad_flag_frames_raise():
    import pytest
    T = _targets(seed=6)
    with pytest.raises(ValueError, match="index"):
        bf.band_gross_capped(T, 0.048, 1.8, unshortable=_flags(T, ["T0"]).iloc[1:])
    with pytest.raises(ValueError, match="does not hold"):
        bf.band_gross_capped(T, 0.048, 1.8, unshortable=pd.DataFrame(True, index=T.index, columns=["ZZZ"]))
    bad = _flags(T, ["T0"]).astype(object)
    bad.iloc[3, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        bf.band_gross_capped(T, 0.048, 1.8, unshortable=bad)
    with pytest.raises(TypeError, match="bool"):
        bf.band_gross_capped(T, 0.048, 1.8, unshortable=pd.DataFrame(1.0, index=T.index, columns=["T0"]))
