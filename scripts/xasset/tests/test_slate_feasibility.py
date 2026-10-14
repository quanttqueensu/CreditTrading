"""The slate's bar arithmetic and eligibility rule, on synthetic inputs.

These test the CODE that turns a declared rule into a fit window and a required
Sharpe; they make no claim about any market (CLAUDE.md: synthetic data tests a
method, never the world). No panel is read and no network is touched.
"""
import math

import pandas as pd
import pytest

from scripts.xasset import slate_feasibility as sf


def test_required_sharpe_inverts_the_repo_bar():
    """At the returned Sharpe, validate._dsr sits on its PASS line (0.95), and the
    requirement rises with N and falls with history -- the two directions the
    slate-size argument rests on."""
    from scripts.cef.validate import _dsr
    n_days = 252 * 15
    r5 = sf.required_sharpe(5, n_days)
    d, _, _ = _dsr(r5, n_days, 0.0, 3.0, 5)
    assert d == pytest.approx(0.95, abs=1e-6)
    assert sf.required_sharpe(3, n_days) < r5 < sf.required_sharpe(162, n_days)
    assert sf.required_sharpe(5, 252 * 25) < r5
    # Above the agenda's sr0 reading: DSR 0.95 needs about 1.645 more t than sqrt(2 ln N).
    sr0 = math.sqrt(2 * math.log(5)) / math.sqrt(n_days / 252)
    assert r5 > sr0


def test_fit_window_half_rule_and_lag():
    """Three instruments; 'half' needs two eligible. Eligible at month-end E once
    the first return is on or before the first session after the month-end
    `lag` months earlier."""
    cal = pd.bdate_range("2000-01-03", "2003-12-31")
    firsts = {"A": pd.Timestamp("2000-01-03").date(),
              "B": pd.Timestamp("2000-06-01").date(),
              "C": pd.Timestamp("2002-01-01").date()}   # bdate_range keeps 1 Jan as a session
    first_dec, n_fit, need = sf.fit_window(["A", "B", "C"], 12, "half", firsts, cal)
    assert need == 2
    # B's first return 2000-06-01 is the first session after 2000-05-31, so B is
    # eligible at the month-end 12 months after May 2000.
    assert str(first_dec) == "2001-05-31"
    first_all, _, need_all = sf.fit_window(["A", "B", "C"], 12, "all", firsts, cal)
    assert need_all == 3 and str(first_all) == "2002-12-31"
    # One session late and the whole month is lost: C starting 2002-01-02 misses
    # the window that opens 2002-01-01, so 'all' first holds at 2003-01-31.
    late = dict(firsts, C=pd.Timestamp("2002-01-02").date())
    assert str(sf.fit_window(["A", "B", "C"], 12, "all", late, cal)[0]) == "2003-01-31"


def test_fit_window_raises_when_rule_never_holds():
    cal = pd.bdate_range("2000-01-03", "2000-12-29")
    with pytest.raises(RuntimeError):
        sf.fit_window(["A"], 36, "all", {"A": pd.Timestamp("2000-01-03").date()}, cal)


def test_coverage_raises_for_an_instrument_no_panel_holds():
    cal = pd.bdate_range("2000-01-03", "2000-01-10")
    df = pd.DataFrame({"date": cal, "ticker": "A", "ret_total": 0.0})
    with pytest.raises(KeyError):
        sf.coverage("ZZZ", {"p": df}, cal)


def test_coverage_counts_interior_gaps():
    cal = pd.bdate_range("2000-01-03", "2000-01-14")          # 10 sessions
    df = pd.DataFrame({"date": cal, "ticker": "A", "ret_total": 0.001})
    df.loc[3, "ret_total"] = float("nan")                      # one hole inside the range
    row = sf.coverage("A", {"p": df}, cal)
    assert row["interior_gaps"] == 1 and row["sessions"] == 9


