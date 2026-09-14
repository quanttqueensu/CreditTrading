"""Option pricing, greeks and implied vol — the model this desk owns.

`docs/prompts/gamma/G1_option_math.md` is the specification. Before this file
there was **no option pricing code in this repository at all**: no
Black-Scholes, no Black-76, no implied-vol solver, no greeks. The `iv` column in
`data/vrp/atm_iv_daily.parquet` was produced by a script that is not here, which
is why G1 Part C test 6 exists — we cannot trust a column we cannot reproduce.

WHY THE MODEL CHOICE IS NOT A DETAIL
------------------------------------
The contracts this programme trades are **American options on dividend-paying
ETFs**. HYG, LQD and TLT distribute **monthly** and yield 4-9%; the dividend is
not a rounding error. A European inversion applied to these systematically
misprices in-the-money puts, and in-the-money calls near an ex-date, because
early exercise carries real value when the dividend is large relative to the
option's remaining time value.

That is not a theoretical nicety. Cboe's own stated rationale for launching
options on IBHY/IBIG futures was "dividend incorporation reducing early exercise
risk" relative to the ETF options — an exchange built a product to route around
exactly this problem.

So there are three pricers and **the caller chooses explicitly**:

    "black76"          European on a FORWARD. Correct for options on futures.
                       NOT the default for an ETF option.
    "bs_discrete_div"  European, with the PV of known discrete dividends removed
                       from spot. Cheap, adequate at-the-money and short-dated
                       where early exercise is worth little.
    "american_binomial" Cox-Ross-Rubinstein with the ACTUAL discrete ex-dividend
                       schedule applied as price drops at the ex-dates, early
                       exercise tested at every node. THE REFERENCE.

`american_binomial` is the default for anything touching a listed ETF option.
Passing `black76` for one is possible but must be deliberate.

BJERKSUND-STENSLAND IS DELIBERATELY NOT HERE YET, AND THIS IS THE REASON
-----------------------------------------------------------------------
G1 Part A asks for Bjerksund-Stensland (2002) as a fast closed-form American
approximation, "use BS-2002 in loops and the tree as the truth". It is not in
this module, and that is a stated deviation rather than an omission:

  * BS-2002's two-step form needs a bivariate normal CDF, which is a second
    numerical component with its own accuracy failure modes — and a wrong
    approximation that runs fast is worse here than a slow exact one.
  * G1 Part D tells us how to decide: measure the early-exercise premium
    (`american_binomial` minus `bs_discrete_div`) on the grid we actually trade,
    and "if it shows the premium is negligible everywhere we trade, say so and
    simplify". That table is produced by `scripts/gamma/early_exercise_grid.py`
    and lands in `results/gamma/OPTION_MATH_<date>.md`. **The measurement
    decides whether a fast American approximation is needed at all.**
  * At the sizes this programme uses — a handful of legs marked once daily —
    the tree at 512 steps is already sub-millisecond per price.

If the premium table says the machinery is needed in loops, BS-2002 is the
follow-up, and it goes here beside the tree with the same test battery.

CONVENTIONS, FIXED ONCE SO NOTHING DOWNSTREAM RE-DECIDES THEM
-------------------------------------------------------------
* **Time** in years, **ACT/365F**, measured to the close of the expiration date.
  A same-day expiry is `T = 0` and every pricer returns intrinsic there.
* **Theta is per CALENDAR DAY**, not per year. Every consumer in this programme
  compares theta against a daily gamma term; a per-year theta is a silent 252x
  error, and that is the single most likely unit bug in the whole queue.
* **Vega is per ONE IMPLIED-VOL POINT (0.01)**, not per unit of sigma. Same
  reason, same size of error.
* **Rho** is per one percentage point of rate, for the same consistency.
* **Rates** come from the caller, which reads the repo's own curve
  (`data/riskfree_daily.parquet`), never a constant baked in here.
* **Dividends are a discrete SCHEDULE from data**, never a continuous yield
  assumption. A monthly distributor is not a continuous yielder.

NO SILENT FALLBACKS
-------------------
`implied_vol` returns **None** — never a number — when the price is outside the
no-arbitrage bounds, when the solver fails to bracket, or when `T <= 0`. A None
propagates and the caller decides. Never a default vol, never a silent clamp.
Every pricer raises, naming the argument, on a negative vol, a negative time or
a non-positive strike or spot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "BLACK76", "BS_DISCRETE_DIV", "AMERICAN_BINOMIAL", "MODELS",
    "OCC_EXERCISE_THRESHOLD_USD", "DAYS_PER_YEAR",
    "Greeks", "price", "greeks", "implied_vol", "forward", "breakeven_move",
    "pv_dividends", "is_exercised_by_exception", "year_fraction",
]

BLACK76 = "black76"
BS_DISCRETE_DIV = "bs_discrete_div"
AMERICAN_BINOMIAL = "american_binomial"
MODELS = (BLACK76, BS_DISCRETE_DIV, AMERICAN_BINOMIAL)

# ACT/365F. The option world's day count for time-to-expiry.
DAYS_PER_YEAR = 365.0

# The OCC exercises by exception at one cent in the money at expiration, for
# equity and ETF options. One implementation, here, so the ledger's settlement
# and any research that models expiry cannot disagree about the boundary.
OCC_EXERCISE_THRESHOLD_USD = 0.01

_DEFAULT_STEPS = 512
# Below this the CRR lattice degenerates (see _american_binomial).
_MIN_TREE_SIGMA = 1e-6

# MEASURED convergence of this lattice to the closed form, 2026-09-11, on an
# ATM 60-day call at sigma 0.20: the gap is clean O(1/n) with
#
#     |tree(n) - black_scholes| * n  =  0.640  for n in (64, 256, 1024, 2000, 4000)
#
# i.e. 1.0e-2 at n=64, 3.2e-4 at n=2000, 1.6e-4 at n=4000. There is no
# sawtooth to average away; the constant is stable to three figures.
#
# G1 Part C asks for "under 1e-4 at 2,000 steps". THAT IS NOT ACHIEVABLE with
# a plain CRR tree -- the law above puts 1e-4 at n = 6,400 -- and the number in
# the prompt was an expectation, not a measurement (CLAUDE.md H14 applies to
# the prompts too). The test asserts the measured law instead, which is a
# stronger statement than a threshold: it fails if the lattice changes order of
# convergence, not merely if it gets slower.
_CRR_CONVERGENCE_CONSTANT = 0.640
_SQRT_2PI = math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Normal distribution
# ---------------------------------------------------------------------------

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _norm_cdf(x: float) -> float:
    """Phi(x) via erf — exact to double precision, no table, no dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _check(S, K, T, sigma, right, model):
    if right not in ("C", "P"):
        raise ValueError(f"right must be 'C' or 'P', got {right!r}")
    if model not in MODELS:
        raise ValueError(f"model must be one of {MODELS}, got {model!r}")
    if not (S > 0):
        raise ValueError(f"spot must be positive, got {S!r}")
    if not (K > 0):
        raise ValueError(f"strike must be positive, got {K!r}")
    if T < 0:
        raise ValueError(f"time to expiry must be non-negative, got {T!r}")
    if sigma is not None and sigma < 0:
        raise ValueError(f"volatility must be non-negative, got {sigma!r}")


