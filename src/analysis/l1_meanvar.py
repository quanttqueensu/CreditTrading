"""Mean-variance with an L1 trading penalty -- the band and the covariance from ONE objective.

WHY THIS EXISTS
---------------
Two construction changes were each measured on the CEF sleeve and each failed:

    w ~ Sigma^-1 alpha   gross SR 1.20 -> 1.54, BR_eff 2.24 -> 3.95, turnover +43%.
                         At 15bp the extra turnover eats the entire gain (0.33 -> 0.28).
    no-trade band        turnover 31 -> 14/yr, net SR 0.33 -> 0.70.

Composing them SEQUENTIALLY -- build Sigma^-1 alpha targets, then run a scalar band
over them -- was also measured and also failed: turnover-matched at ~13/yr, plain+band
nets 0.70 and Sigma^-1+band nets 0.62. The sequential structure throws away the thing
that made Sigma^-1 worth having. The band asks "has this name's WEIGHT moved far
enough to be worth a trade", which is a question about one coordinate at a time; the
whole point of Sigma^-1 is that the coordinates are not separable.

The claim this module implements is that the two are not features to be composed.
They fall out of one objective:

    maximise_w   w'alpha - (lambda/2) w'Sigma w - c||w - w_prev||_1
    subject to   1'w = 0

The quadratic part is the Markowitz book. The L1 part is the cost of getting there.
Their subgradient conditions interlock, and what drops out is a no-trade region --
the solver leaves a name alone unless its RISK-ADJUSTED marginal alpha clears the
cost of trading it. Nothing is thresholded by hand.

WHAT THE NO-TRADE REGION ACTUALLY IS (and how the brief's version is approximate)
--------------------------------------------------------------------------------
Re-centre on the incoming book, d = w - w_prev, and let

    g = alpha - lambda Sigma w_prev = grad of the smooth part, evaluated at w_prev

The problem becomes  min_d (lambda/2) d'Sigma d - g'd + c||d||_1  s.t. 1'd = 0, and
the exact optimality condition at the solution is, with u = alpha - lambda Sigma w* - nu 1,

    d_i > 0  =>  u_i = +c        d_i < 0  =>  u_i = -c        d_i = 0  =>  |u_i| <= c

Two things follow, and the difference between them matters.

  1. WHOLE-BOOK no-trade. w* = w_prev exactly iff there is a nu with |g_i - nu| <= c
     for every i, i.e. iff (max_i g_i - min_i g_i) / 2 <= c. That is exact, it is
     testable at w_prev with no solve, and it is Sigma-aware through g. See
     `no_trade_slack`.

  2. PER-NAME no-trade. The natural reading -- "name i is left alone iff its own
     gradient at w_prev is inside c" -- is EXACT ONLY WHEN Sigma IS DIAGONAL. With a
     dense Sigma the names are coupled: a name whose own marginal alpha is well inside
     the cost can still be dragged into trading because its neighbours moved, and vice
     versa. The condition that is exactly true for a general Sigma is the one above,
     evaluated at w*, not at w_prev. Test 3 in the accompanying test module measures
     the disagreement rather than assuming it away.

  Note also that with an L1 penalty the no-trade region is a POLYTOPE, not an
  ellipsoid: it is the box c*B_inf pulled back through lambda*Sigma and widened along
  the neutrality direction 1. Sigma tilts and shears the box; it does not round it.
  An ellipsoid is what an L2 trading penalty would give.

SOLVER
------
FISTA on d, warm-started at d = 0 (which IS w_prev), then an active-set polish.

The one thing that must not be done here is the obvious thing. Applying the
soft-threshold and THEN projecting onto 1'w = 0 destroys the no-trade region: the
projection puts a small non-zero number into every coordinate, so every name trades
and the sparsity the prox just created is gone. This repo already has that scar --
`src/strategies/credit_rv/optimizer.py` had to abandon the equality constraint
entirely and hedge neutrality with separate legs because of it. The fix is to take
the prox of the L1 term and the neutrality indicator TOGETHER:

    prox(v) = S_kappa(v - nu 1),  nu chosen so that 1'S_kappa(v - nu 1) = 0

which is a soft-threshold about a shifted centre. The shift is found exactly (the
map is piecewise linear in nu with known breakpoints), so the returned d satisfies
1'd = 0 to machine precision AND keeps exact zeros. `_prox_neutral_l1` does this.

The active-set polish then solves the reduced KKT system directly on the names that
moved, which takes the answer to machine precision -- necessary because the c = 0
limit has to reproduce a direct linear solve to tight tolerance.

NO SILENT FALLBACKS. Every returned solution carries a KKT certificate computed at
the solution itself, not an iteration count. If the certificate is not met the solver
RAISES. It never returns the last iterate and hopes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["Solution", "solve", "frictionless", "lambda_for_vol",
           "no_trade_slack", "SolverError"]


class SolverError(RuntimeError):
    """Raised when the solver cannot certify optimality. Never swallowed."""


@dataclass(frozen=True)
class Solution:
    w: np.ndarray            # optimal weights
    d: np.ndarray            # w - w_prev; exact zeros are the no-trade set
    nu: float                # multiplier on 1'w = 0
    kkt: float               # max KKT residual at w, in alpha (return) units
    tol_abs: float           # the absolute tolerance it was required to beat
    iters: int               # FISTA iterations actually run
    polished: bool           # whether the active-set polish supplied the answer

    @property
    def traded(self) -> np.ndarray:
        """Boolean mask of names the optimiser chose to move."""
        return self.d != 0.0


# ----------------------------------------------------------------------------- prox

def _prox_neutral_l1(v: np.ndarray, kappa: float, target: float = 0.0) -> np.ndarray:
    """argmin_d  0.5||d - v||^2 + kappa||d||_1   s.t.  1'd = target.

    Soft-threshold about a shifted centre: d = S_kappa(v - nu 1) with nu solving
    1'S_kappa(v - nu 1) = 0. That sum is continuous, non-increasing and piecewise
    linear in nu with breakpoints at v_i +/- kappa, so nu is found exactly by
    locating the bracketing segment and interpolating along it.

    Doing the threshold and the projection jointly (rather than one then the other)
    is what preserves the exact zeros -- see the module docstring.
    """
    if kappa <= 0.0:
        return v - (v.sum() - target) / len(v)

    pad = 1.0 + abs(target)
    lo = float(v.min() - kappa) - pad
    hi = float(v.max() + kappa) + pad
    pts = np.unique(np.concatenate([[lo], v - kappa, v + kappa, [hi]]))
    X = v[None, :] - pts[:, None]                    # all breakpoints at once
    vals = (np.sign(X) * np.maximum(np.abs(X) - kappa, 0.0)).sum(axis=1) - target
    # vals is non-increasing, vals[0] > 0 > vals[-1] by construction of lo/hi
    j = int(np.searchsorted(-vals, 0.0, side="left"))
    if j <= 0:
        nu = float(pts[0])
    elif j >= len(pts):
        nu = float(pts[-1])
    else:
        a, b, fa, fb = pts[j - 1], pts[j], vals[j - 1], vals[j]
        nu = float(a) if fa == fb else float(a + (b - a) * fa / (fa - fb))
    x = v - nu
    return np.sign(x) * np.maximum(np.abs(x) - kappa, 0.0)


# ----------------------------------------------------------------- KKT certificate

def _certificate(d: np.ndarray, g: np.ndarray, Sigma: np.ndarray,
                 lam: float, c: float) -> tuple[float, float]:
    """Smallest achievable max-KKT-residual at d, and the nu that achieves it.

    With q = g - lambda Sigma d and u = q - nu, optimality demands u_i = c sign(d_i)
    on the traded names and |u_i| <= c elsewhere. Each name's residual is a convex
    piecewise-linear function of nu, so the max over names is convex piecewise linear
    and its minimum sits on a breakpoint. Evaluating the <=3n breakpoints is exact.

    This certifies the ANSWER, not the loop. It is the only thing `solve` trusts.
    """
    q = g - lam * (Sigma @ d)
    nz = d != 0.0
    s = np.sign(d)

    cand = np.concatenate([q - c * s, q - c, q + c])
    U = q[None, :] - cand[:, None]                   # residual at every candidate nu
    R = np.where(nz[None, :],
                 np.abs(U - c * s[None, :]),
                 np.maximum(np.abs(U) - c, 0.0))
    vals = R.max(axis=1)
    k = int(np.argmin(vals))
    return float(vals[k]), float(cand[k])


def _active_set(g: np.ndarray, Sigma: np.ndarray, lam: float, c: float,
                A: np.ndarray, s: np.ndarray, target: float = 0.0) -> tuple[np.ndarray, float]:
    """Exact solve of the reduced KKT system on a fixed traded set A with signs s."""
    k = len(A)
    n = len(g)
    d = np.zeros(n)
    if k < 1 or (k < 2 and target == 0.0):   # too little support to meet 1'd = target
        return d, 0.0
    M = np.zeros((k + 1, k + 1))
    M[:k, :k] = lam * Sigma[np.ix_(A, A)]
    M[:k, k] = 1.0
    M[k, :k] = 1.0
    rhs = np.concatenate([g[A] - c * s, [target]])
    sol = np.linalg.solve(M, rhs)
    d[A] = sol[:k]
    return d, float(sol[k])


def _polish(d0: np.ndarray, g: np.ndarray, Sigma: np.ndarray, lam: float,
            c: float, target: float = 0.0, max_sweeps: int = 80) -> np.ndarray:
    """Active-set refinement seeded from a FISTA iterate.

    Drops names whose exact solution contradicts the assumed trade direction, adds
    names whose dual feasibility |u_i| <= c is violated, and re-solves. Bounded; the
    caller certifies the result regardless of whether this converged.
    """
    n = len(g)
    A = list(np.flatnonzero(d0 != 0.0))
    s = list(np.sign(d0[A])) if A else []
    best = np.zeros(n)
    for _ in range(max_sweeps):
        if len(A) < 2:
            return _active_set(g, Sigma, lam, c, np.asarray(A, dtype=int),
                               np.asarray(s, dtype=float), target)[0]
        Aa = np.asarray(A, dtype=int)
        ss = np.asarray(s, dtype=float)
        d, nu = _active_set(g, Sigma, lam, c, Aa, ss, target)
        best = d
        # 1. primal: assumed directions must hold
        wrong = np.flatnonzero(ss * d[Aa] < 0.0)
        if len(wrong):
            drop = int(Aa[wrong[int(np.argmax(np.abs(d[Aa][wrong])))]])
            k = A.index(drop)
            A.pop(k)
            s.pop(k)
            continue
        # 2. dual: untraded names must sit inside the cost
        u = g - lam * (Sigma @ d) - nu
        out = np.setdiff1d(np.arange(n), Aa)
        if len(out):
            viol = np.abs(u[out]) - c
            j = int(np.argmax(viol))
            if viol[j] > 1e-14 * max(1.0, float(np.abs(g).max())):
                A.append(int(out[j]))
                s.append(float(np.sign(u[out[j]])))
                continue
        break
    return best


# ---------------------------------------------------------------------------- solve

def solve(alpha: np.ndarray, Sigma: np.ndarray, w_prev: np.ndarray, lam: float,
          c: float, tol: float = 1e-8, max_iter: int = 20000,
          block: int = 50) -> Solution:
    """maximise w'alpha - (lam/2) w'Sigma w - c||w - w_prev||_1  s.t. 1'w = 0.

    Warm-started at w_prev (d = 0), which is also what makes the no-trade property
    exact: a book inside the region never leaves d = 0 and reports zero iterations.

    RAISES (SolverError) if the KKT certificate at the returned point is not inside
    tol * max(|alpha|_inf, c). It does not return an uncertified iterate.
    """
    alpha = np.asarray(alpha, dtype=float).ravel()
    w_prev = np.asarray(w_prev, dtype=float).ravel()
    Sigma = np.asarray(Sigma, dtype=float)
    n = alpha.size

    if Sigma.shape != (n, n):
        raise ValueError(f"Sigma is {Sigma.shape}, expected ({n}, {n})")
    if w_prev.size != n:
        raise ValueError(f"w_prev has {w_prev.size} entries, expected {n}")
    if not np.isfinite(alpha).all():
        raise ValueError(f"alpha has non-finite entries at {np.flatnonzero(~np.isfinite(alpha))}")
    if not np.isfinite(Sigma).all():
        raise ValueError("Sigma has non-finite entries")
    if not np.isfinite(w_prev).all():
        raise ValueError(f"w_prev has non-finite entries at {np.flatnonzero(~np.isfinite(w_prev))}")
    if not (lam > 0):
        raise ValueError(f"lam must be strictly positive, got {lam}")
    if c < 0:
        raise ValueError(f"c must be non-negative, got {c}")
    ev = np.linalg.eigvalsh(0.5 * (Sigma + Sigma.T))
    if ev.min() <= 0:
        raise ValueError(f"Sigma is not positive definite (min eigenvalue {ev.min():.3e}); "
                         "the objective would not be strictly convex")

    scale = max(float(np.abs(alpha).max()), float(c), 1e-300)
    tol_abs = tol * scale

    if n < 2:                       # 1'w = 0 with one name forces w = 0
        d = -w_prev
        return Solution(w=np.zeros(n), d=d, nu=0.0, kkt=0.0, tol_abs=tol_abs,
                        iters=0, polished=False)

    g = alpha - lam * (Sigma @ w_prev)
    eta = 1.0 / (lam * float(ev.max()))
    # The constraint is 1'w = 0, so in the re-centred variable d = w - w_prev it reads
    # 1'd = -1'w_prev. That is zero whenever the incoming book is already neutral, and
    # non-zero when it is not -- which happens legitimately when names are dropped from
    # the optimisation set, so it is carried rather than assumed away.
    b = -float(w_prev.sum())

    d = np.zeros(n)                 # warm start: d = 0 IS w_prev
    y = d.copy()
    tk = 1.0
    best_d, best_kkt, best_polished, it = d, None, False, 0

    kkt0, _ = _certificate(d, g, Sigma, lam, c)
    if abs(b) <= 1e-14 and kkt0 <= tol_abs:   # inside the no-trade region: no iterations
        best_d, best_kkt = d, kkt0
    else:
        while it < max_iter:
            for _ in range(block):
                grad = lam * (Sigma @ y) - g
                d_new = _prox_neutral_l1(y - eta * grad, eta * c, b)
                if float((y - d_new) @ (d_new - d)) > 0.0:
                    tk = 1.0        # adaptive restart (O'Donoghue & Candes 2015)
                tk1 = 0.5 * (1.0 + np.sqrt(1.0 + 4.0 * tk * tk))
                y = d_new + ((tk - 1.0) / tk1) * (d_new - d)
                d, tk = d_new, tk1
                it += 1

            k_f, _ = _certificate(d, g, Sigma, lam, c)
            d_p = _polish(d, g, Sigma, lam, c, b)
            k_p, _ = _certificate(d_p, g, Sigma, lam, c)
            if k_p <= k_f:
                cand_d, cand_k, cand_pol = d_p, k_p, True
            else:
                cand_d, cand_k, cand_pol = d, k_f, False
            if best_kkt is None or cand_k < best_kkt:
                best_d, best_kkt, best_polished = cand_d, cand_k, cand_pol
            if best_kkt <= tol_abs:
                break

    if best_kkt is None or best_kkt > tol_abs:
        raise SolverError(
            f"no certified optimum: KKT residual {best_kkt:.3e} > tol {tol_abs:.3e} "
            f"after {it} FISTA iterations (n={n}, lam={lam:.4g}, c={c:.4g}, "
            f"cond(Sigma)={ev.max() / ev.min():.3e})")

    w = w_prev + best_d
    feas = abs(float(w.sum()))
    if feas > 1e-9 * max(1.0, float(np.abs(w).sum())):
        raise SolverError(f"returned book is not dollar-neutral: 1'w = {w.sum():.3e}")
    kkt, nu = _certificate(best_d, g, Sigma, lam, c)
    return Solution(w=w, d=best_d, nu=nu, kkt=kkt, tol_abs=tol_abs,
                    iters=it, polished=best_polished)


# ------------------------------------------------------------------------ utilities

def frictionless(alpha: np.ndarray, Sigma: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """The c = 0 solution: w = Sigma^-1 (alpha - nu 1) / lam with 1'w = 0.

    Note this is NOT the same object as demeaning Sigma^-1 alpha. Neutrality is a
    CONSTRAINT, so its multiplier is Sigma-weighted: nu = 1'Sigma^-1 alpha / 1'Sigma^-1 1.
    Demeaning imposes it in weight space and is only equal when Sigma^-1 1 is constant.
    """
    alpha = np.asarray(alpha, dtype=float).ravel()
    one = np.ones_like(alpha)
    Sa = np.linalg.solve(Sigma, alpha)
    S1 = np.linalg.solve(Sigma, one)
    nu = float(Sa.sum() / S1.sum())
    return (Sa - nu * S1) / lam


def lambda_for_vol(alpha: np.ndarray, Sigma: np.ndarray, vol_target: float,
                   periods: int = 252) -> float:
    """Risk aversion putting the frictionless book exactly on an ex-ante vol target."""
    u = frictionless(alpha, Sigma, 1.0)
    var = float(u @ Sigma @ u)
    if var <= 0:
        raise ValueError("frictionless book has non-positive variance; alpha may be zero")
    return float(np.sqrt(periods * var) / vol_target)


def no_trade_slack(alpha: np.ndarray, Sigma: np.ndarray, w_prev: np.ndarray,
                   lam: float) -> float:
    """Half-range of the gradient at w_prev. The book does not trade at all iff <= c.

    Exact, closed form, no solve. This is the Sigma-aware analogue of the scalar band's
    max|w_target - w_prev|, and the quantity whose sub-c-ness defines the no-trade
    region as a set in w_prev space.
    """
    g = np.asarray(alpha, float).ravel() - lam * (np.asarray(Sigma, float)
                                                  @ np.asarray(w_prev, float).ravel())
    return 0.5 * float(g.max() - g.min())
