"""w proportional to Sigma^-1 alpha, and whether it is worth anything here.

THE PROBLEM IT ADDRESSES
------------------------
There is no covariance matrix anywhere in the sleeve. Weights are built as
w = -(z - mean z) / sum|z|, which treats seventeen funds as seventeen
independent bets. They are not. Decomposing book variance on the sleeve's own
weights (plan_diagnostics.py, block `pca`):

    PC1   3.6%   market direction -- correctly neutralised by dollar-neutrality
    PC2  65.7%   MUNI vs TAXABLE  -- +0.32 on all six Nuveen munis, negative on
                                     all eleven others, and entirely unmanaged
    PC3   9.6%   quality / duration residual
    rest 21.1%   genuinely idiosyncratic

    BR_eff = 1 / sum(v_k^2) = 2.24 effective bets out of 17 names.

IR ~ IC sqrt(BR), so breadth computed on the name count overstates by 2.75x.
The dollar-neutral construction kills market beta and then puts two-thirds of
the remaining risk into one spread bet nobody chose.

THE STANDARD FIX, AND THE HONEST TEST OF IT
-------------------------------------------
Mean-variance says w proportional to Sigma^-1 alpha, not alpha. Sigma^-1 does
not forbid factor exposure -- it charges for it, keeping the exposure where
alpha justifies the risk and cutting it where it does not. That is a different
object from hard group-neutrality, which was already tested here and LOST
(gross Sharpe 0.97 -> 0.82) precisely because it removed exposure the alpha was
paying for.

SHRINKAGE IS NOT OPTIONAL. With 17 names and a 252-day window the sample
covariance is estimable but its INVERSE is not: inversion loads on the smallest
eigenvalues, which are the worst-estimated directions, so an unshrunk Sigma^-1
concentrates the book into estimation noise. Ledoit-Wolf (2004) shrinks toward
a scaled identity with an analytically optimal intensity.

ALPHA UNITS MATTER. Sigma^-1 alpha is only meaningful if alpha is an expected
RETURN. The sleeve's z is a normalised score, so it is converted the Grinold
way, alpha_i = IC * sigma_i * z_i -- IC is a common scalar and drops out of a
gross-normalised book, but sigma_i does not.

NO LOOKAHEAD: Sigma is estimated on a trailing window ending the day before use.

Usage:  python3 scripts/cef/covariance_construction.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ou_score import panel                                    # noqa: E402
from spec import BAND_WIDTH, LIVE_POLICY, summary as spec_summary  # noqa: E402  spec-owned params, never literals
from band_frontier import (UNIVERSE, Z_WINDOW, MIN_PERIODS, VOL_TARGET,
                           VOL_LOOKBACK, MIN_ADV, MIN_NAMES, SAMPLE_START,
                           calendar, band, evaluate)          # noqa: E402

COV_WINDOW = 252
COV_REFIT = 21           # re-estimate Sigma monthly; daily is noise, not signal


def br_eff(w: pd.Series, S: np.ndarray) -> float:
    """Effective breadth: 1 / sum of squared variance shares over eigenvectors."""
    ev, V = np.linalg.eigh(S)
    ev = np.clip(ev, 1e-14, None)
    c = V.T @ w.values                       # weight in each eigen-direction
    var = (c ** 2) * ev
    tot = var.sum()
    if tot <= 0:
        return float("nan")
    share = var / tot
    return float(1.0 / (share ** 2).sum())


def build(mode: str, shrink: bool = True):
    """mode: 'plain' (live), 'inv_z', 'inv_alpha'."""
    px, disc, ret, adv = panel()
    mu = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).mean().shift(1)
    sd = disc.rolling(Z_WINDOW, min_periods=MIN_PERIODS).std().shift(1)
    z = ((disc - mu) / sd.replace(0, np.nan)).clip(-4, 4)
    vol_i = ret.rolling(COV_WINDOW, min_periods=120).std().shift(1)

    tgt = pd.DataFrame(0.0, index=z.index, columns=UNIVERSE)
    start = z.index.searchsorted(pd.Timestamp(SAMPLE_START))
    Sig, cols_cached, brs = None, None, []

    for i in range(start, len(z.index)):
        row = z.iloc[i].dropna()
        row = row[[t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV]]
        if len(row) < MIN_NAMES:
            tgt.iloc[i] = tgt.iloc[i - 1]
            continue
        cols = list(row.index)

        if mode != "plain" and (Sig is None or cols != cols_cached
                                or (i - start) % COV_REFIT == 0):
            # strictly prior returns; ending the day before the signal date
            H = ret[cols].iloc[max(0, i - COV_WINDOW):i].dropna()
            if len(H) < 120:
                Sig, cols_cached = None, None
            else:
                Sig = (LedoitWolf().fit(H.values).covariance_ if shrink
                       else np.cov(H.values, rowvar=False))
                cols_cached = cols

        if mode == "plain" or Sig is None:
            w = -(row - row.mean())
        else:
            a = -row.values.astype(float)
            if mode == "inv_alpha":                     # Grinold units
                a = a * vol_i.iloc[i][cols].fillna(vol_i.iloc[i].median()).values
            try:
                raw = np.linalg.solve(Sig, a)
            except np.linalg.LinAlgError:
                raw = a
            w = pd.Series(raw, index=cols)
            w = w - w.mean()                            # dollar-neutral

        den = w.abs().sum()
        if den <= 0:
            tgt.iloc[i] = tgt.iloc[i - 1]
            continue
        w = w / den
        if Sig is not None and len(brs) < 4000:
            brs.append(br_eff(w.reindex(cols).fillna(0.0), Sig))

        hist = ret[cols].iloc[:i + 1].mul(w, axis=1).sum(axis=1).tail(VOL_LOOKBACK)
        rv = hist.std() * np.sqrt(252)
        scal = float(np.clip(VOL_TARGET / rv, 0.2, 2.5)) if rv > 0 else 1.0
        tgt.iloc[i] = (w * scal).reindex(UNIVERSE).fillna(0.0).values

    T = tgt.iloc[start:]
    return T, ret.reindex(T.index)[UNIVERSE].fillna(0.0), np.nanmean(brs) if brs else np.nan


def main() -> int:
    hdr = (f"{'construction':<30}{'policy':<11}{'gross':>8}{'ann%':>7}"
           f"{'turn':>7}{'net@15':>8}{'BR_eff':>8}")
    print(hdr); print("-" * len(hdr))
    for mode, label, shr in (
            ("plain",     "w ~ alpha  (live construction)",  True),
            ("inv_z",     "w ~ Sigma^-1 z   (LW shrunk)",   True),
            ("inv_alpha", "w ~ Sigma^-1 (sig*z) (LW)",      True),
            ("inv_alpha", "w ~ Sigma^-1 (sig*z) UNSHRUNK",  False)):
        T, R, br = build(mode, shrink=shr)
        # Baseline against the LIVE policy, read from the frozen spec. This read
        # `band(T, 0.064)` until 2026-09-10 -- the width deliberately NOT chosen
        # on 2026-09-06, so every row was measured against a book nobody runs.
        for pol, H in (("calendar 2d", calendar(T, 2)),
                       (LIVE_POLICY, band(T, BAND_WIDTH))):
            r = evaluate(H, R)
            net = (r["ann_ret"] - r["turn"] * 15 / 1e4) / r["vol"]
            print(f"{label:<30}{pol:<11}{r['gross_sr']:>8.2f}{r['ann_ret']*100:>7.2f}"
                  f"{r['turn']:>7.1f}{net:>8.2f}"
                  f"{('' if np.isnan(br) else f'{br:.2f}'):>8}")
        print()
    print("BR_eff is the effective number of independent bets, averaged over the")
    print("sample. 17 names; the live construction measures 2.24.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