def year_fraction(days: float) -> float:
    """ACT/365F. Stated as a function so nobody divides by 252 by accident."""
    return float(days) / DAYS_PER_YEAR


# ---------------------------------------------------------------------------
# Dividends
# ---------------------------------------------------------------------------

def pv_dividends(q_schedule, r: float, T: float) -> float:
    """PV of the discrete cash dividends paid strictly before expiry.

    `q_schedule` is an iterable of `(t_years, amount_per_share)` — the shape the
    data gives us, not a yield. A dividend exactly at T is excluded: the holder
    of an option does not receive it.
    """
    if not q_schedule:
        return 0.0
    out = 0.0
    for t, amt in q_schedule:
        t, amt = float(t), float(amt)
        if amt < 0:
            raise ValueError(f"negative dividend {amt!r} at t={t!r}")
        if 0.0 <= t < T:
            out += amt * math.exp(-r * t)
    return out


def forward(S: float, T: float, r: float, q_schedule=None) -> float:
    """F = (S - PV(divs)) * e^{rT}. The forward the Black-76 form prices off."""
    return (S - pv_dividends(q_schedule, r, T)) * math.exp(r * T)


def breakeven_move(S: float, sigma_imp: float, dt: float = 1.0 / 252.0) -> float:
    """The move the underlier must make for a delta-hedged long option to break even.

    Setting the gamma gain against theta, ½G(dS)^2 + T*dt = 0 with
    T ≈ −½σ²S²G, gives dS ≈ S·σ·sqrt(dt). For a once-daily hedge dt = 1/252.

    This falls out of the ATM asymptotics and — the useful part — **does not
    depend on the option's own tenor**, because |Θ|/Γ ≈ ½σ²S² is tenor-invariant.
    It is the first screen on any candidate trade: if the underlier does not
    routinely move more than this, long gamma does not pay.
    """
    if S <= 0 or sigma_imp < 0 or dt < 0:
        raise ValueError(f"breakeven_move({S!r}, {sigma_imp!r}, {dt!r})")
    return S * sigma_imp * math.sqrt(dt)