def test_power_is_one_half_at_the_required_sharpe_and_rises_with_it():
    """P(pass) is 0.5 exactly at the Sharpe the bar demands and increases with
    the true Sharpe. The section 2.2 power column rests on this."""
    n_days = 252 * 15
    r = sf.required_sharpe(5, n_days)
    assert sf.power(r, 5, n_days) == pytest.approx(0.5, abs=1e-6)
    assert sf.power(r - 0.3, 5, n_days) < 0.5 < sf.power(r + 0.3, 5, n_days)


# --- revision 3 (2026-10-13): the power arithmetic now takes its T and its SE
# --- from the trial's own conventions (PREREG revision 3, the review's fix 8).

def test_pnl_window_starts_exec_lag_sessions_after_the_decision():
    """Decided at the close of E, filled at E+1, earned on E+2 (H1): the first
    P&L session is two sessions after the first decision, and a later `start`
    (a factor's first return) moves it later, never earlier."""
    cal = pd.bdate_range("2022-11-01", "2023-01-31")
    first_pnl, n = sf.pnl_window(pd.Timestamp("2022-11-30"), cal)
    assert str(first_pnl) == "2022-12-02"
    assert n == int(((cal >= "2022-12-02") & (cal < "2023-01-01")).sum())
    later, n_later = sf.pnl_window(pd.Timestamp("2022-11-30"), cal, start="2022-12-15")
    assert str(later) == "2022-12-15" and n_later < n
    earlier, _ = sf.pnl_window(pd.Timestamp("2022-11-30"), cal, start="2022-11-01")
    assert str(earlier) == "2022-12-02"


def test_sr_se_is_the_dsr_denominator():
    """`_dsr` computes z = (obs - sr0) / SE(obs); `sr_se` must be that SE, so the
    power column and the bar cannot drift apart."""
    from statistics import NormalDist
    from scripts.cef.validate import _dsr
    for obs, T in ((1.2, 3000), (0.3, 5000), (2.0, 1500)):
        d, sr0, _ = _dsr(obs, T, 0.0, 3.0, 5)
        z = NormalDist().inv_cdf(d)
        assert (obs - sr0) / z == pytest.approx(sf.sr_se(obs, T), rel=1e-6)


def test_power_matches_a_simulation_through_dsr():
    """Simulate daily Gaussian returns at a known Sharpe, apply the repo's `_dsr`
    to each path, and count passes. The closed form must sit inside the
    simulation's 99% band. Synthetic: this checks the arithmetic, not a market."""
    import numpy as np
    from scripts.cef.validate import _dsr
    rng = np.random.default_rng(20261013)
    T, n_paths, sr = 252 * 10, 1500, 1.0
    x = rng.standard_normal((n_paths, T)) + sr / math.sqrt(252)
    obs = x.mean(1) / x.std(1, ddof=1) * math.sqrt(252)
    p_mc = float(np.mean([_dsr(o, T, 0.0, 3.0, 5)[0] > 0.95 for o in obs]))
    band = 2.58 * math.sqrt(p_mc * (1 - p_mc) / n_paths)
    assert abs(sf.power(sr, 5, T) - p_mc) < band


def test_sharpe_for_power_and_the_alpha_bar_invert_their_functions():
    T = 252 * 15
    s80 = sf.sharpe_for_power(0.80, 5, T)
    assert sf.power(s80, 5, T) == pytest.approx(0.80, abs=1e-6)
    assert s80 > sf.required_sharpe(5, T)
    bar = sf.alpha_t_bar(T)
    assert bar == pytest.approx(3.0 / math.sqrt(15))
    assert sf.p_alpha_t(bar, T) == pytest.approx(0.5, abs=1e-9)
    assert sf.p_alpha_t(bar - 0.2, T) < 0.5 < sf.p_alpha_t(bar + 0.2, T)


def test_expected_ranges_are_ordered_and_cover_every_test():
    assert set(sf.EXPECTED_SR) == set(sf.TESTS) == set(sf.PUBLISHED_SR)
    for lo, hi, why in sf.EXPECTED_SR.values():
        assert lo <= hi and why
