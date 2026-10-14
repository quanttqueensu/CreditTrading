"""Trial C5's harness extension: `session_returns` and `open_fill_gain` beside
`evaluate()`, the WIDE flag on `build_targets`, and the two inference helpers.

WHY THESE TESTS (results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md, DG-C5-3).
C5 adds one leg to the deployed book: the trade decided in the evening of s-1
filled at the OPENING auction of s, earning C[s]/O[s] - 1. The ways to get that
wrong silently are all alignment errors, and each has a dead relative here:

* the trade at shift(0) -- filling a decision before it was made, which is
  the shift(1) incident of 2026-09-10 in a new place;
* the trade at shift(2) -- the deployed MOC fill, i.e. a gain of nothing that
  still looks like a gain series;
* the OVERNIGHT return C[s-1] -> O[s] in place of the session return -- an
  earning that began before the decision existed.

So every property below is asserted for the shipped helper AND asserted to
FAIL for each wrong version, inside the test. A test that passes on the wrong
lag is not a test of the lag.

Synthetic frames only: these are statements about the code, never about any
fund or market (CLAUDE.md data rules). Nothing reads `data/` or the network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cef import band_frontier as bf
from scripts.cef import w4_artifacts as w4

N, COLS = 40, ["A", "B", "C", "D"]
IDX = pd.bdate_range("2019-01-02", periods=N)


def _book(seed=1):
    rng = np.random.default_rng(seed)
    H = pd.DataFrame(np.round(rng.normal(0, 0.1, (N, len(COLS))), 3), index=IDX, columns=COLS)
    H.iloc[:3] = 0.0
    R = pd.DataFrame(rng.normal(0, 0.01, (N, len(COLS))), index=IDX, columns=COLS)
    C = 20.0 * (1 + R).cumprod()
    O = C * (1 + rng.normal(0, 0.004, C.shape))
    return H, R, O, C


# ---------------------------------------------------------------- wrong versions

def _gain_shift2(H, RS):            # the deployed MOC fill: nothing to gain
    return (H.diff().shift(2) * RS).fillna(0.0).sum(axis=1)


def _gain_shift0(H, RS):            # filled before it was decided
    return (H.diff() * RS).fillna(0.0).sum(axis=1)


def _sess_overnight(O, C):          # C[s-1] -> O[s] in place of O[s] -> C[s]
    rs = O / C.shift(1) - 1.0
    return rs.fillna(0.0), rs.isna()


def _sess_next_open(O, C):          # reads tomorrow's open
    rs = C / O.shift(-1) - 1.0
    return rs.fillna(0.0), rs.isna()


def _sess_ffill_open(O, C):         # a silent fallback: yesterday's open where none printed
    rs = C / O.ffill() - 1.0
    return rs.fillna(0.0), rs.isna()


# ---------------------------------------------------------------- properties

def _p_zero_session_is_evaluate(sess):
    """(i) With O == C (a zero session return everywhere), C5 is the deployed
    book to the last bit."""
    H, R, _, C = _book()
    RS, _ = sess(C.copy(), C)
    pnl_d = bf.evaluate(H, R)["pnl"]
    return (pnl_d + bf.open_fill_gain(H, RS)).equals(pnl_d)


def _p_unit_trade_lands_on_t_plus_1(gain):
    """(ii) A unit trade decided on row t appears only on row t+1, times that
    row's session return."""
    _, _, O, C = _book()
    RS, _ = bf.session_returns(O, C)
    t, k = 10, "B"
    H = pd.DataFrame(0.0, index=IDX, columns=COLS)
    H.loc[IDX[t]:, k] = 1.0
    G = gain(H, RS)
    want = pd.Series(0.0, index=IDX)
    want.iloc[t + 1] = RS[k].iloc[t + 1]
    return bool(np.allclose(G.values, want.values, atol=0, rtol=0)) and G.iloc[t + 1] != 0.0


def _p_session_reads_only_its_row(sess):
    """(iii) Perturbing O[s+1] or C[s-1] leaves the session return of s unchanged."""
    _, _, O, C = _book()
    s = 15
    base, _ = sess(O, C)
    O2, C2 = O.copy(), C.copy()
    O2.iloc[s + 1] *= 1.10
    C2.iloc[s - 1] *= 0.90
    a, _ = sess(O2, C)
    b, _ = sess(O, C2)
    return bool(a.iloc[s].equals(base.iloc[s]) and b.iloc[s].equals(base.iloc[s]))