def is_exercised_by_exception(settlement: float, strike: float, right: str,
                              threshold: float = OCC_EXERCISE_THRESHOLD_USD) -> bool:
    """OCC exercise-by-exception: at least `threshold` in the money at expiry.

    ONE implementation, because the ledger's settlement (G4 Part B) and any
    research that models an expiry must agree about the boundary to the cent.
    The threshold is inclusive — exactly $0.01 ITM is exercised.
    """
    if right not in ("C", "P"):
        raise ValueError(f"right must be 'C' or 'P', got {right!r}")
    itm = (settlement - strike) if right == "C" else (strike - settlement)
    return itm >= threshold - 1e-12


# ---------------------------------------------------------------------------
# The three pricers
# ---------------------------------------------------------------------------

def _intrinsic(S: float, K: float, right: str) -> float:
    return max(S - K, 0.0) if right == "C" else max(K - S, 0.0)


def _black76(F: float, K: float, T: float, r: float, sigma: float,
             right: str) -> float:
    """European option on a forward. df * [F N(d1) - K N(d2)] for a call."""
    df = math.exp(-r * T)
    if T <= 0 or sigma <= 0:
        return df * _intrinsic(F, K, right)
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if right == "C":
        return df * (F * _norm_cdf(d1) - K * _norm_cdf(d2))
    return df * (K * _norm_cdf(-d2) - F * _norm_cdf(-d1))


def _bs_discrete_div(S, K, T, r, q_schedule, sigma, right) -> float:
    """European Black-Scholes on spot net of the PV of known discrete dividends."""
    S_adj = S - pv_dividends(q_schedule, r, T)
    if S_adj <= 0:
        raise ValueError(
            f"dividends to expiry ({S - S_adj:.4f}) exceed spot ({S:.4f}); the "
            f"schedule is wrong, not the option")
    return _black76(S_adj * math.exp(r * T), K, T, r, sigma, right)


