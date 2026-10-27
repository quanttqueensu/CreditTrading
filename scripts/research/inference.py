"""The desk's one implementation of research inference.

WHY THIS FILE EXISTS. Until 2026-10-27 every trial carried its own copy of its
statistics: a Newey-West t in `scripts/cef/c4_families.py`,
`scripts/events/e1_merger_pair.py` and `scripts/gamma/vrp_summary.py`; a deflated
Sharpe in `scripts/cef/validate.py` and `e1_merger_pair.py`; and power arithmetic
in four feasibility scripts, each with its own conventions. Two trials could
then reach different answers to one question. A zero-trial audit of 82 kills
(`results/research/DESK_METHOD_2026-10-27.md`) found the larger failure:

- power was forecast and then ignored. The NAV-tender pre-registration put
  P(pass) at 0.02, E1's at 0.15. Both trials were spent, and both "failed";
- a null was recorded as "no edge" whether or not the test could have seen one.

This module is to inference what `band_frontier.evaluate()` is to backtests.
Extend it visibly; never fork a private copy into a trial script.

CONVENTIONS, because a units slip here is invisible downstream:
- A Sharpe ratio is PER PERIOD (non-annualised) unless its name ends `_annual`.
- Kurtosis is RAW kurtosis: 3 for a normal distribution, which is pandas
  `.kurt()` + 3.
- `T` counts return observations, not years.
- Every function raises on input it cannot use. None of them returns a
  default (CLAUDE.md: no silent fallbacks).

Sources: `docs/REFERENCES.md` §12rm. That section names each paper and the
worked example each test reproduces.
"""
from __future__ import annotations

import argparse
from itertools import combinations
from math import comb, e, log, sqrt
from statistics import NormalDist

import numpy as np

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def z_crit(alpha: float = 0.05, two_sided: bool = True) -> float:
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    return _N.inv_cdf(1 - alpha / 2) if two_sided else _N.inv_cdf(1 - alpha)


# -- power: before any data is seen ------------------------------------------

def power_of_z(expected_z: float, alpha: float = 0.05, two_sided: bool = True) -> float:
    """P(the test rejects) when its statistic is ~ N(expected_z, 1).

    Everything else in this section reduces to this. The expected z of a true
    effect is effect / SE, so power is a property of the design (n, sigma, the
    window), and it can be computed before any return is looked at.
    """
    c = z_crit(alpha, two_sided)
    p = 1 - _N.cdf(c - expected_z)
    if two_sided:
        p += _N.cdf(-c - expected_z)
    return p


def p_clear_bar(expected_t: float, bar: float) -> float:
    """P(observed t >= bar) when the t is ~ N(expected_t, 1).

    This is the chance that a one-sided gate passes: alpha t >= 3.0 for D4, a
    net t >= 2.0, and so on. E1's pre-registration forecast 0.28 for its D4 gate
    at a true Sharpe of 0.67 over 13 years: expected t 0.67·√13 = 2.42. The trial
    was spent, and the gate failed. A gate whose pass chance at a plausible
    effect is below a half is more likely to kill a real effect than to find it.
    """
    return 1 - _N.cdf(bar - expected_t)


def sharpe_power(sr_annual: float, years: float, alpha: float = 0.05,
                 two_sided: bool = True) -> float:
    """Power of a t-test that a strategy's Sharpe is non-zero.

    Under IID returns the expected t of an annualised Sharpe over Y years is
    SR·√Y (the ½SR² term in the SE is negligible at per-period scale). At a true
    0.5 over 20 years this gives 0.61 at 5% two-sided and 0.146 at 99.9%
    (Rej, Seager & Bouchaud 2018). A Sharpe-0.5 sleeve is a coin toss to detect
    in a lifetime.
    """
    if years <= 0:
        raise ValueError(f"years must be positive, got {years}")
    return power_of_z(sr_annual * sqrt(years), alpha, two_sided)


def years_needed(sr_annual: float, power: float = 0.8, alpha: float = 0.05,
                 two_sided: bool = True) -> float:
    """Years of data for `power` to detect a true annualised Sharpe."""
    if sr_annual <= 0:
        raise ValueError(f"sr_annual must be positive, got {sr_annual}")
    return ((z_crit(alpha, two_sided) + _N.inv_cdf(power)) / sr_annual) ** 2


