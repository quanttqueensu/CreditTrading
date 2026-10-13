"""Gate G2's estimators and replay mechanics, on synthetic inputs only.

WHY THESE
---------
Every conclusion in `results/gamma/G2_GATE_FREE_DATA_2026-10-12.md` rests on a
handful of mechanical claims that are easy to get subtly wrong and that nothing
downstream would notice:

1. **Roll's persistence bias is s(1 - rho).** The upper-bound spread divides by
   (1 - rho_hat); if the factor were wrong the "upper bound" would be neither.
   Checked by simulating the model it is derived for (a claim about the code,
   not about the market).
2. **A sweep is one trade.** Same-millisecond prints are collapsed before any
   difference is taken; otherwise zero price changes dilute the covariance.
3. **The zero-credit payoff is the four legs' intrinsic sum, capped at the wing.**
   The replay's whole bounded-loss argument is that cap.
4. **The any-path vol bound**: a P&L confined to a range W has sd <= W/2.
5. **No lookahead in sizing**: the vol used to size a cycle is from the session
   BEFORE entry, and a cycle that settles after the window (a sealed 2023 close)
   is not in it.
6. **Sizing hits the target ex ante**, and the delta-strike inversion is exact.
7. **The vol cap has no default.**
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

from scripts.gamma import g2_gate as G  # noqa: E402
from scripts.gamma import g2_spreads as SP  # noqa: E402


# -- 1. Roll and its persistence bias ---------------------------------------

def _simulate_roll(s, rho, n=400_000, seed=7):
    """Efficient price random walk, trade signs a symmetric Markov chain with sign
    autocorrelation rho, observed price m + (s/2) q."""
    rng = np.random.default_rng(seed)
    stay = (1 + rho) / 2
    q = np.empty(n)
    q[0] = 1.0
    flips = rng.random(n) > stay
    for i in range(1, n):
        q[i] = -q[i - 1] if flips[i] else q[i - 1]
    m = np.cumsum(rng.normal(0, s / 10, n))
    p = m + s / 2 * q
    dp = np.diff(p)
    cov = np.mean(dp[1:] * dp[:-1])
    return 2 * math.sqrt(-cov), q


@pytest.mark.parametrize("rho", [0.0, 0.4])
def test_plain_roll_returns_s_times_one_minus_rho(rho):
    s = 0.02
    roll, _ = _simulate_roll(s, rho)
    assert roll == pytest.approx(s * SP.roll_bias_factor(rho), rel=0.03)


def test_the_persistence_correction_recovers_the_spread():
    s, rho = 0.02, 0.4
    roll, q = _simulate_roll(s, rho)
    rho_hat = np.corrcoef(q[1:], q[:-1])[0, 1]
    assert roll / SP.roll_bias_factor(rho_hat) == pytest.approx(s, rel=0.03)


def test_bias_factor_refuses_a_degenerate_chain():
    with pytest.raises(ValueError):
        SP.roll_bias_factor(1.0)


def test_roll_pool_is_undefined_not_zero_when_covariance_is_positive():
    # a steadily trending price: positive serial covariance, no bounce
    tr = pd.DataFrame({"d": ["2024-01-02"] * 6, "expiry": ["2024-02-16"] * 6,
                       "opt_type": ["C"] * 6, "strike": [90.0] * 6, "ms": range(6),
                       "price": [1.00, 1.01, 1.03, 1.06, 1.10, 1.15]})
    r = SP.roll_pool(tr)
    assert np.isnan(r["roll"]) and r["pairs"] == 4


# -- 2. sweeps and tick signs ------------------------------------------------

def test_same_millisecond_prints_collapse_to_one_vwap_trade():
    tr = pd.DataFrame({"d": ["2024-01-02"] * 3, "expiry": ["2024-02-16"] * 3,
                       "opt_type": ["P"] * 3, "strike": [88.0] * 3, "ms": [5, 5, 9],
                       "price": [1.00, 1.02, 1.01], "size": [1, 3, 2]})
    c = SP.collapse_same_time(tr)
    assert len(c) == 2
    assert c.loc[c.ms == 5, "price"].iloc[0] == pytest.approx((1.00 + 3 * 1.02) / 4)
    assert c.loc[c.ms == 5, "size"].iloc[0] == 4


def test_tick_rule_carries_the_sign_through_a_zero_tick():
    assert SP.tick_signs(np.array([1.0, 1.01, 1.01, 1.00, 1.00])).tolist() == [0, 1, 1, -1, -1]


def test_classification_uses_the_previous_close_it_is_given():
    s_prev = pd.Series({pd.Timestamp("2024-01-03"): 100.0})
    tr = pd.DataFrame({"d": ["2024-01-03"] * 3, "expiry": ["2024-02-02"] * 3,
                       "opt_type": ["C", "P", "C"], "strike": [100.0, 95.0, 120.0],
                       "ms": [1, 2, 3], "price": [1.0, 0.3, 0.01], "size": [1, 1, 1]})
    out = SP.classify(tr, s_prev)
    assert out["bucket"].tolist() == ["atm", "put_wing", None]


# -- 3, 4. payoffs and the bound ----------------------------------------------

def test_fly_payoff_is_the_four_legs_capped_at_the_wing():
    K, w = 100.0, 0.05
    ST = np.linspace(80, 120, 401)
    legs = (np.maximum(ST - K, 0) + np.maximum(K - ST, 0)
            - np.maximum(ST - K * (1 + w), 0) - np.maximum(K * (1 - w) - ST, 0))
    np.testing.assert_allclose(G.fly_payoff(ST, K, w), legs, atol=1e-12)
    assert G.fly_payoff(ST, K, w).max() == pytest.approx(K * w)


def test_condor_payoff_never_exceeds_its_widest_wing():
    ST = np.linspace(50, 150, 1001)
    p = G.condor_payoff(ST, 95, 90, 105, 112)
    assert p.min() == 0 and p.max() == pytest.approx(7.0)


def test_any_path_sd_is_at_most_half_the_range():
    rng = np.random.default_rng(3)
    for _ in range(200):
        x = rng.uniform(-1.0, 0.0, rng.integers(2, 30))          # P&L in [-(W-C), C], W = 1
        x[rng.integers(0, len(x))] = -1.0
        assert x.std(ddof=0) <= 0.5 + 1e-12


# -- 5, 6. calendar, lookahead, sizing ---------------------------------------

def test_good_friday_moves_the_expiration_to_thursday():
    sessions = pd.bdate_range("2008-03-01", "2008-04-30").drop(pd.Timestamp("2008-03-21"))
    e = G.monthly_expiries(sessions)
    assert pd.Timestamp("2008-03-20") in e and pd.Timestamp("2008-04-18") in e


def _synthetic(vx_on_entry: float):
    idx = pd.bdate_range("2010-01-01", "2010-12-31")
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.008, len(idx))
    close = 100 * np.exp(np.cumsum(r))
    tlt = pd.DataFrame({"close": close, "ret_total": np.expm1(r)}, index=idx)
    vx = pd.Series(0.12, index=idx)
    for e in G.monthly_expiries(idx):
        vx.loc[e] = vx_on_entry                     # a sentinel ON each entry day
    return tlt, vx


def test_sizing_never_reads_the_entry_day_vol():
    a = G.cycles(*_synthetic(0.12), "2010-04-01", "2010-12-31")
    b = G.cycles(*_synthetic(5.00), "2010-04-01", "2010-12-31")
    pd.testing.assert_series_equal(a["sig_I"], b["sig_I"])
    assert (a["sig_I"] == 0.12).all()


def test_a_cycle_settling_after_the_window_is_excluded():
    tlt, vx = _synthetic(0.12)
    c = G.cycles(tlt, vx, "2010-04-01", "2010-11-30")
    assert c["expiry"].max() <= pd.Timestamp("2010-11-30")
    assert c.index.max() < pd.Timestamp("2010-11-01")


def test_sizing_puts_the_ex_ante_annualised_sd_at_the_spec_vol_target():
    c = G.cycles(*_synthetic(0.12), "2010-04-01", "2010-12-31")
    x = G.sized(c, "fly", "I")
    k = x["max_loss"] / c["fly_W"]                   # n*100/capital per $ of payoff
    np.testing.assert_allclose(k * c["fly_sd_I"] * math.sqrt(12), G.spec.VOL_TARGET, rtol=1e-12)


def test_payoff_sd_matches_monte_carlo():
    rng = np.random.default_rng(11)
    S, T, sig = 100.0, 30 / 365, 0.15
    ST = S * np.exp(-0.5 * sig ** 2 * T + sig * math.sqrt(T) * rng.standard_normal(2_000_000))
    mc = G.fly_payoff(ST, S).std()
    assert G.payoff_sd(lambda x: G.fly_payoff(x, S), S, T, sig) == pytest.approx(mc, rel=0.01)


def test_strike_for_delta_inverts_black_scholes_delta():
    from scipy.stats import norm
    S, T, sig = 100.0, 30 / 365, 0.14
    for cp, target in (("C", 0.20), ("P", 0.20), ("C", 0.05), ("P", 0.05)):
        K = G.strike_for_delta(S, T, sig, target, cp)
        d1 = (math.log(S / K) + 0.5 * sig ** 2 * T) / (sig * math.sqrt(T))
        delta = norm.cdf(d1) if cp == "C" else norm.cdf(d1) - 1
        assert abs(delta) == pytest.approx(target, abs=1e-9)


def test_zero_cost_net_is_the_gross_premium():
    m = pd.DataFrame({"iv": [0.15, 0.14, 0.16], "rv": [0.13, 0.15, 0.12]})
    m["nv_over_S"] = G.fly_net_vega_over_S(m["iv"].to_numpy())
    s = G.net_stats(m, 0.0)
    assert s["ivrv_net"] == pytest.approx(((m.iv - m.rv) * 100).mean())
    assert s["var_net"] == pytest.approx(((m.iv ** 2 - m.rv ** 2) * 1e4).mean())


# -- 7. no default cap ---------------------------------------------------------

def test_replay_refuses_without_a_vol_cap(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["g2_gate.py", "replay"])
    with pytest.raises(SystemExit, match="vol-cap"):
        G.main()