def _american_binomial(S, K, T, r, q_schedule, sigma, right,
                       steps: int = _DEFAULT_STEPS) -> float:
    """Cox-Ross-Rubinstein with discrete dividends and early exercise at every node.

    Dividends are applied the way they actually happen: the share price DROPS by
    the cash amount on the ex-date. That is modelled by pricing the tree on the
    dividend-free component `S - PV(divs to date)` and adding the remaining PV
    back at each node, which keeps the lattice recombining (a tree that subtracts
    cash directly does not recombine, and the node count explodes).

    Early exercise is tested against the FULL share price — dividend-free
    component plus the PV of dividends still to come — because that is what the
    holder receives on exercise.
    """
    if T <= 0:
        return _intrinsic(S, K, right)
    # A sigma at or below this is not "small volatility", it is no diffusion:
    # u -> 1, d -> 1 and the risk-neutral probability (e^{r dt} - d)/(u - d)
    # divides by ~0 and lands outside [0,1]. Measured: sigma=1e-9 gives
    # p = 367,726. Handle it as the degenerate case it is rather than letting
    # the tree produce a number.
    if sigma <= _MIN_TREE_SIGMA:
        # No diffusion: the price is the discounted intrinsic at the forward,
        # or immediate intrinsic if that is worth more.
        fwd = forward(S, T, r, q_schedule)
        return max(_intrinsic(S, K, right),
                   math.exp(-r * T) * _intrinsic(fwd, K, right))
    if steps < 1:
        raise ValueError(f"steps must be >= 1, got {steps!r}")

    dt = T / steps
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    disc = math.exp(-r * dt)
    p = (math.exp(r * dt) - d) / (u - d)
    if not (0.0 <= p <= 1.0):
        raise ValueError(
            f"risk-neutral probability {p:.4f} outside [0,1] — the tree is "
            f"unstable at sigma={sigma!r}, r={r!r}, dt={dt!r}. Increase steps.")

    pv_all = pv_dividends(q_schedule, r, T)
    x0 = S - pv_all                      # dividend-free component at t=0
    if x0 <= 0:
        raise ValueError(
            f"dividends to expiry ({pv_all:.4f}) exceed spot ({S:.4f})")

    def pv_remaining(t: float) -> float:
        """PV, at time t, of dividends paid at or after t and before T."""
        if not q_schedule:
            return 0.0
        return sum(float(a) * math.exp(-r * (float(td) - t))
                   for td, a in q_schedule if t <= float(td) < T)

    # Terminal layer: no dividends remain at T.
    xs = [x0 * (u ** j) * (d ** (steps - j)) for j in range(steps + 1)]
    vals = [_intrinsic(x, K, right) for x in xs]

    for i in range(steps - 1, -1, -1):
        t = i * dt
        add = pv_remaining(t)
        for j in range(i + 1):
            cont = disc * (p * vals[j + 1] + (1.0 - p) * vals[j])
            x = x0 * (u ** j) * (d ** (i - j))
            vals[j] = max(cont, _intrinsic(x + add, K, right))
        vals = vals[:i + 1]
    return vals[0]


def price(S: float, K: float, T: float, r: float, q_schedule, sigma: float,
          right: str, model: str = AMERICAN_BINOMIAL, *,
          steps: int = _DEFAULT_STEPS) -> float:
    """One option price. `model` is explicit; there is no implicit European.

    For `black76`, `S` is read as the FORWARD (that is what Black-76 prices off)
    and `q_schedule` is ignored — pass it as None and the caller states why.
    """
    _check(S, K, T, sigma, right, model)
    if model == BLACK76:
        return _black76(S, K, T, r, sigma, right)
    if model == BS_DISCRETE_DIV:
        return _bs_discrete_div(S, K, T, r, q_schedule, sigma, right)
    return _american_binomial(S, K, T, r, q_schedule, sigma, right, steps=steps)


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------

@dataclass
class Greeks:
    """Greeks in the units this programme compares them in. See the module docstring.

    delta  dPrice/dSpot, per one unit of underlier
    gamma  d2Price/dSpot2
    theta  per CALENDAR DAY (not per year)
    vega   per ONE VOL POINT, i.e. per 0.01 of sigma (not per unit)
    vanna  dDelta/dVol, per one vol point
    volga  dVega/dVol, per one vol point
    charm  dDelta/dTime, per calendar day
    rho    per ONE PERCENTAGE POINT of rate
    """

    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    vanna: float
    volga: float
    charm: float
    rho: float

    def to_leg_greeks(self, F=None, K=None, T=None, sigma=None, df=None):
        """Adapt to `src.deploy.sleeve.LegGreeks`, the seam the sleeves read."""
        from src.deploy.sleeve import LegGreeks
        return LegGreeks(price=self.price, delta=self.delta, F=F, K=K, T=T,
                         sigma=sigma, df=df)