def _p_no_cross_is_zero_and_flagged(sess):
    """(iv) A name-day with no open earns 0 and is returned in the mask; a trade
    filling on it adds nothing."""
    _, _, O, C = _book()
    s, k = 20, "C"
    O = O.copy()
    O.iloc[s, O.columns.get_loc(k)] = np.nan
    RS, mask = sess(O, C)
    H = pd.DataFrame(0.0, index=IDX, columns=COLS)
    H.loc[IDX[s - 1]:, k] = 1.0                       # decided s-1, fills at the open of s
    G = bf.open_fill_gain(H, RS)
    return bool(RS.iloc[s][k] == 0.0 and mask.iloc[s][k] and mask.sum().sum() == 1
                and (G == 0.0).all())


# ---------------------------------------------------------------- DG-C5-3 (i)-(iv)

def test_i_zero_session_return_reproduces_evaluate_exactly():
    assert _p_zero_session_is_evaluate(bf.session_returns)
    assert not _p_zero_session_is_evaluate(_sess_overnight)


def test_ii_a_unit_trade_lands_only_on_the_next_row():
    assert _p_unit_trade_lands_on_t_plus_1(bf.open_fill_gain)
    assert not _p_unit_trade_lands_on_t_plus_1(_gain_shift2)
    assert not _p_unit_trade_lands_on_t_plus_1(_gain_shift0)


def test_iii_the_session_return_reads_only_its_own_row():
    assert _p_session_reads_only_its_row(bf.session_returns)
    assert not _p_session_reads_only_its_row(_sess_overnight)
    assert not _p_session_reads_only_its_row(_sess_next_open)


def test_iv_no_cross_name_days_give_zero_and_are_returned_as_a_mask():
    assert _p_no_cross_is_zero_and_flagged(bf.session_returns)
    assert not _p_no_cross_is_zero_and_flagged(_sess_ffill_open)


def test_the_gain_is_the_preregistered_expression():
    H, _, O, C = _book()
    RS, _ = bf.session_returns(O, C)
    want = (H.diff().shift(1) * RS).sum(axis=1)      # PREREG_C5 §5, verbatim
    assert np.allclose(bf.open_fill_gain(H, RS).values, want.values, atol=1e-15, rtol=0)


def test_by_name_with_unit_returns_is_the_trade_matrix():
    H, *_ = _book()
    ones = pd.DataFrame(1.0, index=IDX, columns=COLS)
    T = bf.open_fill_gain(H, ones, by_name=True)
    assert T.equals((H.diff().shift(1)).fillna(0.0))
    assert T.iloc[:2].eq(0.0).all().all()


# ---------------------------------------------------------------- refusals

def test_session_returns_refuses_a_move_the_harness_filter_would_drop():
    _, _, O, C = _book()
    O = O.copy()
    O.iloc[5, 0] = C.iloc[5, 0] / 1.6                 # session return +60%
    with pytest.raises(ValueError, match="Stage 0 defect"):
        bf.session_returns(O, C)


def test_session_returns_refuses_a_non_positive_price():
    _, _, O, C = _book()
    O = O.copy()
    O.iloc[7, 1] = 0.0
    with pytest.raises(ValueError, match="non-positive"):
        bf.session_returns(O, C)


