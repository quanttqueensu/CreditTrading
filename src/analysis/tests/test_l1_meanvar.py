"""The five correctness tests for the L1 mean-variance solver.

These are the tests that decide whether the joint optimiser is worth measuring at
all. If the c = 0 limit does not reproduce a direct linear solve, or the Sigma = I
limit does not reproduce the scalar band, then whatever the backtest says is an
artefact of a broken solver rather than a statement about the strategy.

Run:  python3 -m pytest src/analysis/tests/test_l1_meanvar.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.analysis.l1_meanvar import (SolverError, frictionless, no_trade_slack,  # noqa: E402
                                     solve)


def random_case(rng, n=17, dense=True, scale_alpha=8e-3):
    """A draw with the shape of the real problem: daily vols ~0.8%, alpha ~ sigma*z."""
    sig = rng.uniform(0.004, 0.012, n)
    if dense:
        F = rng.normal(size=(n, 3))                 # 3 common factors, then noise
        C = F @ F.T / 3.0 + np.diag(rng.uniform(0.3, 1.0, n))
        D = np.diag(1.0 / np.sqrt(np.diag(C)))
        C = D @ C @ D
    else:
        C = np.eye(n)
    Sigma = np.outer(sig, sig) * C
    alpha = scale_alpha * rng.normal(size=n) * sig / sig.mean()
    w_prev = rng.normal(size=n)
    w_prev -= w_prev.mean()
    w_prev /= np.abs(w_prev).sum()
    lam = float(np.abs(frictionless(alpha, Sigma, 1.0)).sum())   # ~unit gross book
    return alpha, Sigma, w_prev, lam


# ------------------------------------------------------------------ 1. c = 0 limit

def test_zero_cost_reproduces_direct_linear_solve():
    """With no cost the answer must be dollar-neutral Sigma^-1 alpha, to tight tol."""
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(40):
        alpha, Sigma, w_prev, lam = random_case(rng)
        s = solve(alpha, Sigma, w_prev, lam, c=0.0)

        # direct linear solve of the equality-constrained QP, no iteration involved
        n = len(alpha)
        M = np.zeros((n + 1, n + 1))
        M[:n, :n] = lam * Sigma
        M[:n, n] = 1.0
        M[n, :n] = 1.0
        direct = np.linalg.solve(M, np.concatenate([alpha, [0.0]]))[:n]

        err = np.abs(s.w - direct).max() / max(np.abs(direct).max(), 1e-30)
        worst = max(worst, err)
        assert err < 1e-10, f"c=0 relative error {err:.3e}"
        assert abs(s.w.sum()) < 1e-12
        # and it must agree with the closed form in the module
        assert np.abs(s.w - frictionless(alpha, Sigma, lam)).max() < 1e-12
    print(f"\n[1] c=0 vs direct linear solve: worst relative error {worst:.2e}")


# --------------------------------------------------- 2. Sigma = I -> the scalar band

def test_identity_covariance_reduces_to_scalar_band_at_the_edge():
    """With Sigma = I the no-trade region must collapse to a per-name scalar band,
    and a name that trades must stop at the BAND EDGE, not at its target."""
    rng = np.random.default_rng(1)
    n = 17
    moved_total = held_total = 0
    worst = 0.0
    # sweep the implied band width so both the trade and the hold branch are hit
    for k in range(40):
        alpha = 8e-3 * rng.normal(size=n)
        Sigma = np.eye(n)
        w_prev = rng.normal(size=n)
        w_prev -= w_prev.mean()
        w_prev /= np.abs(w_prev).sum()
        lam = 50.0
        band_want = (0.001, 0.005, 0.02, 0.06)[k % 4]
        c = lam * band_want
        s = solve(alpha, Sigma, w_prev, lam, c=c)

        # hand-computed: with Sigma = I the problem separates given nu, and
        #   w_i = w_prev_i + S_{c/lam}( (alpha_i - nu)/lam - w_prev_i )
        # i.e. soft-threshold of the gap to the frictionless target, band = c/lam.
        band = c / lam
        tgt_of = lambda nu: (alpha - nu) / lam
        lo, hi = -1.0, 1.0
        for _ in range(300):                      # nu from the neutrality constraint
            mid = 0.5 * (lo + hi)
            gap = tgt_of(mid) - w_prev
            hand = w_prev + np.sign(gap) * np.maximum(np.abs(gap) - band, 0.0)
            if hand.sum() > 0:
                lo = mid
            else:
                hi = mid
        nu = 0.5 * (lo + hi)
        gap = tgt_of(nu) - w_prev
        hand = w_prev + np.sign(gap) * np.maximum(np.abs(gap) - band, 0.0)

        err = np.abs(s.w - hand).max() / max(np.abs(hand).max(), 1e-30)
        worst = max(worst, err)
        assert err < 1e-8, f"Sigma=I vs hand soft-threshold: {err:.3e}"

        mv = np.abs(gap) > band
        assert np.array_equal(s.traded, mv), "traded set differs from the scalar band"
        # stopped at the edge: distance left to target is exactly the band width
        left = np.abs(tgt_of(nu) - s.w)[mv]
        assert np.allclose(left, band, atol=1e-9), "did not stop at the band edge"
        moved_total += int(mv.sum())
        held_total += int((~mv).sum())
    assert moved_total > 0 and held_total > 0, "the sweep did not exercise both branches"
    print(f"\n[2] Sigma=I: worst error {worst:.2e}; "
          f"{moved_total} names traded to the edge, {held_total} held inside the band")


# ------------------------------------------------------------- 3. no-trade condition

def test_no_trade_region():
    """The exact per-name condition holds at w*; the brief's version, evaluated at
    w_prev, is only exact for diagonal Sigma -- measure the disagreement."""
    rng = np.random.default_rng(2)
    agree = total = 0
    whole_book_checked = 0
    for _ in range(200):
        alpha, Sigma, w_prev, lam = random_case(rng)
        c = float(10 ** rng.uniform(-4.0, -2.3))
        s = solve(alpha, Sigma, w_prev, lam, c=c)

        # (a) EXACT condition, evaluated at the solution
        # Traded names sit exactly ON |u| = c, so |u| <= c does not separate the two
        # sets at the boundary; the partition is by the SIGN condition below.
        u = alpha - lam * (Sigma @ s.w) - s.nu
        for i in range(len(alpha)):
            if s.d[i] == 0.0:
                assert abs(u[i]) <= c * (1 + 1e-7) + 1e-12, f"held name {i}: |u|={abs(u[i]):.3e} > c={c:.3e}"
            else:
                assert abs(abs(u[i]) - c) <= 1e-7 * max(c, 1.0), \
                    f"traded name {i}: |u|={abs(u[i]):.3e} != c={c:.3e}"
                assert np.sign(u[i]) == np.sign(s.d[i]), "trade against the gradient"

        # (b) WHOLE-BOOK condition evaluated at w_prev -- exact, closed form
        slack = no_trade_slack(alpha, Sigma, w_prev, lam)
        if slack <= c * (1 - 1e-9):
            assert not s.traded.any(), "slack < c but the book traded"
            whole_book_checked += 1
        elif slack >= c * (1 + 1e-6):
            assert s.traded.any(), "slack > c but the book did not trade"

        # (c) the brief's per-name version, evaluated at w_prev, for the record
        g = alpha - lam * (Sigma @ w_prev)
        approx_hold = np.abs(g - s.nu) <= c
        agree += int((approx_hold == ~s.traded).sum())
        total += len(alpha)
    # Deliberately construct books INSIDE the region -- random draws rarely land
    # there. Perturb OFF the frictionless optimum (at the optimum the slack is
    # identically zero, so the test would be vacuous) and walk c across the boundary.
    inside = 0
    for _ in range(60):
        alpha, Sigma, w_prev, lam = random_case(rng)
        w_star = frictionless(alpha, Sigma, lam)
        e = rng.normal(size=len(alpha))
        e -= e.mean()
        e /= np.abs(e).sum()
        for eps in (1e-3, 1e-2, 5e-2):
            w0 = w_star + eps * e
            slack = no_trade_slack(alpha, Sigma, w0, lam)
            if slack <= 1e-6 * np.abs(alpha).max():
                continue
            # c just above the slack: the whole book must sit still, at zero cost
            s_in = solve(alpha, Sigma, w0, lam, c=slack * (1 + 1e-6))
            assert not s_in.traded.any(), f"slack {slack:.3e} < c but the book traded"
            assert s_in.iters == 0, "a no-trade book should cost zero iterations"
            # c well below it: the book must move
            s_out = solve(alpha, Sigma, w0, lam, c=slack * 0.5)
            assert s_out.traded.any(), f"slack {slack:.3e} > c but the book sat still"
            inside += 1
    whole_book_checked += inside

    frac = agree / total
    print(f"\n[3] exact KKT partition holds on every draw "
          f"({whole_book_checked} whole-book no-trade cases). "
          f"Gradient-at-w_prev version agrees with it on {frac:.1%} of names.")
    assert frac > 0.5


def test_no_trade_condition_is_exact_for_diagonal_sigma():
    """The at-w_prev per-name condition IS exact when Sigma is diagonal."""
    rng = np.random.default_rng(3)
    for _ in range(60):
        n = 12
        sig = rng.uniform(0.004, 0.012, n)
        Sigma = np.diag(sig ** 2)
        alpha = 8e-3 * rng.normal(size=n)
        w_prev = rng.normal(size=n)
        w_prev -= w_prev.mean()
        w_prev /= np.abs(w_prev).sum()
        lam = float(np.abs(frictionless(alpha, Sigma, 1.0)).sum())
        c = float(10 ** rng.uniform(-4.0, -2.5))
        s = solve(alpha, Sigma, w_prev, lam, c=c)
        g = alpha - lam * (Sigma @ w_prev)
        assert np.array_equal(np.abs(g - s.nu) <= c + 1e-12, ~s.traded)
    print("[3b] diagonal Sigma: at-w_prev per-name condition exact on every draw")


# ------------------------------------------------------------------ 4. monotonicity

def test_turnover_non_increasing_in_cost():
    """More cost must never buy more trading, on a single solve and along a path."""
    rng = np.random.default_rng(4)
    grid = [0.0, 2e-4, 5e-4, 1e-3, 1.5e-3, 3e-3, 6e-3, 1.2e-2]
    for _ in range(30):
        alpha, Sigma, w_prev, lam = random_case(rng)
        t = [np.abs(solve(alpha, Sigma, w_prev, lam, c=c).d).sum() for c in grid]
        for a, b in zip(t, t[1:]):
            assert b <= a + 1e-12, f"turnover rose with cost: {a:.6e} -> {b:.6e}"

    # and along a multi-period path, where w_prev itself becomes cost-dependent
    n = 10
    sig = rng.uniform(0.004, 0.012, n)
    F = rng.normal(size=(n, 2))
    C = F @ F.T / 2.0 + np.diag(rng.uniform(0.4, 1.0, n))
    D = np.diag(1.0 / np.sqrt(np.diag(C)))
    Sigma = np.outer(sig, sig) * (D @ C @ D)
    alphas = [6e-3 * rng.normal(size=n) for _ in range(120)]
    lam = float(np.abs(frictionless(alphas[0], Sigma, 1.0)).sum())
    path = []
    for c in grid:
        w = np.zeros(n)
        turn = 0.0
        for a in alphas:
            s = solve(a, Sigma, w, lam, c=c)
            turn += np.abs(s.d).sum()
            w = s.w
        path.append(turn)
    for a, b in zip(path, path[1:]):
        assert b <= a + 1e-9, f"path turnover rose with cost: {a:.6e} -> {b:.6e}"
    print(f"\n[4] turnover monotone in c on 30 single solves and a 120-step path "
          f"({path[0]:.3f} -> {path[-1]:.3f})")


# ---------------------------------------------------------------------- 5. optimality

def test_kkt_certificate_and_objective_dominance():
    """Check the subgradient condition at the answer, and that no perturbation of it
    improves the objective. The loop counter is never trusted."""
    rng = np.random.default_rng(5)
    worst = 0.0
    for _ in range(60):
        alpha, Sigma, w_prev, lam = random_case(rng)
        c = float(10 ** rng.uniform(-4.0, -2.3))
        s = solve(alpha, Sigma, w_prev, lam, c=c)
        assert s.kkt <= s.tol_abs, f"returned an uncertified point: {s.kkt:.3e}"
        worst = max(worst, s.kkt / max(s.tol_abs, 1e-300))
        assert abs(s.w.sum()) < 1e-11, f"not dollar-neutral: {s.w.sum():.3e}"

        obj = lambda w: (w @ alpha - 0.5 * lam * w @ Sigma @ w
                         - c * np.abs(w - w_prev).sum())
        f0 = obj(s.w)
        n = len(alpha)
        for _ in range(60):                 # random feasible perturbations
            e = rng.normal(size=n)
            e -= e.mean()
            e /= np.abs(e).sum()
            for step in (1e-2, 1e-3, 1e-4, 1e-5):
                assert obj(s.w + step * e) <= f0 + 1e-14 * max(abs(f0), 1.0), \
                    "a feasible perturbation improved the objective"
        # and against the frictionless optimum, which must not beat it either
        assert obj(frictionless(alpha, Sigma, lam)) <= f0 + 1e-14 * max(abs(f0), 1.0)
    print(f"\n[5] KKT certified on every draw; worst residual "
          f"{worst:.2e}x the tolerance; no feasible perturbation improved the objective")


# ------------------------------------------------------------------------- guardrails

def test_non_neutral_incoming_book_is_solved_to_a_neutral_one():
    """A book restricted to a sub-universe is generally not neutral. The constraint is
    on w, not on w_prev, so the solver must still return 1'w = 0."""
    rng = np.random.default_rng(7)
    for _ in range(40):
        alpha, Sigma, w_prev, lam = random_case(rng)
        w_prev = w_prev + rng.normal() * 0.05          # deliberately off-neutral
        c = float(10 ** rng.uniform(-4.0, -2.3))
        s = solve(alpha, Sigma, w_prev, lam, c=c)
        assert abs(s.w.sum()) < 1e-10, f"not neutral: {s.w.sum():.3e}"
        assert s.kkt <= s.tol_abs
        u = alpha - lam * (Sigma @ s.w) - s.nu
        for i in range(len(alpha)):
            if s.d[i] == 0.0:
                assert abs(u[i]) <= c * (1 + 1e-7) + 1e-12
            else:
                assert abs(abs(u[i]) - c) <= 1e-7 * max(c, 1.0)
    # and at c = 0 it must still be the direct linear solve
    alpha, Sigma, w_prev, lam = random_case(rng)
    s = solve(alpha, Sigma, w_prev + 0.3, lam, c=0.0)
    assert np.abs(s.w - frictionless(alpha, Sigma, lam)).max() < 1e-10
    print("\n[6] non-neutral incoming books are solved back to 1'w = 0 with KKT intact")


def test_raises_rather_than_degrading():
    rng = np.random.default_rng(6)
    alpha, Sigma, w_prev, lam = random_case(rng)
    with pytest.raises(SolverError):
        solve(alpha, Sigma, w_prev, lam, c=1e-3, tol=1e-16, max_iter=2, block=1)
    with pytest.raises(ValueError):
        solve(alpha, np.zeros_like(Sigma), w_prev, lam, c=1e-3)      # not PD
    with pytest.raises(ValueError):
        bad = alpha.copy(); bad[0] = np.nan
        solve(bad, Sigma, w_prev, lam, c=1e-3)
    with pytest.raises(ValueError):
        solve(alpha, Sigma, w_prev[:-1], lam, c=1e-3)                # wrong length
    with pytest.raises(ValueError):
        solve(alpha, Sigma, w_prev, -1.0, c=1e-3)
    print("[G] solver raises on non-convergence, non-PD Sigma, NaN alpha, "
          "mis-shaped w_prev, non-positive lambda")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-s"]))
