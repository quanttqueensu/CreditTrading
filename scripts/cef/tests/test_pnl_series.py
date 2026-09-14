"""The harness extensions W14 Part A added, and the two ways they could rot.

WHY THIS FILE EXISTS
--------------------
Three things were added to `band_frontier.py` on 2026-09-11 so that W14 could
ask questions about the SHAPE of the book's P&L rather than its first two
moments:

    evaluate(...)["pnl"]     the daily P&L series the statistics come from
    build_panel()            the signal panel, split out of build_targets
    distribution_yield()     the cash leg the raw price panel omits
    total_returns()          price returns + that cash leg

Each is a place where a second copy of something load-bearing could appear:

  * `pnl` could drift from the statistics if someone recomputed it instead of
    returning the object -- and, worse, could acquire its own execution lag.
    The shift(1) incident of 2026-09-10 (gross 1.27 -> 0.94) was exactly a
    second copy of the convention disagreeing with the first.
  * `build_panel` could stop producing the panel `build_targets` uses. The
    split was proved a byte-for-byte no-op once; nothing kept it one.
  * `distribution_yield` could acquire a silent fallback. A zero there is
    indistinguishable from "this fund paid nothing" and has the opposite
    meaning, which is the shape of `fee.fillna(fee.median())`.

Every test below was checked to FAIL against the behaviour it guards before it
was kept -- the shift test against `shift(1)`, the no-op test against a panel
with `mu`/`sd` un-shifted, the raise test against a `.fillna(0.0)` fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.cef import band_frontier as BF  # noqa: E402


# --- evaluate()["pnl"] ------------------------------------------------------

def _toy():
    idx = pd.bdate_range("2020-01-01", periods=40)
    cols = ["A", "B"]
    rng = np.random.default_rng(7)
    H = pd.DataFrame(rng.normal(size=(40, 2)), index=idx, columns=cols)
    R = pd.DataFrame(rng.normal(scale=0.01, size=(40, 2)), index=idx, columns=cols)
    return H, R


def test_pnl_is_the_series_the_statistics_are_moments_of():
    """Not a recomputation: the reported Sharpe must BE this series' Sharpe."""
    H, R = _toy()
    r = BF.evaluate(H, R)
    pnl = r["pnl"]
    assert isinstance(pnl, pd.Series)
    assert np.isclose(pnl.mean() / pnl.std() * np.sqrt(252), r["gross_sr"])
    assert np.isclose(pnl.mean() * 252, r["ann_ret"])
    assert np.isclose(pnl.std() * np.sqrt(252), r["vol"])


def test_pnl_carries_the_shift_2_convention():
    """The returned series must be lagged two sessions, not one.

    A panel whose returns are known only at t+2 from the weights at t is
    monetised iff the lag is 2. Verified to fail when `evaluate` was
    temporarily regressed to `H.shift(1)`.
    """
    idx = pd.bdate_range("2020-01-01", periods=60)
    rng = np.random.default_rng(11)
    R = pd.DataFrame(rng.normal(scale=0.01, size=(60, 1)), index=idx, columns=["A"])
    H = (-R).shift(-2).fillna(0.0)        # weights at t point at the t+2 return
    pnl = BF.evaluate(H, R)["pnl"]
    assert pnl.sum() < 0, "a book aimed at t+2 earned nothing; the lag moved"
    H1 = (-R).shift(-1).fillna(0.0)       # aimed at the UNREACHABLE t+1 return
    assert abs(BF.evaluate(H1, R)["pnl"].sum()) < abs(pnl.sum()) / 5, (
        "a book aimed at the t+1 return -- which needs t's NAV, published after "
        "t's close -- was monetised; the execution lag has regressed")


def test_pnl_does_not_disturb_the_existing_keys():
    """Additive extension: every key `evaluate` used to return is unchanged."""
    H, R = _toy()
    r = BF.evaluate(H, R)
    for k in ("gross_sr", "ann_ret", "vol", "turn", "hold", "turn_series"):
        assert k in r
    assert np.isfinite(r["turn"])


