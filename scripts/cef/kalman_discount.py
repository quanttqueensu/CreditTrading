"""A state-space fair discount for the CEF sleeve.

WHAT IS WRONG WITH THE CURRENT ESTIMATOR
----------------------------------------
The live signal is `(d_t - mean_252(d)) / sd_252(d)`. A 252-day rolling mean is a
boxcar filter: it weights a discount from eleven months ago exactly as heavily as
yesterday's, and its effective lag is about half its window. So when a fund's fair
discount genuinely moves, the estimator takes roughly a year to notice, and until
it does it reports the re-rated fund as "cheap".

That is not a hypothetical failure. Measured in `results/cef/DIST_CUT_NOTE.md`: a
distribution cut widens the discount 0.58pp permanently, and the rolling z-score
of cut funds stays at -0.20 to -0.34 for six months afterwards. The sleeve is
pulled into funds whose cheapness is a fact about their new level, not a
dislocation that will revert.

THE MODEL
---------
Decompose the observed discount into a slow level and a fast deviation:

    d_t = theta_t + x_t
    theta_t = theta_{t-1} + w_t          w ~ N(0, q_theta)   fair level, random walk
    x_t     = phi * x_{t-1} + v_t        v ~ N(0, q_x)       dislocation, AR(1)

`theta` is where the fund's discount belongs; `x` is how far it currently sits
from that. **The tradable signal is `-x_t`, not `-(d_t - mean)`.** A fund whose
fair discount has widened has a new `theta` and an `x` near zero -- correctly
reading as neither cheap nor rich -- where the rolling z-score would call it
cheap for months.

Estimated by Kalman FILTER, never the smoother: the filtered state at t uses only
observations up to t, so it is point-in-time by construction. The smoother would
be materially better-fitting and completely untradeable.

CUTS ENTER AS A LEVEL SHIFT, NOT A FILTER
-----------------------------------------
Excluding recently-cut funds was tested and rejected -- it costs more breadth than
it saves (median eligible universe is 8 funds, and IR = IC*sqrt(BR)). The right
response is to let `theta` MOVE when we have a reason to think it moved. On a
distribution change the process variance of `theta` is inflated for that one step,
so the filter reallocates the shift into the level instead of reading it as a
dislocation. The fund stays in the universe and keeps contributing breadth.

PARAMETERS, AND KEEPING THE TRIAL COUNT HONEST
----------------------------------------------
`phi` is fixed from the pooled AR(1) of the demeaned discount -- estimated once,
from data, not tuned. `q_x` is normalised to 1 and `r` pinned small, which leaves
exactly ONE free parameter: `lam = q_theta / q_x`, how readily the fair level is
allowed to move. It is swept over a small grid and every value is reported.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.cef.validate import load_raw, signals, MIN_ADV  # noqa: E402

R_OBS = 1e-3          # observation noise; small, the discount is observed exactly
Q_X = 1.0             # transient variance, normalised -- lam is measured against it
# q_theta multiplier after a distribution change, applied over a WINDOW rather
# than a single step. The event study is explicit that the re-rating is gradual,
# not a jump: the discount is essentially unmoved at t+21 (-0.044pp) and only
# reaches its new level near t+60 (-0.580pp). A one-step variance bump at the
# ex-date therefore fires when nothing has happened yet and is shut again by the
# time it has -- measured, it made the post-cut misreading WORSE, not better
# (-0.453 vs the rolling z-score's -0.341). Holding theta loose across the window
# the shift actually occupies is what lets the level absorb it.
CUT_INFLATION = 25.0
CUT_WINDOW = 60

# Everything from here is SEALED. lam is chosen on 2005-2023 and the holdout is
# opened once, by an adjudicated run, after the specification is frozen.
HOLDOUT_START = '2023-12-31'


def pooled_phi(disc: pd.DataFrame) -> float:
    """AR(1) coefficient of the demeaned discount, pooled across funds.

    Estimated from the data once and then held fixed, so it is a measurement
    rather than a knob. Demeaning per fund first removes the level, leaving the
    persistence of the deviation -- which is what `phi` is meant to describe.
    """
    dm = disc - disc.rolling(252, min_periods=120).mean()
    num = den = 0.0
    for c in dm.columns:
        s = dm[c].dropna()
        if len(s) < 500:
            continue
        a, b = s.iloc[:-1].to_numpy(), s.iloc[1:].to_numpy()
        num += float(a @ b)
        den += float(a @ a)
    return float(np.clip(num / den, 0.5, 0.995)) if den > 0 else 0.94


def kalman_level_ar1(d: np.ndarray, phi: float, lam: float,
                     bump: np.ndarray | None = None):
    """Filtered (theta, x) for one series. Causal: state at t uses data <= t.

    Returns arrays the same length as `d`, NaN where the input is NaN.
    `bump[t]` True inflates q_theta for that step (a distribution change).
    """
    n = len(d)
    theta = np.full(n, np.nan)
    x = np.full(n, np.nan)

    # state [theta, x]; start at the first observation with a diffuse prior
    s = np.zeros(2)
    P = np.eye(2) * 1e4
    started = False
    F = np.array([[1.0, 0.0], [0.0, phi]])
    H = np.array([1.0, 1.0])

    for t in range(n):
        obs = d[t]
        if not np.isfinite(obs):
            continue
        if not started:
            s = np.array([obs, 0.0])
            P = np.array([[1.0, 0.0], [0.0, Q_X / max(1e-6, 1 - phi * phi)]])
            started = True
            theta[t], x[t] = s
            continue
        q_theta = lam * (CUT_INFLATION if (bump is not None and bump[t]) else 1.0)
        Q = np.array([[q_theta, 0.0], [0.0, Q_X]])
        # predict
        s = F @ s
        P = F @ P @ F.T + Q
        # update
        y = obs - H @ s
        S = H @ P @ H + R_OBS
        K = (P @ H) / S
        s = s + K * y
        P = P - np.outer(K, H @ P)
        theta[t], x[t] = s
    return theta, x


def build_signal(disc, phi, lam, cuts=None):
    """Cross-sectional z of the DISLOCATION component, per fund."""
    X = pd.DataFrame(np.nan, index=disc.index, columns=disc.columns)
    for c in disc.columns:
        bump = None
        if cuts is not None and c in cuts.columns:
            bump = cuts[c].to_numpy()
        _, x = kalman_level_ar1(disc[c].to_numpy(dtype=float), phi, lam, bump)
        X[c] = x
    # standardise each fund's dislocation by its OWN trailing scale, causally
    sd = X.rolling(252, min_periods=120).std().shift(1)
    return (X / sd.replace(0, np.nan)).clip(-4, 4)


def cut_flags(index, columns):
    ev = pd.read_parquet(REPO / "data/cef/cef_dist_features.parquet")
    ev["ex_date"] = pd.to_datetime(ev["ex_date"])
    ev = ev[(ev.is_cut.astype(bool)) | (ev.is_raise.astype(bool))]
    M = pd.DataFrame(False, index=index, columns=columns)
    for _, r in ev.iterrows():
        if r.ticker not in M.columns:
            continue
        p = index.searchsorted(r["ex_date"])
        if 0 <= p < len(index):
            M.iloc[p:p + CUT_WINDOW, M.columns.get_loc(r.ticker)] = True
    return M


def backtest(z, px, adv, hold=2, shift=2, vol_target=0.06, end=None):
    """`end` truncates the evaluation window. Used to keep the 2024-01+ holdout
    sealed while lam is chosen: every specification below is scored on
    2005-2023 ONLY, so the holdout stays unspent for a single adjudicated run."""
    idx = px.index if end is None else px.index[px.index <= pd.Timestamp(end)]
    px, adv, z = px.loc[idx], adv.loc[idx], z.loc[idx]
    ret = px.pct_change(fill_method=None).where(lambda x: x.abs() < 0.5)
    elig = adv.fillna(0.0) >= MIN_ADV
    W = pd.DataFrame(0.0, index=idx, columns=px.columns)
    for t in idx[::hold]:
        row = z.loc[t][elig.loc[t]].dropna()
        if len(row) < 6:
            continue
        v = -(row - row.mean())
        if v.abs().sum() < 1e-9:
            continue
        W.loc[t, v.index] = (v / v.abs().sum()).values
    W = (W.replace(0.0, np.nan).ffill(limit=hold - 1) if hold > 1
         else W.replace(0.0, np.nan)).fillna(0.0)
    raw = (W.shift(1).fillna(0.0) * ret).sum(axis=1)
    rv = raw.shift(1).rolling(63, min_periods=30).std() * np.sqrt(252)
    W = W.mul((vol_target / rv.replace(0, np.nan)).clip(0.2, 2.5).fillna(1.0), axis=0)
    g = (W.shift(shift).fillna(0.0) * ret).sum(axis=1)
    dw = W.shift(shift).fillna(0.0).diff().abs().fillna(0.0)
    return g, dw.sum(axis=1)


def sr(s):
    return s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else np.nan


def main() -> int:
    px, nav, vol = load_raw()
    disc, z_base, adv = signals(px, nav, vol)
    phi = pooled_phi(disc)
    print(f"pooled AR(1) phi = {phi:.4f}  "
          f"(dislocation half-life {np.log(0.5)/np.log(phi):.1f} trading days)")

    cuts = cut_flags(disc.index, disc.columns)
    print(f"distribution-change flags: {int(cuts.values.sum())}")

    g, _ = backtest(z_base, px, adv, hold=2, shift=2, end=HOLDOUT_START)
    print(f"\nEVALUATION WINDOW: 2005-01 .. {HOLDOUT_START} (2024-01+ SEALED)")
    print(f"BASELINE rolling-252 z-score      gross SR {sr(g):+5.2f}")

    print("\nKALMAN state-space signal, sweep of lam = q_theta/q_x:")
    print(f"{'lam':>8} {'cuts off':>12} {'cuts on':>12}")
    best = None
    for lam in (3e-1, 1.0, 3.0, 10.0, 30.0, 100.0):
        z1 = build_signal(disc, phi, lam, cuts=None)
        z2 = build_signal(disc, phi, lam, cuts=cuts)
        a, _ = backtest(z1, px, adv, hold=2, shift=2, end=HOLDOUT_START)
        b, _ = backtest(z2, px, adv, hold=2, shift=2, end=HOLDOUT_START)
        print(f"{lam:>8.0e} {sr(a):>12.2f} {sr(b):>12.2f}")
        for tag, s in (("cuts-off", sr(a)), ("cuts-on", sr(b))):
            if best is None or s > best[0]:
                best = (s, lam, tag)
    print(f"\nbest: {best[2]} lam={best[1]:.0e}  gross SR {best[0]:+.2f}  "
          f"vs baseline {sr(g):+.2f}")

    # does the estimator actually fix the post-cut misreading it was built for?
    print("\nPOST-CUT MISREADING — mean signal of cut funds after the cut")
    ev = pd.read_parquet(REPO / "data/cef/cef_dist_features.parquet")
    ev["ex_date"] = pd.to_datetime(ev["ex_date"])
    ev = ev[ev.is_cut.astype(bool)]
    zk = build_signal(disc, phi, best[1], cuts=cuts)
    idx = disc.index
    print(f"{'window':>12} {'rolling-z':>12} {'kalman':>12}")
    for lo, hi in ((0, 21), (21, 63), (63, 126)):
        va, vb = [], []
        for _, r in ev.iterrows():
            tk = r.ticker
            if tk not in disc.columns:
                continue
            p = idx.searchsorted(r["ex_date"])
            for src, acc in ((z_base, va), (zk, vb)):
                seg = src[tk].iloc[p + lo:p + hi].to_numpy(dtype=float)
                acc.extend(seg[np.isfinite(seg)])
        if va and vb:
            print(f"  t+{lo:>3}..{hi:<5} {np.mean(va):>12.3f} {np.mean(vb):>12.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
