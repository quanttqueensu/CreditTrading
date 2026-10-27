"""Tests for the shared inference module.

WHY THESE. Each published figure below is a worked example from the paper that
defines the method, and reproducing it is the check that the formula was
transcribed correctly (`docs/REFERENCES.md` §12rm gives the sources). The parity
tests pin that this module and the desk's existing copies agree, so moving a
trial onto it changes no past number. The PBO and read_result tests run on
synthetic data, so they are statements about the code, never about the market
(CLAUDE.md data rules).
"""
from __future__ import annotations

import sys
from math import comb, sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.research import inference as I

REPO = Path(__file__).resolve().parents[3]


# -- published worked examples ------------------------------------------------

def test_dsr_reproduces_bailey_lopez_de_prado_worked_example():
    # SR 2.5 annualised on 5y of daily data (T=1250, 250/yr), N=100, V[SR_n]=1/2
    # annualised, skew -3, raw kurtosis 10 -> SR0 0.1132, DSR 0.9004 (fails 95%).
    d, sr0 = I.dsr(2.5 / sqrt(250), 1250, -3, 10, 100, 0.5 / 250)
    assert sr0 == pytest.approx(0.1132, abs=5e-5)
    assert d == pytest.approx(0.9004, abs=5e-5)
    # ... the same strategy passes at N=46, and with normal returns up to N=88.
    assert I.dsr(2.5 / sqrt(250), 1250, -3, 10, 46, 0.5 / 250)[0] == pytest.approx(0.9505, abs=5e-5)
    assert I.dsr(2.5 / sqrt(250), 1250, 0, 3, 88, 0.5 / 250)[0] > 0.95
    assert I.dsr(2.5 / sqrt(250), 1250, 0, 3, 89, 0.5 / 250)[0] < 0.95


def test_sharpe_power_matches_rej_seager_bouchaud():
    # True SR 0.5 over 20y: power 0.61 at 5% two-sided, 0.146 at 99.9%;
    # ~43y to reach 99.9% significance (50% power), ~68y for 80% power.
    assert I.sharpe_power(0.5, 20) == pytest.approx(0.609, abs=1e-3)
    assert I.sharpe_power(0.5, 20, alpha=0.001) == pytest.approx(0.146, abs=1e-3)
    assert I.years_needed(0.5, power=0.5, alpha=0.001) == pytest.approx(43.3, abs=0.1)
    assert I.years_needed(0.5, power=0.8, alpha=0.001) == pytest.approx(68.3, abs=0.1)


def test_events_needed_matches_kothari_warner():
    # Lowest-volatility decile (daily SD 0.014): 21 events detect 1% on day 0 with
    # 90% power. (Their highest-decile figure of 60 is not reproduced by the
    # formula, which gives 58.5; it is not pinned here.)
    assert np.ceil(I.events_needed(0.01, 0.014, 1, power=0.9)) == 21
    # Power falls with the window: the same AR spread over L days needs L times
    # the events.
    assert I.events_needed(0.01, 0.014, 20) == pytest.approx(20 * I.events_needed(0.01, 0.014, 1))


def test_cluster_inflation_matches_kothari_warner():
    assert I.cluster_se_inflation(100, 0.02) == pytest.approx(1.73, abs=5e-3)
    assert I.cluster_se_inflation(1, 0.5) == 1.0


def test_pbo_split_count_is_c_16_8_not_the_printed_12780():
    rng = np.random.default_rng(0)
    assert I.pbo_cscv(rng.normal(size=(320, 5)), S=16)["n_splits"] == comb(16, 8) == 12870


# -- parity with the desk's existing copies -----------------------------------

def test_desk_dsr_is_validate_dsr_exactly():
    sys.path.insert(0, str(REPO / "scripts" / "cef"))
    import validate as V
    for obs, T, sk, ku, n in [(1.2, 2520, -0.5, 6, 52), (0.6, 1500, 0.2, 4, 10), (0.9, 800, -1, 9, 6)]:
        assert I.desk_dsr(obs, T, sk, ku, n) == pytest.approx(V._dsr(obs, T, sk, ku, n)[0], abs=1e-12)


def test_desk_bar_is_the_upper_bound_and_stricter_than_the_expected_max():
    for n in (6, 10, 52, 162):
        assert I.upper_bound_max_z(n) > I.expected_max_z(n)
    assert I.upper_bound_max_z(52) == pytest.approx(2.811, abs=1e-3)   # orient's CEF bar
    assert I.expected_max_z(52) == pytest.approx(2.291, abs=1e-3)


