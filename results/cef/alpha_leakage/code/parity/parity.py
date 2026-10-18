"""Read-only: harness book vs a sleeve-faithful replica, built on band_frontier's targets."""
import sys; R='/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027'; sys.path.insert(0,R)
import numpy as np, pandas as pd
from scripts.cef import band_frontier as bf
from scripts.cef.spec import MIN_ADV_USD, MIN_NAMES, BAND_WIDTH, MAX_GROSS_STRESS, MIN_ABS_WEIGHT
T, Rp = bf.build_targets()
Rt = bf.total_returns(Rp)
p = bf.build_panel()
z, adv = p['z'].reindex(T.index), p['adv'].reindex(T.index)
elig = (z.notna() & (adv >= MIN_ADV_USD)).reindex(columns=T.columns, fill_value=False).sum(axis=1)
short = (elig < MIN_NAMES).values
b, cap, minw = BAND_WIDTH, MAX_GROSS_STRESS, MIN_ABS_WEIGHT

def minweight(row):
    s = row[row != 0]
    if s.empty: return row
    scal = s.abs().sum()
    keep = s[s.abs() >= minw]
    if len(keep) >= MIN_NAMES:
        keep = keep - keep.mean(); keep = keep / keep.abs().sum() * scal
        return keep.reindex(row.index).fillna(0.0)
    return row
def sim(liquidate=False, defer=False, mw=False, dust=False):
    A = T.apply(minweight, axis=1).values if mw else T.values
    cur = np.zeros(T.shape[1]); H = np.zeros_like(A)
    for i in range(len(A)):
        if liquidate and short[i]:
            cur = np.zeros_like(cur); H[i] = cur; continue
        gap = A[i] - cur; mv = np.abs(gap) > b
        new = cur.copy(); new[mv] = A[i][mv] - np.sign(gap[mv]) * b
        g = np.abs(new).sum(); traded = mv.copy()
        if g > cap: new = new * cap / g; traded[:] = True
        if dust: new[traded & (np.abs(new) < minw)] = 0.0
        if defer: new[(cur * new) < 0] = 0.0
        cur = new; H[i] = cur
    return pd.DataFrame(H, index=T.index, columns=T.columns)
def st(H, a, e=None):
    r = bf.evaluate(H.loc[a:e], Rt.loc[a:e])
    return f"SR {r['gross_sr']:5.2f} ann {r['ann_ret']*100:5.2f}% turn {r['turn']:5.1f}"
books = {"harness band+cap": sim(),
         "+liquidate on <min_names": sim(liquidate=True),
         "+deferred flips": sim(defer=True),
         "+min_abs_weight renorm+dust": sim(mw=True, dust=True),
         "all sleeve divergences": sim(liquidate=True, defer=True, mw=True, dust=True)}
print("panel end", T.index[-1].date(), "| days <min_names in 2013-06-14..:", int(short[T.index >= '2013-06-14'].sum()))
for k, H in books.items():
    print(f"{k:<30} traded-era {st(H,'2013-06-14')} | 2015-19 {st(H,'2015','2019')} | 2020-22 {st(H,'2020','2022')} | 2023+ {st(H,'2023')}")
H0 = books["harness band+cap"]; Hd = books["+deferred flips"]
fl = ((H0.shift(1) * H0) < 0).sum().sum(); print("sign flips in harness book (traded era+):", int(fl), "over", len(H0.loc['2013-06-14':]), "days")
s = pd.Series(short, index=T.index)
print(s.groupby(T.index.year).sum().loc[2013:].to_dict())
HL = books["+liquidate on <min_names"]
for y in (2017, 2019, 2023):
    m = s.loc[str(y)]
    print(y, 'short days', int(m.sum()), 'harness gross on them', round(H0.loc[str(y)][m].abs().sum(axis=1).mean(),3),
          'live gross', round(HL.loc[str(y)][m].abs().sum(axis=1).mean(),3), 'harness gross all days', round(H0.loc[str(y)].abs().sum(axis=1).mean(),3))
# 2023 short-day dates
print(s.loc['2023'][s.loc['2023']].index.min(), s.loc['2023'][s.loc['2023']].index.max())
# DRIFT: live holds shares sized at the as-of close and filled one session later; the
# harness holds constant weights. H_eff[i] = weight at close i+1 of the shares decided at i.
def sim_drift():
    A, Rv = T.values, Rp.values
    cur = np.zeros(T.shape[1]); He = np.zeros_like(A); prev = np.zeros(T.shape[1])
    for i in range(len(A)):
        gap = A[i] - cur; mv = np.abs(gap) > b
        new = cur.copy(); new[mv] = A[i][mv] - np.sign(gap[mv]) * b
        g = np.abs(new).sum()
        if g > cap: new = new * cap / g
        if i + 1 < len(A):
            r = Rv[i + 1]; br = float(np.dot(prev, r))
            eff = new * (1 + r) / (1 + br)
        else:
            eff = new
        He[i] = eff; prev = eff; cur = eff
    return pd.DataFrame(He, index=T.index, columns=T.columns)
HD = sim_drift()
print(f"{'+share drift (fill t+1)':<30} traded-era {st(HD,'2013-06-14')} | 2020-22 {st(HD,'2020','2022')} | 2023+ {st(HD,'2023')}")
print('max gross drifted', round(HD.abs().sum(axis=1).max(),3), 'days >1.8x:', int((HD.abs().sum(axis=1) > cap + 1e-9).sum()))
