import sys, numpy as np, pandas as pd
sys.path.insert(0,'/Users/simonjarvis/Desktop/QUANTT/2027')
from scripts.cef.validate import load_raw, signals, MIN_ADV
from src.strategies.credit_rv.costs import SCENARIOS
CM=SCENARIOS['base']
px,nav,vol=load_raw(); disc,z,adv=signals(px,nav,vol)
idx=px.index[px.index>='2005-01-01']
zz,pp,aa=z.reindex(idx),px.reindex(idx),adv.reindex(idx)
ret=pp.pct_change(fill_method=None).where(lambda x:x.abs()<0.5)
elig=aa.fillna(0.0)>=MIN_ADV
hs=pd.DataFrame({c:[CM.half_spread_bp(p,a) for p,a in zip(pp[c].values,aa[c].fillna(0).values)]
                 for c in pp.columns},index=idx)

def run(hold,shift):
    W=pd.DataFrame(0.0,index=idx,columns=pp.columns)
    for t in idx[::hold]:
        row=zz.loc[t][elig.loc[t]].dropna()
        if len(row)<6: continue
        v=-(row-row.mean())
        if v.abs().sum()<1e-9: continue
        W.loc[t,v.index]=(v/v.abs().sum()).values
    W=(W.replace(0.0,np.nan).ffill(limit=hold-1) if hold>1 else W.replace(0.0,np.nan)).fillna(0.0)
    raw=(W.shift(1).fillna(0.0)*ret).sum(axis=1)
    rv=raw.shift(1).rolling(63,min_periods=30).std()*np.sqrt(252)
    W=W.mul((0.06/rv.replace(0,np.nan)).clip(0.2,2.5).fillna(1.0),axis=0)
    held=W.shift(shift).fillna(0.0)
    g=(held*ret).sum(axis=1)
    dw=held.diff().abs().fillna(held.abs())
    cost=(dw*hs/1e4).sum(axis=1)
    n=(g-cost).dropna()
    return g.mean()/g.std()*np.sqrt(252), n.mean()/n.std()*np.sqrt(252), dw.sum(axis=1).mean()*252

print("="*86)
print("G. NET-OF-COST FRONTIER — gross SR / net SR / turnover-per-year")
print("="*86)
print(f"{'hold':>5} | {'shift=1 (backtest)':>32} | {'shift=2 (what MOC gets)':>32}")
print(f"{'':>5} | {'gross':>8}{'net':>10}{'turn/yr':>12} | {'gross':>8}{'net':>10}{'turn/yr':>12}")
best=None
for hold in (1,2,3,5,8,10,15,21):
    a=run(hold,1); b=run(hold,2)
    print(f"{hold:>5} | {a[0]:>8.2f}{a[1]:>10.2f}{a[2]:>12.1f} | {b[0]:>8.2f}{b[1]:>10.2f}{b[2]:>12.1f}")
    if best is None or b[1]>best[1]: best=(hold,b[1],b[0],b[2])
print(f"\n  OPTIMAL under the execution we actually have (shift=2): hold={best[0]}d, net SR {best[1]:.2f}")
print(f"  LIVE CONFIG IS hold=5d  ->  net SR {run(5,2)[1]:.2f}")

print("\n"+"="*86); print("H. SIGNAL DECAY — information half-life"); print("="*86)
ic=[]
for h in (1,2,3,5,8,10,15,21,42):
    fwd=pp.shift(-h)/pp-1.0
    x=(-zz).where(elig); y=fwd
    d=pd.concat([x.stack().rename('x'),y.stack().rename('y')],axis=1).dropna()
    c=d.x.corr(d.y); ic.append((h,c,len(d)))
    print(f"  horizon {h:>2}d   IC {c:+.4f}   n={len(d):,}")
hh=np.array([r[0] for r in ic]); cc=np.array([r[1] for r in ic])
per=cc/np.sqrt(hh)                      # IC per unit sqrt-time = decay-adjusted
k=np.polyfit(hh, np.log(np.maximum(per,1e-6)),1)[0]
print(f"\n  IC/sqrt(h) decays at {k:+.4f}/day  ->  information half-life "
      f"{np.log(2)/abs(k):.1f} trading days" if k<0 else f"\n  no decay detected (k={k:+.4f})")