# Differencing steps. Stated here rather than inline so a reader can see what
# tolerance to expect from the finite-difference greeks, and so the tests can
# import the same numbers instead of guessing at them.
_H_S = 1e-4        # relative, on spot
_H_V = 1e-4        # absolute, on sigma
_H_T = 1.0 / DAYS_PER_YEAR   # one calendar day, on time
_H_R = 1e-5        # absolute, on the rate


def greeks(S: float, K: float, T: float, r: float, q_schedule, sigma: float,
           right: str, model: str = AMERICAN_BINOMIAL, *,
           steps: int = _DEFAULT_STEPS) -> Greeks:
    """Greeks by central differences on `price`, in the units above.

    WHY FINITE DIFFERENCES EVEN WHERE ANALYTIC FORMS EXIST. Black-76 has closed
    forms, the binomial tree does not, and a module that mixed the two would
    report greeks whose definition depended on the model — the caller would have
    to know which. Differencing the same `price` function keeps one definition,
    and the analytic forms are used as the TEST oracle
    (`test_optmath_greeks.py`) rather than as a second implementation.

    Theta differences FORWARD in time (the option ages), never centred, because
    a centred theta at short tenors reaches past expiry.
    """
    _check(S, K, T, sigma, right, model)
    f = lambda s, t, v, rr: price(  # noqa: E731
        s, K, max(t, 0.0), rr, q_schedule, v, right, model, steps=steps)

    p0 = f(S, T, sigma, r)
    hS = S * _H_S
    up, dn = f(S + hS, T, sigma, r), f(S - hS, T, sigma, r)
    delta = (up - dn) / (2.0 * hS)
    gamma = (up - 2.0 * p0 + dn) / (hS * hS)

    # theta: one calendar day forward, and the sign is negative for a long
    # option that is losing time value.
    if T > _H_T:
        theta = f(S, T - _H_T, sigma, r) - p0
    else:
        theta = _intrinsic(S, K, right) - p0     # the last day

    vu, vd = f(S, T, sigma + _H_V, r), f(S, T, max(sigma - _H_V, 0.0), r)
    vega = (vu - vd) / (2.0 * _H_V) * 0.01       # per vol POINT
    volga = (vu - 2.0 * p0 + vd) / (_H_V * _H_V) * 0.01 * 0.01

    # vanna = d2P/dS dsigma, per vol point
    vanna = ((f(S + hS, T, sigma + _H_V, r) - f(S - hS, T, sigma + _H_V, r)
              - f(S + hS, T, sigma - _H_V, r) + f(S - hS, T, sigma - _H_V, r))
             / (4.0 * hS * _H_V)) * 0.01

    # charm = dDelta/dTime, per calendar day, same forward convention as theta
    if T > _H_T:
        d_later = ((f(S + hS, T - _H_T, sigma, r) - f(S - hS, T - _H_T, sigma, r))
                   / (2.0 * hS))
        charm = d_later - delta
    else:
        charm = 0.0

    rho = (f(S, T, sigma, r + _H_R) - f(S, T, sigma, r - _H_R)) / (2.0 * _H_R) * 0.01

    return Greeks(price=p0, delta=delta, gamma=gamma, theta=theta, vega=vega,
                  vanna=vanna, volga=volga, charm=charm, rho=rho)


# ---------------------------------------------------------------------------
# Implied volatility
# ---------------------------------------------------------------------------