def mde(sigma: float, n: float, alpha: float = 0.05, power: float = 0.8,
        two_sided: bool = True) -> float:
    """Minimum detectable mean effect for n INDEPENDENT observations of sd sigma.

    n counts independent units: distinct issuer-months or event clusters, never
    raw rows. Use `cluster_se_inflation` on the SE when events share dates. At
    80% power and 5% two-sided this is ≈ 2.8·sigma/√n, the rule the SS desk's
    event-econometrician seat used.
    """
    if n <= 0 or sigma <= 0:
        raise ValueError(f"need sigma > 0 and n > 0, got sigma={sigma}, n={n}")
    return (z_crit(alpha, two_sided) + _N.inv_cdf(power)) * sigma / sqrt(n)


def events_needed(abnormal: float, sigma_daily: float, window_days: float = 1,
                  alpha: float = 0.05, power: float = 0.8,
                  two_sided: bool = True) -> float:
    """Events needed to detect a mean abnormal return spread over a window.

    Kothari & Warner (2007), assuming independent events:
    N ≈ ((z_{1-α/2} + z_power)·σ·√L / AR)². Power falls with the window length L
    and with σ. A long-hold event sleeve on volatile names needs far more events
    than a one-day reaction. σ must be MEASURED: non-event windows before
    2023-01-01, or a cited paper. Never assume it.
    """
    if abnormal == 0 or sigma_daily <= 0 or window_days <= 0:
        raise ValueError("need abnormal != 0, sigma_daily > 0, window_days > 0")
    return ((z_crit(alpha, two_sided) + _N.inv_cdf(power))
            * sigma_daily * sqrt(window_days) / abs(abnormal)) ** 2


def cluster_se_inflation(n: int, rho: float) -> float:
    """Factor by which a naive SE understates the true one for n events whose
    returns correlate at rho: √(1 + (n−1)ρ) (Kothari & Warner 2007). At n=100
    and rho=0.02 it is 1.73, so a naive t of 3.4 is really about 2.0. That is a
    false positive, which is why calendar-time portfolios are the headline."""
    if n < 1 or not -1 / max(n - 1, 1) <= rho <= 1:
        raise ValueError(f"need n >= 1 and a feasible rho, got n={n}, rho={rho}")
    return sqrt(1 + (n - 1) * rho)


# -- multiple testing: the bar a best-of-N result must clear -----------------

def expected_max_z(n: float) -> float:
    """E[max of n IID N(0,1)] ≈ (1−γ)Z⁻¹(1−1/n) + γZ⁻¹(1−1/(ne)).

    Bailey & López de Prado (2014). The desk's counter bar √(2 ln N) is the
    UPPER BOUND on this quantity, not the quantity itself. At N=52 the two are
    2.29 and 2.81. A stricter bar is a choice, so state which one you used.
    """
    if n < 2:
        raise ValueError(f"expected maximum needs n >= 2, got {n}")
    return ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n)
            + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * e)))


def upper_bound_max_z(n: float) -> float:
    """√(2 ln N): the bar `ops/orient.py` and `validate._dsr` derive from the counter."""
    if n < 2:
        raise ValueError(f"bar needs n >= 2, got {n}")
    return sqrt(2 * log(n))


def effective_trials(m: int, rho_bar: float) -> float:
    """Independent trials implied by M correlated ones: N̂ = ρ̄ + (1−ρ̄)M.

    Bailey & López de Prado (2014). Twenty variants at correlation near one
    are about one trial (Arnott, Harvey & Markowitz 2019). The counter table
    records raw M. Counting correlated variants as independent raises the bar
    and rejects true effects. ρ̄ must come from the stored trial P&L series,
    never be guessed.
    """
    if m < 1 or not 0 <= rho_bar <= 1:
        raise ValueError(f"need m >= 1 and 0 <= rho_bar <= 1, got m={m}, rho={rho_bar}")
    return rho_bar + (1 - rho_bar) * m


