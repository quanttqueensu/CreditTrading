"""At what resolution should this book treat funds differently?

THE QUESTION
------------
The sleeve applies one z-window, one band width, one vol target and one set of
rules to all seventeen funds. They are visibly not the same instrument: half-
lives span 11.9-41.9 business days, borrow 0.28-10.56%, a tick is 2.9-10.7bp,
ADV spans 12x, and the panel contains four distinct asset groups (muni, multi-
sector, high yield, loan) with different buyers, tax treatment and leverage.

The obvious answer -- give every fund its own parameters -- is a trap. With
BR_eff around 1.2-2.2 effective bets, seventeen independent parameter sets is
the z_window=63 mistake seventeen times over, and `ou_score.py` already measured
it: RAW per-name kappa scored 0.94 gross / 0.35 net against POOLED 1.20 / 0.70.
Per-name estimation lost outright.

So the real question is the RESOLUTION at which differences are estimable:

    pooled  ->  one number for the book
    group   ->  one number per asset group (muni / multi / hy / loan)
    name    ->  one number per fund

This is answerable, not arguable. For each candidate parameter, decompose the
cross-sectional spread into signal and estimation noise:

    tau^2 = Var(theta_hat) - E[se^2]          between-name TRUE variance
    w     = tau^2 / (tau^2 + se^2)            empirical-Bayes shrinkage weight

w near 1 means the names really do differ and per-name is estimable. w near 0
means the observed spread is mostly noise and per-name fitting will overfit.
Separately, an R^2 of group membership against the per-name estimates says
whether GROUP is the right resolution -- i.e. whether the differences are
structural (muni vs taxable) rather than idiosyncratic.

Usage:  python3 scripts/cef/per_name_resolution.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from band_frontier import UNIVERSE, Z_WINDOW, MIN_PERIODS      # noqa: E402
from exit_study import panel                                   # noqa: E402

N_BOOT = 400


def groups():
    u = pd.read_csv(REPO / "data/cef/cef_universe.csv")
    return {r.ticker: str(r.grp) for r in u.itertuples() if r.ticker in UNIVERSE}


def ar1_with_se(x):
    a, b = x[:-1], x[1:]
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 250:
        return np.nan, np.nan
    sxx = float((a * a).sum())
    phi = float((a * b).sum() / sxx)
    resid = b - phi * a
    s2 = float((resid ** 2).sum()) / (len(a) - 1)
    return phi, float(np.sqrt(s2 / sxx))


def block_boot_se(v, fn, n=N_BOOT, block=63):
    """Standard error of a statistic under a moving-block bootstrap."""
    v = v[np.isfinite(v)]
    if len(v) < 500:
        return np.nan
    nb = len(v) // block
    rng = np.random.default_rng(0)
    out = []
    for _ in range(n):
        st = rng.integers(0, len(v) - block, nb)
        out.append(fn(np.concatenate([v[s:s + block] for s in st])))
    return float(np.nanstd(out, ddof=1))


def eb(theta, se):
    """Empirical-Bayes shrinkage weight per name, and the pooled tau^2."""
    ok = np.isfinite(theta) & np.isfinite(se) & (se > 0)
    if ok.sum() < 4:
        return np.nan, np.full(len(theta), np.nan)
    tau2 = max(0.0, float(np.var(theta[ok], ddof=1)) - float(np.mean(se[ok] ** 2)))
    w = np.where(ok, tau2 / (tau2 + se ** 2), np.nan)
    return tau2, w


def group_r2(theta, grp):
    """Share of the cross-name variance explained by asset-group membership."""
    ok = np.isfinite(theta)
    if ok.sum() < 6:
        return np.nan
    t, g = theta[ok], np.array(grp)[ok]
    tot = float(np.var(t, ddof=1)) * (len(t) - 1)
    if tot <= 0:
        return np.nan
    within = 0.0
    for u in set(g):
        s = t[g == u]
        if len(s) > 1:
            within += float(np.var(s, ddof=1)) * (len(s) - 1)
    return float(1.0 - within / tot)


def main() -> int:
    px, disc, ret, z = panel()
    G = groups()
    names = [t for t in UNIVERSE if t in px.columns]
    grp = [G.get(t, "?") for t in names]

    mu = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    x = disc - mu

    est = {}
    # --- kappa (reversion rate) ---------------------------------------------
    phi, sep = [], []
    for t in names:
        p_, s_ = ar1_with_se(x[t].to_numpy(float))
        phi.append(p_); sep.append(s_)
    phi, sep = np.array(phi), np.array(sep)
    kap = -np.log(np.clip(phi, 1e-6, 0.999999))
    # delta method: se(kappa) = se(phi)/phi
    est["kappa (reversion rate)"] = (kap, sep / np.clip(phi, 1e-6, None))

    # --- discount volatility -------------------------------------------------
    sd = np.array([float(x[t].std()) for t in names])
    sdse = np.array([block_boot_se(x[t].to_numpy(float), np.nanstd) for t in names])
    est["sigma_d (discount vol)"] = (sd, sdse)

    # --- price volatility ----------------------------------------------------
    pv = np.array([float(ret[t].std()) * np.sqrt(252) for t in names])
    pvse = np.array([block_boot_se(ret[t].to_numpy(float),
                                   lambda a: np.nanstd(a) * np.sqrt(252)) for t in names])
    est["sigma_P (price vol)"] = (pv, pvse)

    print(f"{len(names)} names, {len(set(grp))} asset groups "
          f"({', '.join(sorted(set(grp)))})\n")
    hdr = (f"{'parameter':<26}{'spread':>18}{'mean w':>9}{'names w>0.5':>13}"
           f"{'group R^2':>11}  resolution")
    print(hdr); print("-" * len(hdr))

    for k, (th, se) in est.items():
        tau2, w = eb(th, se)
        r2 = group_r2(th, grp)
        mw = float(np.nanmean(w))
        nhi = int(np.nansum(w > 0.5))
        spread = f"{np.nanmin(th):.3f}-{np.nanmax(th):.3f}"
        # the decision rule, stated once and applied uniformly
        res = ("PER-NAME" if mw > 0.7 else
               "GROUP" if (np.isfinite(r2) and r2 > 0.5) else
               "POOLED")
        print(f"{k:<26}{spread:>18}{mw:>9.2f}{nhi:>13}{r2:>11.2f}  {res}")

    print("-" * len(hdr))
    print("w = tau^2/(tau^2+se^2): share of the observed cross-name spread that is")
    print("REAL rather than estimation noise. w>0.7 -> per-name is estimable.")
    print("group R^2 > 0.5 -> the differences are structural, so GROUP is the right")
    print("resolution and per-name adds parameters without adding information.\n")

    # --- observed, non-estimated attributes: these need no shrinkage ---------
    print("MEASURED ATTRIBUTES (observed, not estimated -- no overfitting risk):")
    bor = pd.read_csv(REPO / "data/cef/cef_borrow.csv")
    bor = bor[bor.date == bor.date.max()].set_index("ticker")
    last_px = px.ffill().iloc[-1]
    print(f"  {'ticker':<8}{'grp':<7}{'half-life':>10}{'borrow %':>10}"
          f"{'1c tick bp':>12}{'px':>8}")
    for t, g_, k_ in sorted(zip(names, grp, kap), key=lambda r: r[1]):
        hl = np.log(2) / k_
        fee = bor.fee_rate_pct.get(t, np.nan)
        tick = 1e4 * 0.01 / float(last_px[t])
        print(f"  {t:<8}{g_:<7}{hl:>10.1f}{fee:>10.2f}{tick:>12.2f}{last_px[t]:>8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