# --- build_panel() ----------------------------------------------------------

def test_build_panel_is_a_noop():
    """Re-deriving the targets from the panel must reproduce build_targets().

    This is the standing form of the one-off hash check done at the split
    (sha256 of pickle.dumps((T, R)) identical before and after). It re-runs the
    target loop against build_panel()'s own arrays, so a panel that stopped
    shifting `mu`/`sd`, or that changed the ADV filter, diverges here.
    """
    from scripts.cef.spec import MIN_ADV_USD, MIN_NAMES, UNIVERSE, VOL_TARGET

    T, R = BF.build_targets()
    p = BF.build_panel()
    ret, z, adv = p["ret"], p["z"], p["adv"]

    tgt = pd.DataFrame(0.0, index=z.index, columns=UNIVERSE)
    start = z.index.searchsorted(pd.Timestamp(BF.SAMPLE_START))
    for i in range(start, len(z.index)):
        row = z.iloc[i].dropna()
        row = row[[t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV_USD]]
        if len(row) < MIN_NAMES:
            tgt.iloc[i] = tgt.iloc[i - 1]
            continue
        w = -(row - row.mean())
        w = w / w.abs().sum()
        hist = (ret[list(row.index)].iloc[:i + 1].mul(w, axis=1)
                .sum(axis=1).tail(BF.VOL_LOOKBACK))
        rv = hist.std() * np.sqrt(252)
        scal = float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0
        tgt.iloc[i] = (w * scal).reindex(UNIVERSE).fillna(0.0).values

    pd.testing.assert_frame_equal(T, tgt.iloc[start:])
    pd.testing.assert_frame_equal(R, ret.reindex(T.index)[UNIVERSE].fillna(0.0))


def test_panel_is_invariant_to_truncation():
    """H7, tested end to end: nothing on date t may depend on data after t.

    Rebuilding the panel from price/NAV history **truncated at the source**
    must reproduce, exactly, every row the full panel produced up to that date.
    This goes through the pivot, the `|ret| < 0.5` filter, the rolling z-score
    AND `adv` -- the point-in-time eligibility gate, which the previous version
    of this test never touched, because it truncated a `disc` frame that had
    already been computed from the full panel. A `bfill` or a centred window
    anywhere in the ADV chain passed that version green and fails this one.

    Verified to fail when `mu`/`sd` were given `.shift(-1)` and when `adv` was
    given `.shift(-1)`.
    """
    full = BF.build_panel()
    cut = full["z"].index[-400]
    part = BF.build_panel(end=cut)
    assert part["z"].index[-1] == cut
    for key in ("px", "nav", "ret", "disc", "z", "adv"):
        pd.testing.assert_frame_equal(part[key], full[key].loc[:cut],
                                      check_freq=False)


def test_the_zscore_is_standardised_against_a_window_that_excludes_its_own_day():
    """`mu`/`sd` are `.shift(1)`, and that is an estimation choice, not a lag.

    Un-shifting them is NOT lookahead -- disc[t] is date-t information and the
    execution convention is shift(2) -- but it puts the observation being
    standardised inside its own reference window, which shrinks |z| for exactly
    the dislocations the book exists to trade. The previous version of this
    check compared build_targets against a re-derivation from the SAME panel,
    so it moved with any change to the panel and passed when `.shift(1)` was
    deleted. This one asserts the value.
    """
    p = BF.build_panel()
    disc, mu, sd = p["disc"], p["mu"], p["sd"]
    i = len(disc) - 5
    col = disc.columns[0]
    window = disc[col].iloc[i - BF.Z_WINDOW:i]          # ends at i-1, excludes i
    assert np.isclose(mu[col].iloc[i], window.mean()), "mu includes its own day"
    assert np.isclose(sd[col].iloc[i], window.std()), "sd includes its own day"
    assert not np.isclose(mu[col].iloc[i], disc[col].iloc[i - BF.Z_WINDOW + 1:i + 1].mean())


