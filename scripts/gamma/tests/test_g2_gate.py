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
4. **The path bounds** (corrected 2026-10-13): a P&L confined to a range W has
   population sd <= W/2, but the SAMPLE sd the replay prints can reach
   W/2 x sqrt(n/(n-1)), and the not-demeaned rms only W. The old single "bound"
   W/2 bounded neither printed measure.
5. **No lookahead in sizing**: the vol used to size a cycle is from the session
   BEFORE entry, and a cycle that settles after the window (a sealed 2023 close)
   is not in it.
6. **Sizing hits the target ex ante**, and the delta-strike inversion is exact.
7. **The vol cap has no default.**
8. **No 2023 return is read** (added 2026-10-13, after a review found G2(a)'s
   headline and G2(c)'s second method each ran one window into January 2023):
   every window ends on or before 2022-12-30, and the output does not move when
   2023 returns do.
9. **No silent vol substitute** in the model cross-check (added 2026-10-13).
10. **The cost rows the note quotes** (added 2026-10-13): the two relaxations of
    the upper bound, plain Roll beside the delta-adjusted one, and the 21-phase
    robustness.
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


def _window(pnl, nW=1.0):
    p = pd.Series(pnl, dtype=float)
    return pd.DataFrame({"pnl": p, "max_loss": nW, "contracts_at_capital": 1.0})


def test_the_sample_sd_can_exceed_half_the_range_and_the_bound_allows_for_it():
    # Two cycles, one untouched and one full-wing loss: the extreme case. The
    # ddof=1 sd is W/sqrt(2) > W/2, which the pre-2026-10-13 "bound" (W/2) missed.
    s = G.window_stats(_window([0.0, -1.0]), vol_cap=10.0)
    assert s["vol"] > 0.5 * math.sqrt(12) + 1e-9
    assert s["vol"] <= s["bound_sd"] + 1e-12
    assert s["bound_sd"] == pytest.approx(0.5 * math.sqrt(2) * math.sqrt(12))


def test_the_not_demeaned_vol_is_bounded_only_by_the_full_range():
    # Repeated full-wing losses: sd 0, rms W. Only bound_rms (= W) bounds it.
    s = G.window_stats(_window([-1.0] * 6), vol_cap=10.0)
    assert s["vol"] == pytest.approx(0.0)
    assert s["rms_vol"] == pytest.approx(math.sqrt(12))
    assert s["rms_vol"] > s["bound_sd"]
    assert s["rms_vol"] <= s["bound_rms"] + 1e-12


def test_both_bounds_hold_on_random_zero_credit_paths():
    rng = np.random.default_rng(5)
    for _ in range(300):
        n = int(rng.integers(2, 40))
        nW = rng.uniform(0.01, 0.08, n)
        p = -rng.uniform(0, 1, n) * nW                       # zero credit: P&L in [-nW, 0]
        x = pd.DataFrame({"pnl": p, "max_loss": nW, "contracts_at_capital": 1.0})
        s = G.window_stats(x, vol_cap=10.0)
        assert s["vol"] <= s["bound_sd"] + 1e-12
        assert s["rms_vol"] <= s["bound_rms"] + 1e-12


def test_window_stats_refuses_a_positive_zero_credit_pnl_and_a_single_cycle():
    with pytest.raises(ValueError, match="positive"):
        G.window_stats(_window([0.01, -0.5]), vol_cap=0.2)
    with pytest.raises(ValueError, match="two cycles"):
        G.window_stats(_window([-0.5]), vol_cap=0.2)


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


# -- 8. no 2023 return is read (added 2026-10-13) -----------------------------

def _late_2022_inputs(seed=2):
    """TLT sessions from mid-2022 into 2023, a flat IV, random total returns."""
    idx = pd.bdate_range("2022-06-01", "2023-03-31")
    rng = np.random.default_rng(seed)
    ret = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx)
    iv = pd.Series(0.15, index=idx)
    return iv, ret


