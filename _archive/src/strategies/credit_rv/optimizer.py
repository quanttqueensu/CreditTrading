"""Cost-aware mean-variance portfolio for the credit RV book.

The heuristic book (thresholds, no-trade bands, risk-parity units) trades without
knowing what trading costs.  That is why every configuration burned 2-11%/yr in
execution: the rules decide *whether* to trade on statistical grounds and only then
pay whatever the market charges.

The correct problem is to decide both at once.  On each date solve

    max_w   mu'w  -  (lambda/2) w'Sigma w  -  sum_i c_i |w_i - w_i_prev|
    s.t.    B'w = 0            (factor neutral)
            ||w||_1 <= L       (gross cap)

where

    mu_i    = -s_i * sigma_eq_i * (1 - exp(-kappa_i * h / 252))
              the OU-implied expected reversion over the holding horizon; this is
              an EXPECTED RETURN in return units, not a z-score, so it is directly
              comparable to the cost term.
    c_i     = round-trip half-spread + expected impact for that name.
    lambda  = risk aversion, set so the unconstrained solution hits the vol target.

The L1 term is what makes this work.  Its subgradient creates a **no-trade region**
around the current holding whose width is exactly the cost of trading: the book
moves a position only when the expected improvement exceeds the spread it must pay
to get there.  That is the same economics the no-trade band was groping at, except
derived rather than guessed, and per-name rather than global -- a cheap leg is
rebalanced often, an expensive one is left alone.

Solved by proximal gradient (ISTA) with the factor-neutrality projection applied
inside each iteration, warm-started from the previous day's weights.  With ~28
assets this converges in a few dozen cheap iterations.
"""
from __future__ import annotations

import numpy as np


def _project_null(w: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Project onto {w : B'w = 0} and remove the dollar imbalance."""
    ok = np.isfinite(B).all(axis=1)
    if ok.sum() < B.shape[1] + 2:
        return np.zeros_like(w)
    out = np.zeros_like(w)
    Bk = B[ok]
    wk = w[ok]
    G = Bk.T @ Bk + 1e-10 * np.eye(Bk.shape[1])
    wk = wk - Bk @ np.linalg.solve(G, Bk.T @ wk)
    wk = wk - wk.mean()
    out[ok] = wk
    return out


def solve(mu: np.ndarray, Sigma: np.ndarray, cost: np.ndarray, w_prev: np.ndarray,
          B: np.ndarray, lam: float, max_gross: float,
          n_iter: int = 80, tol: float = 1e-9, n_sig: int | None = None) -> np.ndarray:
    """Proximal-gradient solution of the cost-aware problem.

    NOTE ON NEUTRALITY.  Projecting the whole weight vector onto the factor-null
    space destroys the L1 sparsity the proximal step just created - the projection
    gives every name a small non-zero weight, so every name trades and the
    no-trade region is lost.  Neutrality is therefore imposed OUTSIDE this solve,
    by dedicated liquid hedge legs (see book_opt), and this routine optimises the
    SIGNAL legs only.  `n_sig` marks how many leading entries are signal legs.
    """
    n = len(mu)
    mu = np.nan_to_num(mu, nan=0.0)
    cost = np.nan_to_num(cost, nan=1e-3, posinf=1e-3)
    w = w_prev.copy()

    # step size from the curvature of the smooth part
    L = lam * float(np.linalg.eigvalsh(Sigma).max()) + 1e-12
    eta = 1.0 / max(L, 1e-8)

    for _ in range(n_iter):
        grad = -mu + lam * (Sigma @ w)
        z = w - eta * grad
        # proximal operator of the L1 term, centred on the CURRENT holding:
        # this is the no-trade region -- move toward z only by the amount that
        # beats the per-name cost of moving.
        d = z - w_prev
        thr = eta * cost
        d = np.sign(d) * np.clip(np.abs(d) - thr, 0.0, None)
        w_new = w_prev + d
        if n_sig is not None:
            w_new[n_sig:] = 0.0        # hedge legs are solved for separately

        g = np.abs(w_new).sum()
        if g > max_gross:
            w_new *= max_gross / g
        if np.max(np.abs(w_new - w)) < tol:
            w = w_new
            break
        w = w_new
    return w


def calibrate_lambda(mu: np.ndarray, Sigma: np.ndarray, B: np.ndarray,
                     vol_target: float, lam_lo: float = 1e-2, lam_hi: float = 1e6,
                     iters: int = 40) -> float:
    """Risk aversion such that the frictionless optimum sits at the vol target."""
    def vol_at(lam):
        w = _project_null(np.linalg.solve(Sigma + 1e-12 * np.eye(len(mu)), mu) / lam, B)
        return float(np.sqrt(max(w @ Sigma @ w, 1e-18)) * np.sqrt(252))

    lo, hi = lam_lo, lam_hi
    if vol_at(hi) > vol_target:
        return hi
    if vol_at(lo) < vol_target:
        return lo
    for _ in range(iters):
        mid = np.sqrt(lo * hi)
        if vol_at(mid) > vol_target:
            lo = mid
        else:
            hi = mid
    return np.sqrt(lo * hi)