# --- distribution_yield() / total_returns() ---------------------------------

def test_distribution_yield_raises_on_a_name_it_cannot_cover():
    """NO SILENT FALLBACKS. A zero here means "paid nothing", not "unknown"."""
    idx = pd.bdate_range("2020-01-01", periods=10)
    with pytest.raises(ValueError, match="NOT_A_FUND"):
        BF.distribution_yield(idx, ["AWF", "NOT_A_FUND"])


def test_total_returns_composes_the_two_corrections():
    """r_total = (1+r_px)*k - 1 + D/P_{t-1}, and both legs are real.

    This test used to assert `Rt - y == R`, which was true only while splits
    were unapplied. It caught the split correction the moment it landed, which
    is the behaviour wanted; it is now the identity for both legs.
    """
    T, R = BF.build_targets()
    y = BF.distribution_yield(R.index, R.columns)
    k = BF.split_factor(R.index, R.columns)
    assert (y >= 0).all().all()
    assert (y > 0).sum().sum() > 3000, "the 17 have thousands of ex-dates since 2005"
    assert y.max().max() < 0.25, "a CEF distribution is not a quarter of its price"
    pd.testing.assert_frame_equal(BF.total_returns(R), (1.0 + R) * k - 1.0 + y)


def test_distribution_yield_raises_rather_than_dropping_an_ex_date():
    """The count check, not just the ticker check.

    `.fillna(0.0)` is right for a date with no ex-date and WRONG for an ex-date
    that fell off the index or lost its prior close (landmine 4: HYT lags the
    price panel by a day). Asking for a window that excludes most of the panel
    leaves ex-dates unbookable and must raise, not silently return zeros.
    """
    T, R = BF.build_targets()
    with pytest.raises(ValueError, match="did not reach the yield matrix"):
        BF.distribution_yield(R.index[::3], R.columns)     # drops 2 of every 3 sessions


def test_the_split_is_applied_and_it_is_not_cosmetic():
    """BIT 2025-08-19: a 1.029 split the raw panel books as a -2.8% return.

    RESEARCH_STATE.md 2026-09-09 names this row and says it "is not applied in
    the harness at all". It is now. The +-50% return filter never touched it,
    so nothing errored and nothing looked wrong -- the harness simply lost the
    money. Verified to fail with `split_factor` returning all ones.
    """
    T, R = BF.build_targets()
    Rt = BF.total_returns(R)
    d = pd.Timestamp("2025-08-19")
    assert np.isclose(R.loc[d, "BIT"], -0.043538, atol=1e-5), "raw panel changed"
    assert np.isclose(Rt.loc[d, "BIT"], -0.015801, atol=1e-5)
    # the correction is the split factor exactly, not an approximation
    assert np.isclose((1 + R.loc[d, "BIT"]) * 1.029 - 1, Rt.loc[d, "BIT"])
    # and it is the ONLY name-date the split panel touches
    k = BF.split_factor(R.index, R.columns)
    assert (k != 1.0).sum().sum() == 1


def test_the_convention_choice_is_the_callers_and_moves_the_number():
    """If total vs price returns made no difference, the extension is pointless.

    It must differ -- the distribution carry has sd 1.23%/yr on the band's
    holdings path -- while leaving the POSITIONS untouched.
    """
    from scripts.cef.spec import BAND_WIDTH
    T, R = BF.build_targets()
    H = BF.band(T, BAND_WIDTH)
    px_pnl = BF.evaluate(H, R)["pnl"]
    tot_pnl = BF.evaluate(H, BF.total_returns(R))["pnl"]
    assert not px_pnl.equals(tot_pnl)
    assert np.isclose(BF.evaluate(H, R)["turn"], BF.evaluate(H, BF.total_returns(R))["turn"]), \
        "the return convention must not change turnover -- positions are identical"
