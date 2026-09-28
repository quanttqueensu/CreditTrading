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
