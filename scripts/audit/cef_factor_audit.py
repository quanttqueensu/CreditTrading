import sys, numpy as np, pandas as pd
sys.path.insert(0,'/Users/simonjarvis/Desktop/QUANTT/2027')
from scripts.cef.validate import load_raw, signals, run, WIN, HOLD, MIN_ADV

px, nav, vol = load_raw()
disc, z, adv = signals(px, nav, vol)
uni = pd.read_csv('data/cef/cef_universe.csv').set_index('ticker')['grp']

# ---- rebuild the weights exactly as validate.run does, but KEEP them ----
start='2005-01-01'
idx = px.index[px.index>=start]
zz,pp,aa = z.reindex(idx), px.reindex(idx), adv.reindex(idx)
ret = pp.pct_change(fill_method=None).where(lambda x: x.abs()<0.5)
elig = aa.fillna(0.0)>=MIN_ADV
W = pd.DataFrame(0.0, index=idx, columns=pp.columns)
for t in idx[::HOLD]:
    row = zz.loc[t][elig.loc[t]].dropna()
    if len(row)<6: continue
    v = -(row-row.mean())
    if v.abs().sum()<1e-9: continue
    W.loc[t, v.index] = (v/v.abs().sum()).values
W = W.replace(0.0,np.nan).ffill(limit=HOLD-1).fillna(0.0)
raw=(W.shift(1).fillna(0.0)*ret).sum(axis=1)
rv=raw.shift(1).rolling(63,min_periods=30).std()*np.sqrt(252)
W=W.mul((0.06/rv.replace(0,np.nan)).clip(0.2,2.5).fillna(1.0),axis=0)
held=W.shift(1).fillna(0.0)

# ---- GROUP EXPOSURE: is this a muni-vs-taxable bet? ----
grp = pd.Series({c: uni.get(c,'?') for c in held.columns})
print("="*78); print("A. NET GROUP EXPOSURE OF THE 'DOLLAR-NEUTRAL' BOOK"); print("="*78)
expo = {}
for g in sorted(set(grp.values)):
    cols=[c for c in held.columns if grp[c]==g]
    expo[g]=held[cols].sum(axis=1)
E=pd.DataFrame(expo)
print("mean net weight by group (positive = net long that group):")
print((E.mean()*100).round(2).to_string())
print(f"\nmean |net muni| exposure       : {E['muni'].abs().mean()*100:.2f}% of gross")
print(f"corr(net muni expo, sleeve ret) : {E['muni'].shift(1).corr(raw):.3f}")
print("\nlast 5 sessions, net exposure by group (%):")
print((E.tail(5)*100).round(2).to_string())

# ---- FACTOR REGRESSION: baseline vs muni-augmented ----
print("\n"+"="*78); print("B. FACTOR REGRESSION — DOES ALPHA SURVIVE A MUNI FACTOR?"); print("="*78)
ext = pd.read_parquet('data/rv/etf_ohlc_extended.parquet')
if 'ticker' in ext.columns:
    ext = ext.pivot_table(index='date',columns='ticker',values='close')
ext.index = pd.to_datetime(ext.index)
rw = pd.read_parquet('data/rv/returns_wide.parquet'); rw.index=pd.to_datetime(rw.index)
fret = ext.pct_change(fill_method=None)
for c in ('LQD','HYG','SPY','IEF','TLT'):
    if c not in fret.columns and c in rw.columns: fret[c]=rw[c]
print('factor cols available:', [c for c in ('HYG','LQD','IEF','SPY','TLT','MUB','HYD') if c in fret.columns])

net = (held*ret).sum(axis=1) - 0.0   # gross; costs are tiny and factor-neutral
y = net.copy(); y.index=pd.to_datetime(y.index)

def ols(y, X, label):
    d = pd.concat([y.rename('y'), X], axis=1).dropna()
    if len(d)<250: print(f"  {label}: too few obs ({len(d)})"); return
    Y=d['y'].values; A=np.column_stack([np.ones(len(d))]+[d[c].values for c in X.columns])
    b,*_ = np.linalg.lstsq(A,Y,rcond=None)
    res = Y - A@b; dof=len(d)-A.shape[1]
    s2 = res@res/dof; cov = s2*np.linalg.pinv(A.T@A); se=np.sqrt(np.diag(cov))
    tt = b/se
    r2 = 1 - (res@res)/(((Y-Y.mean())**2).sum())
    print(f"\n  [{label}]  n={len(d)}  R2={r2:.4f}")
    print(f"    alpha  {b[0]*252*100:+7.2f}%/yr   t={tt[0]:+5.2f}")
    for i,c in enumerate(X.columns,1):
        flag = "  <-- BREACH" if abs(b[i])>0.10 else ""
        print(f"    {c:9s} beta {b[i]:+7.3f}   t={tt[i]:+5.2f}{flag}")
    return b[0]*252*100, tt[0]

base = fret[['HYG','LQD','IEF','SPY']].rename(columns={'HYG':'HY','LQD':'IG','IEF':'RATES','SPY':'EQ'})
a1 = ols(y, base, "BASELINE — the 5-factor set Test 7 used")
aug  = base.join(fret[['MUB']].rename(columns={'MUB':'MUNI'}))
a2 = ols(y, aug,  "AUGMENTED — same, plus MUB (investment-grade muni)")
aug2 = aug.join(fret[['HYD']].rename(columns={'HYD':'MUNI_HY'}))
a3 = ols(y, aug2, "AUGMENTED — plus MUB and HYD (high-yield muni)")
aug3 = aug2.join((fret['TLT']-fret['IEF']).rename('DURATION'))
a4 = ols(y, aug3, "AUGMENTED — plus MUB, HYD and a duration spread (TLT-IEF)")

print("\n"+"="*78); print("C. ALPHA DECAY AS FACTORS ARE ADDED"); print("="*78)
for lbl,a in [("HY/IG/rates/equity only",a1),("+ MUB",a2),("+ MUB,HYD",a3),("+ MUB,HYD,duration",a4)]:
    if a: print(f"  {lbl:28s} alpha {a[0]:+6.2f}%/yr  t {a[1]:+5.2f}")
