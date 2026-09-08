"""The OU score: put the reversion rate and the right volatility into the signal.

WHAT THE LIVE SLEEVE COMPUTES
-----------------------------
    z_i = x_i / sigma^d_i          x_i = discount minus its own rolling mean

WHAT THE MODEL SAYS IT SHOULD COMPUTE
-------------------------------------
Model each fund's dislocation as Ornstein-Uhlenbeck, dx_i = -kappa_i x_i dt +
sigma_i dW_i. Then the expected convergence over a holding period h is exact:

    E[x_{t+h} - x_t] = -x_t (1 - e^{-kappa_i h}) = -x_t (1 - phi_i^h)

and the thing we actually earn is a PRICE return, so the risk it should be
divided by is price volatility over the same horizon, not the volatility of the
discount series:

    score_i = -x_i (1 - phi_i^h) / (sigma^P_i * sqrt(h))

Two terms are missing from the live score and they are not cosmetic. Over a
2-day hold DSL (half-life 11.9bd) delivers 11.0% of its dislocation and PHK
(41.9bd) delivers 3.3%. We currently size them identically.

NO LOOKAHEAD, AND THIS IS THE PART THAT IS EASY TO GET WRONG
-----------------------------------------------------------
phi is a parameter estimated FROM the panel, so estimating it once on all
history and then "backtesting" is circular -- every day's signal would embed
knowledge of how fast that fund reverted in years that had not happened yet.
Here phi is re-estimated on an EXPANDING window ending the day before it is
used, refreshed annually, and the first REFIT_EVERY days are simply unavailable.

SHRINKAGE IS MANDATORY, NOT OPTIONAL
------------------------------------
Per-name AR(1) estimates on ~17 names are noisy and the half-life transform
ln2/(-ln phi) is convex, so noise in phi inflates the spread of half-lives in a
way that looks like signal. Estimates are shrunk toward the pooled phi by
empirical Bayes: w_i = tau^2 / (tau^2 + s_i^2), where tau^2 is the cross-name
dispersion net of estimation variance. When the names genuinely differ, tau^2 is
large and shrinkage is light; when they do not, everything collapses to pooled
and the score degenerates gracefully to the pooled case.

Usage:  python3 scripts/cef/ou_score.py [--h 2]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from band_frontier import (UNIVERSE, Z_WINDOW, MIN_PERIODS, VOL_TARGET,
                           VOL_LOOKBACK, MIN_ADV, MIN_NAMES, SAMPLE_START,
                           calendar, band, evaluate)          # noqa: E402

REFIT_EVERY = 252          # re-estimate phi once a year
MIN_FIT_OBS = 500          # ~2 years before a per-name phi is trusted at all


def panel():
    P = pd.read_parquet(REPO / "data/cef/cef_prices.parquet")
    N = pd.read_parquet(REPO / "data/cef/cef_nav.parquet")
    P, N = P[P.ticker.isin(UNIVERSE)], N[N.ticker.isin(UNIVERSE)]
    d = P.merge(N, on=["date", "ticker"], how="inner")
    d["date"] = pd.to_datetime(d["date"])
    d = d[(d.nav > 0.5) & (d.close > 0.5)]
    piv = lambda c: d.pivot_table(index="date", columns="ticker", values=c).sort_index()
    px, nav, vol = piv("close"), piv("nav"), piv("volume")
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    disc = 100.0 * (px - nav) / nav
    adv = (px * vol).rolling(63, min_periods=21).mean().shift(1)
    return px, disc, ret, adv


def ar1(x: np.ndarray) -> tuple[float, float]:
    """OLS through the origin on x_{t+1} = phi x_t. Returns (phi, se)."""
    a, b = x[:-1], x[1:]
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 60:
        return np.nan, np.nan
    sxx = float((a * a).sum())
    if sxx <= 0:
        return np.nan, np.nan
    phi = float((a * b).sum() / sxx)
    resid = b - phi * a
    s2 = float((resid ** 2).sum()) / max(len(a) - 1, 1)
    return phi, float(np.sqrt(s2 / sxx))


def shrink(phis: pd.Series, ses: pd.Series) -> pd.Series:
    """Empirical Bayes toward the pooled phi. Light when names truly differ."""
    ok = phis.notna() & ses.notna() & (ses > 0)
    if ok.sum() < 3:
        return phis
    p, s = phis[ok], ses[ok]
    pooled = float(p.mean())
    tau2 = max(0.0, float(p.var(ddof=1)) - float((s ** 2).mean()))
    w = tau2 / (tau2 + s ** 2)                     # 0 -> pooled, 1 -> raw
    out = phis.copy()
    out[ok] = w * p + (1 - w) * pooled
    return out.fillna(pooled)


def rolling_phi(x: pd.DataFrame, do_shrink=True, per_name=True) -> pd.DataFrame:
    """phi_i estimated on an expanding window ending at t-1, refit annually."""
    idx = x.index
    fits = {}
    for i in range(MIN_FIT_OBS, len(idx), REFIT_EVERY):
        hist = x.iloc[:i]                          # strictly before idx[i]
        phis, ses = {}, {}
        for t in x.columns:
            phis[t], ses[t] = ar1(hist[t].to_numpy(float))
        phis, ses = pd.Series(phis), pd.Series(ses)
        if not per_name:
            phis = pd.Series(float(phis.mean()), index=phis.index)
        elif do_shrink:
            phis = shrink(phis, ses)
        fits[idx[i]] = phis.clip(0.5, 0.9995)
    if not fits:
        return pd.DataFrame(index=idx, columns=x.columns, dtype=float)
    return pd.DataFrame(fits).T.reindex(idx).ffill()


def build(score: pd.DataFrame, ret, adv):
    """Cross-sectional dollar-neutral targets from any score matrix."""
    tgt = pd.DataFrame(0.0, index=score.index, columns=UNIVERSE)
    start = score.index.searchsorted(pd.Timestamp(SAMPLE_START))
    for i in range(start, len(score.index)):
        row = score.iloc[i].dropna()
        row = row[[t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV]]
        if len(row) < MIN_NAMES:
            tgt.iloc[i] = tgt.iloc[i - 1]
            continue
        w = -(row - row.mean())
        den = w.abs().sum()
        if den <= 0:
            tgt.iloc[i] = tgt.iloc[i - 1]
            continue
        w = w / den
        hist = ret[list(row.index)].iloc[:i + 1].mul(w, axis=1).sum(axis=1).tail(VOL_LOOKBACK)
        rv = hist.std() * np.sqrt(252)
        scal = float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0
        tgt.iloc[i] = (w * scal).reindex(UNIVERSE).fillna(0.0).values
    T = tgt.iloc[start:]
    return T, ret.reindex(T.index)[UNIVERSE].fillna(0.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h", type=int, default=2, help="holding horizon in days")
    a = ap.parse_args()
    h = a.h

    px, disc, ret, adv = panel()
    mu = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    x = disc - mu                                        # the dislocation
    sig_p = ret.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)

    # A -- what the sleeve does today
    z_live = (x / sd.replace(0, np.nan)).clip(-4, 4)

    phi_pool = rolling_phi(x, per_name=False)
    phi_raw = rolling_phi(x, do_shrink=False)
    phi_shr = rolling_phi(x, do_shrink=True)

    def ou(phi, denom):
        conv = 1.0 - phi.pow(h)                          # expected fraction closed
        return ((x * conv) / denom.replace(0, np.nan)).clip(-4, 4)

    scores = {
        "A live  z = x/sd_d": z_live,
        "B OU pooled k, /sd_d": ou(phi_pool, sd),
        "C OU shrunk k, /sd_d": ou(phi_shr, sd),
        "D OU shrunk k, /sd_P": ou(phi_shr, sig_p * np.sqrt(h) * 100),
        "E OU RAW k (no shrink)": ou(phi_raw, sd),
    }

    hl = np.log(2) / -np.log(phi_shr.iloc[-1].clip(upper=0.9999))
    hlr = np.log(2) / -np.log(phi_raw.iloc[-1].clip(upper=0.9999))
    print("half-lives (business days), final fit:")
    cmp = pd.DataFrame({"raw": hlr, "shrunk": hl}).sort_values("shrunk")
    print(cmp.round(1).T.to_string())
    print(f"\nraw spread {hlr.min():.1f}-{hlr.max():.1f}bd, "
          f"shrunk {hl.min():.1f}-{hl.max():.1f}bd "
          f"(shrinkage pulled the range in by "
          f"{100*(1-(hl.max()-hl.min())/(hlr.max()-hlr.min())):.0f}%)\n")

    hdr = f"{'score':<24}{'policy':<14}{'gross SR':>10}{'ann%':>8}{'turn':>8}{'net@15bp':>10}"
    print(hdr); print("-" * len(hdr))
    for name, sc in scores.items():
        T, R = build(sc, ret, adv)
        for pol, H in (("calendar 2d", calendar(T, 2)), ("band 6.4%", band(T, 0.064))):
            r = evaluate(H, R)
            net = (r["ann_ret"] - r["turn"] * 15 / 1e4) / r["vol"]
            print(f"{name:<24}{pol:<14}{r['gross_sr']:>10.2f}"
                  f"{r['ann_ret']*100:>8.2f}{r['turn']:>8.1f}{net:>10.2f}")
        print()
    print(f"horizon h = {h}d. phi refit every {REFIT_EVERY}d on an expanding")
    print("window ending the day before use; first fit needs "
          f"{MIN_FIT_OBS} observations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