def _no_arb_bounds(S, K, T, r, q_schedule, right, model):
    """(lower, upper) on a European price; the American lower bound is intrinsic."""
    df = math.exp(-r * T)
    if model == BLACK76:
        F, disc_k = S, df * K
        lo = max(df * (F - K), 0.0) if right == "C" else max(df * (K - F), 0.0)
        hi = df * F if right == "C" else disc_k
    else:
        S_adj = S - pv_dividends(q_schedule, r, T)
        lo = max(S_adj - df * K, 0.0) if right == "C" else max(df * K - S_adj, 0.0)
        hi = S_adj if right == "C" else df * K
    if model == AMERICAN_BINOMIAL:
        lo = max(lo, _intrinsic(S, K, right))
        if right == "P":
            hi = max(hi, K)          # an American put is worth at most K
    return lo, hi


def implied_vol(target: float, S: float, K: float, T: float, r: float,
                q_schedule, right: str, model: str = AMERICAN_BINOMIAL, *,
                steps: int = _DEFAULT_STEPS, tol: float = 1e-8,
                vol_tol: float = 1e-8, max_iter: int = 200,
                vol_hi: float = 5.0) -> float | None:
    """Invert `price` for sigma. Returns **None**, never a fallback, on failure.

    None is returned when:
      * `T <= 0` — there is no volatility to imply from an expired option;
      * the target is outside the model's no-arbitrage bounds — a price that
        cannot come from this model does not have an implied vol in it;
      * the solver cannot bracket a root below `vol_hi`;
      * **the vol is not identified** — the option has so little vega that the
        entire plausible vol range moves the price by less than the tolerance.
        Returning the bisection midpoint there is a confident wrong number.

    HOUSE RULE, and the reason this is spelled out: never return a default vol,
    never clamp silently. A None propagates and the caller decides — the same
    discipline `mark_fn` already follows when it runs out of marks.

    Bisection, not Newton. Vega vanishes for deep out-of-the-money options and
    Newton then diverges or returns a confident wrong number; bisection on a
    monotone function cannot, and the extra iterations are free at our sizes.
    """
    # T <= 0 is answered BEFORE validation: an expired option has no implied
    # vol, and that is a None, not a ValueError. _check would raise on T < 0.
    if T is None or T <= 0:
        return None
    _check(S, K, T, None, right, model)
    lo_p, hi_p = _no_arb_bounds(S, K, T, r, q_schedule, right, model)
    if target < lo_p - 1e-10 or target > hi_p + 1e-10:
        return None

    f = lambda v: price(  # noqa: E731
        S, K, T, r, q_schedule, v, right, model, steps=steps) - target

    lo, hi = _MIN_TREE_SIGMA, vol_hi
    f_lo, f_hi = f(lo), f(hi)

    if f_lo > 0:                 # target below the zero-vol price
        return None
    if f_hi < 0:                 # target above anything vol_hi can produce
        return None

    # Bisect to convergence IN VOL, not in price. A price-space tolerance on a
    # low-vega option is satisfied by a wide band of vols and returns an
    # arbitrary member of it.
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if (hi - lo) < vol_tol:
            return mid if _is_identified(f, mid, tol) else None
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return None


def _is_identified(f, sigma: float, tol: float, bump: float = 0.005) -> bool:
    """Is there enough vega AT THE SOLUTION for the answer to mean anything?

    THE FAILURE THIS PREVENTS, measured 2026-09-11. A 7-day call at 0.85
    moneyness has a price IDENTICAL to double precision for every sigma from
    0.01 to 0.156 — vega per vol point is exactly 0.0. Bisection on a flat
    function is not wrong, it simply has nothing to converge to, and it returned
    **0.156 for a true 0.06**: no error, no warning, a confident wrong number.

    An earlier version of this check asked whether the price was flat across the
    WHOLE bracket [1e-6, 5.0]. That interval is never flat — a 500% vol moves
    any option — so the check never fired. The question is local: can one vol
    point either side of the answer move the price by more than the tolerance we
    solved to? If not, the data does not contain the vol.
    """
    a = f(max(sigma - bump, _MIN_TREE_SIGMA))
    b = f(sigma + bump)
    return abs(b - a) > max(tol, 1e-12) * 10.0
