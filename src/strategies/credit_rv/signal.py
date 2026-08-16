"""Credit ETF statistical arbitrage — factor model, OU residuals, s-scores.

Implements CREDIT_RV_PREREG.md §3.  Every quantity on day ``t`` uses data through
``t`` only; positions formed from it are filled at the close of ``t+1``.

Pipeline
--------
1. Excess returns over the daily bill rate.
2. Five tradeable factors (rates level, curve slope, credit, quality, equity),
   Gram-Schmidt orthogonalised **inside the trailing estimation window** so the
   beta matrix is well-conditioned without peeking forward.
3. Rolling multivariate OLS -> beta matrix ``B`` (N x K) per day.
4. Residual path over a shorter window; cumulate to ``X``.
5. AR(1) on ``X`` -> OU parameters (kappa, m, sigma_eq) -> s-score.
6. Two-level blend: within-cluster residual (near-arbitrage) + complex-wide.

Residuals are invariant to any invertible linear transform of the regressor set,
so orthogonalising the factors changes ``B`` (making it stable and interpretable)
without changing ``eps`` by even a rounding error.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- universe ---

FACTOR_LEGS = {
    "F_RATE":  ("IEF", None),      # rates level
    "F_SLOPE": ("TLT", "SHY"),     # curve slope
    "F_CREDIT": ("HYG", None),     # credit beta  <- the carry factor
    "F_QUAL":  ("HYG", "LQD"),     # quality
    "F_EQ":    ("SPY", None),      # equity
}
FACTOR_ORDER = ["F_RATE", "F_SLOPE", "F_CREDIT", "F_QUAL", "F_EQ"]

# clusters declared a priori by economic content (prereg §3.4) - never fitted
CLUSTERS = {
    "HY_BROAD": ["HYG", "JNK", "USHY", "SPHY"],
    "HY_SHORT": ["SHYG", "SJNK"],
    "IG_BROAD": ["LQD", "VCIT"],
    "IG_SHORT": ["VCSH", "IGSB"],
    "FALLEN":   ["ANGL", "FALN"],
    "LOANS":    ["BKLN", "SRLN"],
}

# instruments we are willing to hold. factor legs double as tradeables where
# they are also credit instruments (HYG, LQD); pure rates/equity legs do not trade.
TRADEABLE = [
    "HYG", "JNK", "USHY", "SPHY", "SHYG", "SJNK", "HYGH",
    "ANGL", "FALN",
    "LQD", "VCSH", "VCIT", "VCLT", "IGSB", "LQDH",
    "BKLN", "SRLN", "JAAA", "JBBB",
    "EMB", "PFF", "CWB",
]


@dataclass
class SignalConfig:
    """Frozen per CREDIT_RV_PREREG.md §4."""
    w_beta: int = 120          # beta estimation window
    w_resid: int = 60          # residual / OU window
    theta: float = 0.60        # cluster vs complex blend
    # Amendment 1: the edge is absent below |s|=2.0 and large above it, as a wide
    # AP-arbitrage band predicts. 1.25 is Avellaneda-Lee's EQUITY value.
    s_entry: float = 2.00
    s_exit: float = 0.50
    s_stop: float = 3.50
    max_halflife: float = 10.0
    min_ar_r2: float = 0.05
    min_adv_usd: float = 5e6
    shrink_beta: float = 0.25  # toward cluster-mean beta
    tradeable: list[str] = field(default_factory=lambda: list(TRADEABLE))


# ------------------------------------------------------------------ helpers ---

def build_factors(rx: pd.DataFrame) -> pd.DataFrame:
    """Factor excess-return matrix from tradeable legs."""
    out = {}
    for name in FACTOR_ORDER:
        lo, hi = FACTOR_LEGS[name]
        out[name] = rx[lo] - rx[hi] if hi else rx[lo]
    return pd.DataFrame(out, index=rx.index)[FACTOR_ORDER]


def excess_returns(returns: pd.DataFrame, rf_daily: pd.Series) -> pd.DataFrame:
    rf = rf_daily.reindex(returns.index).ffill().fillna(0.0)
    return returns.sub(rf, axis=0)


def _ar1_ou(X: np.ndarray) -> tuple[np.ndarray, ...]:
    """Vectorised AR(1) fit on the columns of X (T x N cumulative residual paths).

    Returns (kappa, m, sigma_eq, r2, b) with kappa in per-year units.
    """
    y = X[1:, :]
    x = X[:-1, :]
    n = x.shape[0]
    valid = np.isfinite(x).all(axis=0) & np.isfinite(y).all(axis=0)

    xm = np.where(valid, x.mean(axis=0), np.nan)
    ym = np.where(valid, y.mean(axis=0), np.nan)
    xc, yc = x - xm, y - ym
    sxx = (xc * xc).sum(axis=0)
    sxy = (xc * yc).sum(axis=0)

    with np.errstate(divide="ignore", invalid="ignore"):
        b = np.where(sxx > 1e-18, sxy / sxx, np.nan)
        a = ym - b * xm
        resid = yc - b * xc
        sse = (resid * resid).sum(axis=0)
        sst = (yc * yc).sum(axis=0)
        r2 = np.where(sst > 1e-18, 1.0 - sse / sst, np.nan)

        # OU parameters; only b in (0,1) is a mean-reverting fit
        ok = np.isfinite(b) & (b > 1e-6) & (b < 1.0 - 1e-9)
        kappa = np.where(ok, -np.log(np.where(ok, b, 0.5)) * 252.0, np.nan)
        m = np.where(ok, a / (1.0 - np.where(ok, b, 0.5)), np.nan)
        var_z = np.where(n > 2, sse / max(n - 2, 1), np.nan)
        sigma_eq = np.where(ok, np.sqrt(var_z / (1.0 - np.where(ok, b, 0.5) ** 2)), np.nan)

    return kappa, m, sigma_eq, r2, b


# --------------------------------------------------------------- main build ---

def compute_signals(
    returns: pd.DataFrame,
    rf_daily: pd.Series,
    dollar_volume: pd.DataFrame,
    cfg: SignalConfig,
) -> dict[str, pd.DataFrame]:
    """Full s-score panel.

    Returns dict of DataFrames indexed by date, columns = tradeable tickers:
      s_complex, s_cluster, s_blend, halflife, ar_r2, tradeable_mask
    plus 'betas' as a dict[date] -> DataFrame(N x K).
    """
    rx = excess_returns(returns, rf_daily)
    F = build_factors(rx)

    names = [t for t in cfg.tradeable if t in rx.columns]
    R = rx[names]

    dates = rx.index
    K = len(FACTOR_ORDER)
    start = cfg.w_beta + cfg.w_resid

    idx, cols = dates[start:], names
    s_complex = pd.DataFrame(np.nan, index=idx, columns=cols)
    s_cluster = pd.DataFrame(np.nan, index=idx, columns=cols)
    halflife = pd.DataFrame(np.nan, index=idx, columns=cols)
    ar_r2 = pd.DataFrame(np.nan, index=idx, columns=cols)
    sigma_eq = pd.DataFrame(np.nan, index=idx, columns=cols)
    kappa_p = pd.DataFrame(np.nan, index=idx, columns=cols)
    beta_store: dict[pd.Timestamp, pd.DataFrame] = {}

    Fv, Rv = F.values, R.values
    ticker_pos = {t: i for i, t in enumerate(cols)}
    cluster_idx = {c: [ticker_pos[t] for t in ts if t in ticker_pos]
                   for c, ts in CLUSTERS.items()}

    ridge = 1e-8
    for n, ti in enumerate(range(start, len(dates))):
        b0, b1 = ti - cfg.w_beta + 1, ti + 1          # beta window (inclusive of t)
        r0 = ti - cfg.w_resid + 1                      # residual sub-window

        Fw_raw = Fv[b0:b1]
        Rw_raw = Rv[b0:b1]
        good = np.isfinite(Fw_raw).all(axis=1)
        if good.sum() < cfg.w_beta * 0.8:
            continue

        # Betas in the RAW factor basis. Centring both sides is equivalent to
        # fitting an intercept, which strips in-window drift - i.e. carry - from
        # the residual. Ridge only conditions the 5x5 solve; it does not shrink
        # economically (lambda is 1e-8 against factor variances of ~1e-4).
        Fw = Fw_raw[good]
        Rw = Rw_raw[good]
        f_mu = Fw.mean(axis=0)
        Fc = Fw - f_mu
        G = Fc.T @ Fc + ridge * np.eye(K)

        avail = np.isfinite(Rw).all(axis=0)
        B = np.full((len(cols), K), np.nan)
        if avail.any():
            Rc = Rw[:, avail] - Rw[:, avail].mean(axis=0)
            B[avail] = np.linalg.solve(G, Fc.T @ Rc).T

        # shrink each beta toward its cluster-mean beta (estimation-noise control)
        Bs = B.copy()
        for _, members in cluster_idx.items():
            mem = [i for i in members if avail[i]]
            if len(mem) >= 2:
                cm = np.nanmean(B[mem], axis=0)
                Bs[mem] = (1 - cfg.shrink_beta) * B[mem] + cfg.shrink_beta * cm

        # Residuals over the shorter window, SAME (raw, centred) basis as the fit.
        Fr = Fv[r0:ti + 1] - f_mu
        Rr = Rv[r0:ti + 1]
        r_mu = np.nanmean(Rv[b0:b1], axis=0)           # window mean, PIT-safe
        eps = (Rr - r_mu) - Fr @ Bs.T                  # (w_resid x N)
        X = np.nancumsum(np.where(np.isfinite(eps), eps, 0.0), axis=0)
        X[~np.isfinite(eps)] = np.nan

        kappa, m, sig_eq, r2, _ = _ar1_ou(X)
        with np.errstate(divide="ignore", invalid="ignore"):
            s = (X[-1, :] - m) / sig_eq
            hl = np.log(2.0) / kappa * 252.0           # trading days

        d = dates[ti]
        s_complex.iloc[n] = s
        halflife.iloc[n] = hl
        ar_r2.iloc[n] = r2
        sigma_eq.iloc[n] = sig_eq
        kappa_p.iloc[n] = kappa
        beta_store[d] = pd.DataFrame(Bs, index=cols, columns=FACTOR_ORDER)

        # ---- level 2: within-cluster residual (the near-arbitrage) ----
        sc = np.full(len(cols), np.nan)
        for _, members in cluster_idx.items():
            mem = [i for i in members if avail[i]]
            if len(mem) < 2:
                continue
            Rm = Rr[:, mem]
            demeaned = Rm - np.nanmean(Rm, axis=1, keepdims=True)
            Xc = np.nancumsum(demeaned, axis=0)
            kap_c, m_c, sig_c, r2_c, _ = _ar1_ou(Xc)
            with np.errstate(divide="ignore", invalid="ignore"):
                sc_vals = (Xc[-1, :] - m_c) / sig_c
                hl_c = np.log(2.0) / kap_c * 252.0
            bad = ~np.isfinite(hl_c) | (hl_c > cfg.max_halflife) | (r2_c < cfg.min_ar_r2)
            sc_vals = np.where(bad, np.nan, sc_vals)
            sc[mem] = sc_vals
            # where the cluster residual is the sharper signal, its OU params
            # are the ones that price the trade
            ok_c = ~bad
            for pos, mi in enumerate(mem):
                if ok_c[pos]:
                    sigma_eq.iloc[n, mi] = sig_c[pos]
                    kappa_p.iloc[n, mi] = kap_c[pos]
        s_cluster.iloc[n] = sc

    # blend; cluster term drops out where absent
    sc_f = s_cluster.fillna(0.0)
    has_c = s_cluster.notna()
    w_c = cfg.theta * has_c
    s_blend = w_c * sc_f + (1.0 - w_c) * s_complex

    adv = dollar_volume.reindex(index=idx, columns=cols)
    liquid = adv.rolling(21, min_periods=10).median() >= cfg.min_adv_usd
    revert = (halflife > 0) & (halflife <= cfg.max_halflife) & (ar_r2 >= cfg.min_ar_r2)
    mask = liquid & revert & s_blend.notna()

    return {
        "sigma_eq": sigma_eq,
        "kappa": kappa_p,
        "s_complex": s_complex,
        "s_cluster": s_cluster,
        "s_blend": s_blend,
        "halflife": halflife,
        "ar_r2": ar_r2,
        "tradeable_mask": mask,
        "betas": beta_store,
        "factors": F,
        "excess_returns": rx,
    }