def psr(sr: float, T: int, skew: float, kurt: float, sr_star: float = 0.0) -> float:
    """Probabilistic Sharpe ratio: P(true SR > sr_star) (Bailey & López de Prado 2012).

    sr and sr_star are per period, and kurt is raw. Fat tails and negative skew
    widen the SE, so the same Sharpe on a short-put-like payoff earns less
    confidence.
    """
    if T < 2:
        raise ValueError(f"PSR needs T >= 2, got {T}")
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        raise ValueError(f"PSR variance term is non-positive ({denom}); check skew/kurt units")
    return _N.cdf((sr - sr_star) * sqrt(T - 1) / sqrt(denom))


def dsr(sr: float, T: int, skew: float, kurt: float, n_trials: float,
        sr_var: float, bound: str = "gumbel") -> tuple[float, float]:
    """Deflated Sharpe ratio. Returns (DSR, SR0), both on the per-period scale.

    SR0 = √V[SR_n]·E[max of N] is the best Sharpe that N skill-less trials are
    expected to produce. sr_var is the cross-trial variance of per-period
    Sharpes, measured from the stored trial series where they exist.
    `bound="gumbel"` is the paper's expected maximum. `bound="upper"` uses
    √(2 ln N), the desk's bar. Report both; the team lead rules which one gates.
    Reproduces the paper's worked example (DSR 0.9004) in the tests.
    """
    if sr_var <= 0:
        raise ValueError(f"sr_var must be positive, got {sr_var}")
    m = {"gumbel": expected_max_z, "upper": upper_bound_max_z}[bound](n_trials)
    sr0 = sqrt(sr_var) * m
    return psr(sr, T, skew, kurt, sr0), sr0


def desk_dsr(sr_annual: float, T: int, skew: float, kurt: float,
             n_trials: float) -> float:
    """`scripts/cef/validate.py::_dsr`, restated on the scale above.

    That function uses the upper bound and sets V[SR_n] = 1/T, the sampling
    variance of a single skill-less Sharpe, in place of a measured cross-trial
    spread. The parity test pins this equivalence. Changing the desk's bar is a
    governance change, not a refactor.
    """
    return dsr(sr_annual / sqrt(252), T, skew, kurt, n_trials, 1 / T, bound="upper")[0]


def p_pass_dsr(sr_true_annual: float, T: int, n_trials: float, sr_var: float | None = None,
               conf: float = 0.95, bound: str = "upper", periods: int = 252) -> float:
    """Chance a strategy whose true annualised Sharpe is sr_true clears DSR > conf.

    Normal approximation with normal returns: SR_hat ~ N(SR, (1 + ½SR²)/(T−1)),
    and the gate passes iff SR_hat > SR0 + z_conf·SE. sr_var=None means the
    desk's null-implied 1/T. Compute this BEFORE spending a trial, and hand it to
    the research-idea power gate.
    """
    sr = sr_true_annual / sqrt(periods)
    var = 1 / T if sr_var is None else sr_var
    m = {"gumbel": expected_max_z, "upper": upper_bound_max_z}[bound](n_trials)
    sr0 = sqrt(var) * m
    se = sqrt((1 + 0.5 * sr ** 2) / (T - 1))
    return 1 - _N.cdf((sr0 + _N.inv_cdf(conf) * se - sr) / se)


