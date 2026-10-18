"""Sensitivity of OUR CODE to a stale NAV(D-1) at decide time (synthetic corruption, seeded).
Not a claim about the market: the corruption pattern is the one LIVE_NAV_QUALITY_2026-10-12 §5 measured."""
import sys; R='/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027'; sys.path.insert(0,R)
import numpy as np, pandas as pd
from scripts.cef import band_frontier as bf
from scripts.cef.spec import MIN_ADV_USD, MIN_NAMES, BAND_WIDTH, MAX_GROSS_STRESS, VOL_TARGET, UNIVERSE as U
p = bf.build_panel(); px, nav, ret, mu, sd, adv = p['px'], p['nav'], p['ret'], p['mu'], p['sd'], p['adv']
z_clean = p['z']
nav_prev = nav.shift(1)
z_stale = ((100*(px-nav_prev)/nav_prev - mu) / sd.replace(0, np.nan)).clip(-4, 4)
PIMCO = ['PCN','PDI','PDO','PFN','PHK','PTY']
def targets(mask):
    z = z_clean.where(~mask, z_stale)
    tgt = pd.DataFrame(0.0, index=z.index, columns=U)
    start = z.index.searchsorted(pd.Timestamp(bf.SAMPLE_START))
    for i in range(start, len(z.index)):
        row = z.iloc[i].dropna()
        row = row[[t for t in row.index if (adv.iloc[i].get(t, 0) or 0) >= MIN_ADV_USD]]
        if len(row) < MIN_NAMES: tgt.iloc[i] = tgt.iloc[i-1]; continue
        w = -(row - row.mean()); w = w / w.abs().sum()
        hist = ret[list(row.index)].iloc[:i+1].mul(w, axis=1).sum(axis=1).tail(bf.VOL_LOOKBACK)
        rv = hist.std()*np.sqrt(252); scal = float(np.clip(VOL_TARGET/rv, 0.2, 2.5)) if rv > 0 else 1.0
        tgt.iloc[i] = (w*scal).reindex(U).fillna(0.0).values
    return tgt.iloc[start:]
T0, Rp = bf.build_targets(); Rt = bf.total_returns(Rp)
rng = np.random.default_rng(20261013)
masks = {"clean (harness)": pd.DataFrame(False, index=z_clean.index, columns=z_clean.columns),
         "38% name-days stale, random": pd.DataFrame(rng.random(z_clean.shape) < 0.38, index=z_clean.index, columns=z_clean.columns),
         "PIMCO 6 stale every day": pd.DataFrame(False, index=z_clean.index, columns=z_clean.columns).assign(**{c: True for c in PIMCO if c in z_clean.columns})}
for k, m in masks.items():
    T = targets(m); assert k != "clean (harness)" or np.allclose(T.values, T0.values)
    H = bf.band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)
    out = []
    for a, e in (('2013-06-14', None), ('2020', '2022'), ('2023', None)):
        r = bf.evaluate(H.loc[a:e], Rt.loc[a:e]); out.append(f"SR {r['gross_sr']:5.2f} ann {r['ann_ret']*100:5.2f}% turn {r['turn']:5.1f}")
    print(f"{k:<30} traded-era {out[0]} | 2020-22 {out[1]} | 2023+ {out[2]}")