def test_newey_west_matches_vrp_summary_and_statsmodels():
    from scripts.gamma.vrp_summary import newey_west_t as nw_desk
    import statsmodels.api as sm
    rng = np.random.default_rng(7)
    x = rng.normal(0.05, 1, 600)
    x = x + 0.5 * np.r_[0, x[:-1]]                       # MA(1): HAC matters
    t = I.newey_west_t(x, 5)
    assert t == pytest.approx(nw_desk(pd.Series(x), 5), abs=1e-12)
    fit = sm.OLS(x, np.ones_like(x)).fit(cov_type="HAC",
                                         cov_kwds={"maxlags": 5, "use_correction": False})
    assert t == pytest.approx(fit.tvalues[0], abs=1e-9)


def test_p_clear_bar_reproduces_the_e1_preregistration_forecast():
    # PREREG_E1_MERGER_PAIR_2026-10-19.md (branch trial-events-e1): at a true
    # Sharpe 0.67 over 13 years, P(alpha t >= 3.0) ~= 0.28.
    assert I.p_clear_bar(0.67 * sqrt(13), 3.0) == pytest.approx(0.28, abs=5e-3)


# -- behaviour on synthetic data ----------------------------------------------

def test_pbo_is_near_half_on_noise_and_near_zero_with_a_dominant_edge():
    # On noise PBO is a half only ON AVERAGE across datasets. One fixed sample
    # ranged 0.09-0.93 across 40 seeds (2026-10-27): a column that drew a lucky
    # full-sample mean looks good in both halves. So one PBO on one panel is a
    # noisy reading. Report it with N and S, never as a verdict on its own.
    v = [I.pbo_cscv(np.random.default_rng(s).normal(size=(400, 20)), S=8)["pbo"]
         for s in range(40)]
    assert 0.4 < np.mean(v) < 0.7
    noise = np.random.default_rng(11).normal(size=(1000, 40))
    edge = noise.copy()
    edge[:, 0] += 0.5
    assert I.pbo_cscv(edge)["pbo"] < 0.01


def test_pbo_refuses_what_it_cannot_rank():
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError):
        I.pbo_cscv(rng.normal(size=(100, 1)))            # one trial
    with pytest.raises(ValueError):
        I.pbo_cscv(rng.normal(size=(100, 4)), S=7)        # odd S
    x = rng.normal(size=(100, 4))
    x[3, 2] = np.nan
    with pytest.raises(ValueError):
        I.pbo_cscv(x)


def test_bh_is_step_up():
    assert I.bh_fdr([0.01, 0.02, 0.03, 0.5]).tolist() == [True, True, True, False]
    # 0.013 fails its own threshold (0.0125) but is rejected because 0.02 passes
    # a later one: the step-up property.
    assert I.bh_fdr([0.02, 0.013, 0.5, 0.5]).tolist() == [True, True, False, False]
    assert not I.bh_fdr([0.2, 0.3]).any()


def test_read_result_separates_absent_from_inconclusive():
    # Powered null: the interval excludes every effect worth trading.
    assert I.read_result(1.0, 2.0, 30.0)["outcome"] == "ABSENT"
    # Wide null: cannot rule out the meaningful effect -> not a kill.
    assert I.read_result(-58.0, 104.0, 30.0)["outcome"] == "INCONCLUSIVE"
    # Present but below the meaningful size: evidence is not the expression gate.
    r = I.read_result(10.0, 4.0, 30.0)
    assert r["outcome"] == "PRESENT" and r["below_meaningful"]
    # A significant effect of the wrong sign is ABSENT for this hypothesis.
    assert I.read_result(-20.0, 5.0, 10.0)["outcome"] == "ABSENT"


def test_marginal_gain_agrees_with_combined_sharpe():
    # A sleeve at exactly rho * SR_book adds nothing; above it, the book improves.
    assert I.marginal_gain(0.5, 1.0, 0.5) == pytest.approx(0.0)
    assert I.combined_sharpe(1.0, 0.5, 0.5) == pytest.approx(1.0)
    assert I.combined_sharpe(1.0, 0.6, 0.5) > 1.0
    # Uncorrelated: five 0.5s combine to sqrt(5)*0.5 ~= 1.12 (the D5 legend's "about 1.1").
    sr = 0.5
    for _ in range(4):
        sr = I.combined_sharpe(sr, 0.5, 0.0)
    assert sr == pytest.approx(sqrt(5) * 0.5)


def test_effective_trials_collapses_correlated_variants():
    assert I.effective_trials(20, 1.0) == pytest.approx(1.0)
    assert I.effective_trials(20, 0.0) == pytest.approx(20.0)
    with pytest.raises(ValueError):
        I.effective_trials(20, 1.5)


def test_inputs_it_cannot_use_raise():
    with pytest.raises(ValueError):
        I.psr(0.1, 100, skew=50, kurt=3)                  # non-positive variance term
    with pytest.raises(ValueError):
        I.newey_west_t(np.array([1.0, np.nan, 2.0, 3.0]))
    with pytest.raises(ValueError):
        I.mde(0.0, 10)
    with pytest.raises(ValueError):
        I.expected_max_z(1)