def bh_fdr(pvals, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg (1995) step-up. Returns a boolean mask of discoveries.

    Use it across a DECLARED slate (XASSET, an SS census) in place of a family-
    wise bar. Harvey & Liu (2020) found BH came close to its target false-
    discovery rate on their strategy set, while stricter procedures missed
    true effects.
    """
    p = np.asarray(pvals, dtype=float)
    if p.ndim != 1 or p.size == 0 or np.isnan(p).any() or ((p < 0) | (p > 1)).any():
        raise ValueError("pvals must be a non-empty 1-D array of numbers in [0, 1]")
    m = p.size
    order = np.argsort(p)
    passed = p[order] <= q * np.arange(1, m + 1) / m
    out = np.zeros(m, dtype=bool)
    if passed.any():
        k = np.nonzero(passed)[0].max()
        out[order[: k + 1]] = True
    return out


# -- reading a result: what a null means -------------------------------------

def newey_west_t(x, lags: int | None = None) -> float:
    """HAC (Bartlett) t of a series' mean. lags=None uses ⌊4(T/100)^(2/9)⌋ (Newey-West 1994).

    The same estimator as `scripts/gamma/vrp_summary.py::newey_west_t`, pinned
    by a parity test, and checked against statsmodels as a second method.
    NaNs raise. Drop them yourself and say how many you dropped.
    """
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or x.size < 3:
        raise ValueError("newey_west_t needs a 1-D series of length >= 3")
    if np.isnan(x).any():
        raise ValueError("newey_west_t got NaNs; drop them explicitly and report the count")
    n = x.size
    L = int(4 * (n / 100) ** (2 / 9)) if lags is None else lags
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, L + 1):
        s += 2 * (1 - k / (L + 1)) * (u[k:] @ u[:-k]) / n
    if s <= 0:
        raise ValueError("long-run variance is non-positive")
    return x.mean() / sqrt(s / n)


def read_result(estimate: float, se: float, meaningful: float,
                alpha: float = 0.05) -> dict:
    """Read a result into PRESENT, ABSENT or INCONCLUSIVE. Never into "no edge" alone.

    `estimate` is signed so that positive is the hypothesised direction.
    `meaningful` (> 0) is the smallest effect that would matter: the cost hurdle,
    or the size the sleeve needs. With the (1−alpha) interval [lo, hi]:
    - PRESENT: lo > 0. The effect is there, whatever later gates decide about its
      expression.
    - ABSENT: hi < meaningful. Every effect worth trading is ruled out. This is
      the only reading that justifies "never re-test without new data".
    - INCONCLUSIVE: anything else. The test could not tell. Record it as
      underpowered, with what would make it decidable, not as a kill.
    The audit behind this module found 20 of 82 kills were INCONCLUSIVE by this
    rule but were recorded as dead.
    """
    if se <= 0 or meaningful <= 0:
        raise ValueError(f"need se > 0 and meaningful > 0, got se={se}, meaningful={meaningful}")
    c = z_crit(alpha)
    lo, hi = estimate - c * se, estimate + c * se
    outcome = "PRESENT" if lo > 0 else "ABSENT" if hi < meaningful else "INCONCLUSIVE"
    return {"outcome": outcome, "lo": lo, "hi": hi, "t": estimate / se,
            "power_at_meaningful": power_of_z(meaningful / se, alpha),
            "below_meaningful": estimate < meaningful}


# -- the book: judge a sleeve by what it adds --------------------------------

def marginal_gain(sr_new: float, sr_book: float, rho: float) -> float:
    """Positive iff a small allocation to the new sleeve raises the book's Sharpe.

    Algebra, not a market claim. For a book p and a sleeve k at weight w,
    d SR(p + w·k)/dw at w = 0 equals (σ_k/σ_p)·(SR_k − ρ·SR_p). A sleeve
    uncorrelated with the book helps at ANY positive Sharpe. This is the D5
    "inventory" principle in `docs/RESEARCH_STATE.md`, and the ρ·IR_c bar in
    `results/cef/PORTFOLIO_FRAMEWORK_2026-10-15.md`.
    """
    if not -1 <= rho <= 1:
        raise ValueError(f"rho must be in [-1, 1], got {rho}")
    return sr_new - rho * sr_book


def combined_sharpe(sr_a: float, sr_b: float, rho: float) -> float:
    """Maximum Sharpe of two streams at the optimal (unconstrained) mix.

    SR² = (a² + b² − 2ρab)/(1 − ρ²). At ρ = 0 this is √(a² + b²), so five
    unrelated 0.5s combine to about 1.1. That holds before costs. Costs do not
    diversify (`pair-reversion` in the graveyard).
    """
    if not -1 < rho < 1:
        raise ValueError(f"rho must be in (-1, 1), got {rho}")
    return sqrt((sr_a ** 2 + sr_b ** 2 - 2 * rho * sr_a * sr_b) / (1 - rho ** 2))


# -- overfitting: how likely the in-sample winner is noise -------------------

def pbo_cscv(pnl, S: int = 16) -> dict:
    """Probability of backtest overfitting by CSCV (Bailey, Borwein, López de Prado & Zhu).

    pnl is a T×N array: one column per trial configuration, the per-period P&L
    of each, on common dates. That is why every trial must store its daily P&L
    series, not just a verdict. The rows are cut into S contiguous blocks. For
    every split of the blocks into halves, take the in-sample best Sharpe and
    record the logit of its relative out-of-sample rank. PBO is the share of
    logits at or below zero, i.e. the winner ranking at or below the OOS median.
    C(16, 8) = 12,870 splits (the paper misprints 12,780). A high PBO says the
    selection was unreliable. It does not say the family has no skill: N
    similar good strategies also score high (the paper's own caveat).
    """
    X = np.asarray(pnl, dtype=float)
    if X.ndim != 2:
        raise ValueError("pnl must be a T×N array")
    T, N = X.shape
    if S < 2 or S % 2:
        raise ValueError(f"S must be an even integer >= 2, got {S}")
    if N < 2 or T < 2 * S:
        raise ValueError(f"need N >= 2 trials and T >= 2S rows, got T={T}, N={N}, S={S}")
    if np.isnan(X).any():
        raise ValueError("pnl has NaNs; align the trials on common dates first")
    blocks = np.array_split(np.arange(T), S)
    cnt = np.array([len(b) for b in blocks], dtype=float)
    s1 = np.stack([X[b].sum(axis=0) for b in blocks])          # S×N
    s2 = np.stack([(X[b] ** 2).sum(axis=0) for b in blocks])

    def sharpe(idx):
        n = cnt[idx].sum(axis=1)[:, None]
        mu = s1[idx].sum(axis=1) / n
        var = s2[idx].sum(axis=1) / n - mu ** 2
        if (var <= 0).any():
            raise ValueError("a trial has zero variance on a half; it cannot be ranked")
        return mu / np.sqrt(var)

    combos = np.array(list(combinations(range(S), S // 2)))
    rest = np.array([sorted(set(range(S)) - set(c)) for c in combos])
    is_sr, oos_sr = sharpe(combos), sharpe(rest)
    best = is_sr.argmax(axis=1)
    rows = np.arange(len(combos))
    b = oos_sr[rows, best][:, None]
    rank = (oos_sr < b).sum(axis=1) + 0.5 * ((oos_sr == b).sum(axis=1) - 1) + 1
    w = rank / (N + 1)
    logits = np.log(w / (1 - w))
    return {"pbo": float((logits <= 0).mean()), "n_splits": len(combos),
            "logits": logits, "n_trials": N, "T": T, "S": S}


def main(argv=None) -> int:
    """`python3 -m scripts.research.inference bars 52 --years 13 --sr 0.67`

    Prints the desk's bar beside the paper's for a counter's N, and the chance a
    true Sharpe clears each. It is a calculator for the power gate and reads
    no data.
    """
    ap = argparse.ArgumentParser(description=main.__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bars", help="desk vs Gumbel best-of-N bar, and P(pass)")
    b.add_argument("n", type=float)
    b.add_argument("--years", type=float)
    b.add_argument("--sr", type=float, help="hypothesised true annualised Sharpe")
    p = sub.add_parser("power", help="power to detect a true annualised Sharpe")
    p.add_argument("--sr", type=float, required=True)
    p.add_argument("--years", type=float, required=True)
    p.add_argument("--alpha", type=float, default=0.05)
    a = ap.parse_args(argv)
    if a.cmd == "bars":
        print(f"N={a.n:g}: desk bar sqrt(2 ln N) = {upper_bound_max_z(a.n):.3f}; "
              f"Gumbel E[max] = {expected_max_z(a.n):.3f}")
        if a.years and a.sr is not None:
            T = int(round(a.years * 252))
            for bound in ("upper", "gumbel"):
                print(f"  P(DSR > 0.95 | true SR {a.sr}, {a.years:g}y, {bound}) = "
                      f"{p_pass_dsr(a.sr, T, a.n, bound=bound):.3f}")
    else:
        print(f"power = {sharpe_power(a.sr, a.years, a.alpha):.3f}; "
              f"years for 80% = {years_needed(a.sr, 0.8, a.alpha):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