def test_open_fill_gain_refuses_nan_and_misalignment():
    H, _, O, C = _book()
    RS, _ = bf.session_returns(O, C)
    holed = RS.copy()
    holed.iloc[5, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        bf.open_fill_gain(H, holed)
    with pytest.raises(ValueError, match="one index"):
        bf.open_fill_gain(H, RS.iloc[1:])
    with pytest.raises(ValueError, match="one index"):
        bf.session_returns(O, C[COLS[::-1]])


# ---------------------------------------------------------------- DG-C5-4: the WIDE flag

def _fake_panel(monkeypatch, adv_row):
    """A panel on which every name has a z-score on every row, and the given ADVs."""
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2005-01-03", periods=80)
    cols = list(adv_row)
    z = pd.DataFrame(rng.normal(0, 1, (len(idx), len(cols))), index=idx, columns=cols)
    ret = pd.DataFrame(rng.normal(0, 0.01, z.shape), index=idx, columns=cols)
    adv = pd.DataFrame([list(adv_row.values())] * len(idx), index=idx, columns=cols, dtype=float)
    monkeypatch.setattr(bf, "build_panel", lambda universe=None: dict(ret=ret, z=z, adv=adv))
    return cols


def test_min_adv_absent_is_the_spec_floor_and_zero_admits_only_defined_adv(monkeypatch):
    big, small = 2 * bf.MIN_ADV, 0.5 * bf.MIN_ADV
    adv = {"A": big, "B": big, "C": big, "D": big, "E": big, "F": big,
           "G": small, "H": small, "I": np.nan}
    cols = _fake_panel(monkeypatch, adv)
    T0, _ = bf.build_targets(universe=cols)
    Tn, _ = bf.build_targets(universe=cols, min_adv=None)
    Tw, _ = bf.build_targets(universe=cols, min_adv=0)
    assert T0.equals(Tn)                                           # absent == None == spec floor
    held = lambda T: set(T.columns[(T.abs().sum() > 0).to_numpy()])
    assert held(T0) == set("ABCDEF")
    assert held(Tw) == set("ABCDEFGH")                             # floor off, NaN ADV still out
    assert bf.MIN_ADV == bf.MIN_ADV_USD


# ---------------------------------------------------------------- PREREG_C5 §8 helpers

def test_stationary_boot_is_reproducible_and_wider_on_autocorrelated_data():
    rng = np.random.default_rng(11)
    e = rng.normal(0, 1, 1500)
    ar = np.empty_like(e)
    ar[0] = e[0]
    for i in range(1, len(e)):
        ar[i] = 0.6 * ar[i - 1] + e[i]
    x = pd.Series(ar)
    a = w4.stationary_boot(x, mean_block=21, reps=600, seed=5)
    b = w4.stationary_boot(x, mean_block=21, reps=600, seed=5)
    assert np.array_equal(a["means"], b["means"])
    iid = w4.stationary_boot(x, mean_block=1, reps=600, seed=5)
    assert a["means"].std() > 1.5 * iid["means"].std()            # blocks keep the dependence
    # on white noise, mean block 1 is the iid bootstrap: SE close to sd/sqrt(n)
    wn = pd.Series(e)
    s = w4.stationary_boot(wn, mean_block=1, reps=2000, seed=6)["means"].std()
    assert abs(s / (e.std(ddof=1) / np.sqrt(len(e))) - 1) < 0.1
    assert a["lo_mean"] < x.mean() < a["hi_mean"]


def test_stationary_boot_blocks_are_geometric_and_wrap():
    """Recover the index path: run lengths have mean ~ mean_block, and a block
    may run past the end and continue at 0."""
    x = pd.Series(np.arange(400, dtype=float))                    # the value IS the index
    d = w4.stationary_boot(x, mean_block=10, reps=1, seed=9, chunk=1)
    rng = np.random.default_rng(9)
    starts = rng.integers(0, 400, size=(1, 400))
    new = rng.random((1, 400)) < 0.1
    new[:, 0] = True
    pos = np.arange(400)
    last = np.maximum.accumulate(np.where(new, pos[None, :], 0), axis=1)
    idx = (np.take_along_axis(starts, last, axis=1) + (pos[None, :] - last)) % 400
    assert d["means"][0] == idx.mean()
    steps = np.diff(idx[0])
    assert ((steps == 1) | (steps == -399) | new[0, 1:]).all()      # continue, wrap, or restart
    assert 6 < 400 / new.sum() < 16


def test_stationary_boot_refuses_a_short_series():
    with pytest.raises(ValueError):
        w4.stationary_boot(pd.Series(np.ones(30)), mean_block=21)


def test_nw_auto_lag_grows_with_persistence():
    """The plug-in lag is noisy on white noise (2-13 over 12 seeds at T = 4,000,
    measured when this was written), so the test pins what the rule must do:
    a persistent series gets a much longer lag, near the AR(1) theory."""
    rng = np.random.default_rng(0)
    e = rng.normal(0, 1, 4000)
    ar = np.empty_like(e)
    ar[0] = e[0]
    for i in range(1, len(e)):
        ar[i] = 0.6 * ar[i - 1] + e[i]
    lw, la = w4.nw_auto_lag(pd.Series(e)), w4.nw_auto_lag(pd.Series(ar))
    # theory at phi 0.6 with the n = 9 pilot: gamma = 1.1447 (s1/s0)^(2/3), s1/s0 from the
    # truncated AR(1) autocovariances; lag = floor(gamma * 4000^(1/3)) = 27
    phi, n = 0.6, int(np.floor(4 * 40 ** (2 / 9)))
    g = phi ** np.arange(n + 1)
    s0, s1 = g[0] + 2 * g[1:].sum(), 2 * (np.arange(1, n + 1) * g[1:]).sum()
    theory = int(np.floor(1.1447 * (s1 / s0) ** (2 / 3) * 4000 ** (1 / 3)))
    assert abs(la - theory) <= 5
    assert la > 2 * lw
    with pytest.raises(ValueError):
        w4.nw_auto_lag(pd.Series([1.0, 2.0]))