def _perturb_2023(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.loc[s.index >= "2023-01-01"] *= 7.0
    return s


def test_fit_sample_windows_all_end_before_2023():
    iv, ret = _late_2022_inputs()
    j = G.fit_sample(iv, ret)
    assert j["win_end"].max() <= pd.Timestamp("2022-12-30")
    # ...and no window that fits is lost: the last one ends on the last 2022 session,
    # and its IV date is 21 sessions before it.
    sessions = ret.index
    assert j["win_end"].max() == pd.Timestamp("2022-12-30")
    assert j.index.max() == sessions[sessions.get_loc(pd.Timestamp("2022-12-30")) - 21]


def test_fit_sample_does_not_move_when_2023_returns_do():
    iv, ret = _late_2022_inputs()
    pd.testing.assert_frame_equal(G.fit_sample(iv, ret), G.fit_sample(iv, _perturb_2023(ret)))


def _book_inputs():
    iv, ret = _late_2022_inputs(seed=4)
    rng = np.random.default_rng(9)
    book = pd.Series(rng.normal(0, 0.002, len(ret)), index=ret.index)
    return book, iv, ret


def test_varswap_windows_never_end_after_2022():
    from scripts.gamma import book_vs_shortvol as B
    book, iv, ret = _book_inputs()
    d = B.varswap_windows(book, iv, ret, "2022-06-01", B.FIT_END)
    assert len(d) > 0
    assert d["end"].max() <= pd.Timestamp("2022-12-30")


def test_varswap_windows_do_not_move_when_2023_data_do():
    from scripts.gamma import book_vs_shortvol as B
    book, iv, ret = _book_inputs()
    a = B.varswap_windows(book, iv, ret, "2022-06-01", B.FIT_END)
    b = B.varswap_windows(_perturb_2023(book), iv, _perturb_2023(ret), "2022-06-01", B.FIT_END)
    pd.testing.assert_frame_equal(a, b)


def test_varswap_windows_refuse_a_bound_in_the_holdout():
    from scripts.gamma import book_vs_shortvol as B
    book, iv, ret = _book_inputs()
    with pytest.raises(ValueError, match="sealed"):
        B.varswap_windows(book, iv, ret, "2022-06-01", "2023-03-31")


# -- 9. no silent vol substitute in the model mark (added 2026-10-13) ----------

def test_model_mark_raises_on_a_vxtlt_gap_instead_of_using_the_entry_vol():
    tlt, vx = _synthetic(0.12)
    gap = vx.index[(vx.index >= "2010-06-01") & (vx.index <= "2010-06-15")]   # 11 sessions > ffill 5
    vx = vx.drop(gap)
    with pytest.raises(ValueError, match="VXTLT"):
        G.model_mark(tlt, vx, 0.20)


# -- 10. the cost rows and robustness the note quotes (added 2026-10-13) --------

def _roll_and_indicative():
    months = ["2024-01", "2024-02", "2024-03"]
    rows = []
    for k, m in enumerate(months):
        for b, base in (("atm", 0.010), ("call_wing", 0.008), ("put_wing", 0.007)):
            rows.append(dict(month=m, bucket=b, roll=base * (1 + 0.1 * k) if k != 1 else np.nan,
                             roll_adj=base * 1.2 * (1 + 0.1 * k), rho=0.4))
    roll = pd.DataFrame(rows)
    ind = pd.DataFrame(dict(snapshot=["s1"] * 4, spot=100.0, leg=["atm_call", "atm_put", "put_wing", "call_wing"],
                            width=[0.02, 0.02, 0.01, 0.01]))
    idx = pd.bdate_range("2024-01-01", "2024-03-31")
    tlt = pd.DataFrame({"close": 100.0}, index=idx)
    return roll, ind, tlt


def test_relaxation_rows_relax_one_convention_each():
    roll, ind, tlt = _roll_and_indicative()
    rows = G.cost_rows(roll, ind, tlt).set_index("rule")["cost_pct_S"]
    assert sum(r.startswith("UPPER") for r in rows.index) == 1            # the gate reads exactly one
    ub = rows[[r for r in rows.index if r.startswith("UPPER")][0]]
    relax1 = rows[[r for r in rows.index if r.startswith("relax (1)")][0]]
    relax2 = rows[[r for r in rows.index if r.startswith("relax (2)")][0]]
    assert relax1 == pytest.approx(ub / 2)
    corr = roll.assign(c=roll.roll_adj / (1 - roll.rho) / 100.0).groupby("bucket")["c"].median()
    w = ind.set_index("leg")["width"] / 100.0
    want = (2 * max(w["atm_call"], corr["atm"]) + max(w["put_wing"], corr["put_wing"])
            + max(w["call_wing"], corr["call_wing"]))
    assert relax2 == pytest.approx(want)


def test_plain_roll_row_excludes_undefined_months_and_never_fills_them():
    roll, ind, tlt = _roll_and_indicative()
    rows = G.cost_rows(roll, ind, tlt).set_index("rule")["cost_pct_S"]
    plain = rows[[r for r in rows.index if "PLAIN" in r][0]]
    med = roll.dropna(subset=["roll"]).groupby("bucket")["roll"].median() / 100.0
    assert plain == pytest.approx((2 * med["atm"] + med["put_wing"] + med["call_wing"]) / 2)
    cmp_ = G.roll_comparison(roll)
    assert (cmp_["both_defined"] == 2).all() and (cmp_["adj_above_plain"] == 2).all()


def test_phase_robustness_at_zero_cost_includes_the_headline_phase():
    rng = np.random.default_rng(8)
    n = 21 * 30
    j = pd.DataFrame({"iv": rng.uniform(0.10, 0.20, n)}, index=pd.bdate_range("2005-01-03", periods=n))
    j["rv"] = j["iv"] * rng.uniform(0.6, 1.3, n)
    j["nv_over_S"] = G.fly_net_vega_over_S(j["iv"].to_numpy())
    p = G.phase_robustness(j, 0.0)
    t0 = G.net_stats(j.iloc[::21], 0.0)["var_t"]
    assert p["t_min"] - 1e-12 <= t0 <= p["t_max"] + 1e-12
    assert p["n_pos"] + p["n_neg"] == 21


def test_assignment_exposure_is_one_short_leg_between_the_wings_and_none_beyond():
    c = pd.DataFrame({"S0": [100.0, 100.0, 100.0, 100.0], "S1": [103.0, 97.0, 106.0, 100.0],
                      "fly_sd_I": [1.0, 1.0, 1.0, 1.0]})
    a = G.assignment_exposure(c, "I")
    assert a["assigned"].tolist() == [True, True, False, False]       # beyond a wing, or pinned: none
    assert a["side"].tolist() == [-1.0, 1.0, 0.0, 0.0]               # call assigned: short; put: long
    k = G.spec.VOL_TARGET / math.sqrt(12) / 1.0
    assert a["notional_frac"].iloc[0] == pytest.approx(k * 103.0)
    assert a["notional_frac"].iloc[2] == 0.0
