import sys, numpy as np, pandas as pd
sys.path.insert(0,'/Users/simonjarvis/Desktop/QUANTT/2027')
from scripts.cef.validate import load_raw, signals, MIN_ADV, HOLD
px,nav,vol = load_raw(); disc,z,adv = signals(px,nav,vol)
uni = pd.read_csv('data/cef/cef_universe.csv').set_index('ticker')['grp']

def build(shift_days=1, hold=HOLD, start='2005-01-01'):
    idx=px.index[px.index>=start]
    zz,pp,aa=z.reindex(idx),px.reindex(idx),adv.reindex(idx)
    ret=pp.pct_change(fill_method=None).where(lambda x:x.abs()<0.5)
    elig=aa.fillna(0.0)>=MIN_ADV
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
    held=W.shift(shift_days).fillna(0.0)
    return held,(held*ret).sum(axis=1),ret

def SR(s): return s.mean()/s.std()*np.sqrt(252)
def ols(y,X,label):
    d=pd.concat([y.rename('y'),X],axis=1).dropna()
    Y=d['y'].values; A=np.column_stack([np.ones(len(d))]+[d[c].values for c in X.columns])
    b,*_=np.linalg.lstsq(A,Y,rcond=None); res=Y-A@b; dof=len(d)-A.shape[1]
    cov=(res@res/dof)*np.linalg.pinv(A.T@A); se=np.sqrt(np.diag(cov)); tt=b/se
    r2=1-(res@res)/(((Y-Y.mean())**2).sum())
    print(f"\n  [{label}] n={len(d)} R2={r2:.4f}")
    print(f"    alpha {b[0]*252*100:+7.2f}%/yr  t={tt[0]:+5.2f}")
    for i,c in enumerate(X.columns,1):
        print(f"    {c:12s} beta {b[i]:+7.3f}  t={tt[i]:+5.2f}")

held,g1,ret = build(1)
print("="*78); print("D. THE RIGHT CONTROL: CEF SECTOR FACTORS, NOT ETF PROXIES"); print("="*78)
gf={}
for grp in ['muni','multi','hy','loan','emd']:
    cols=[c for c in ret.columns if uni.get(c)==grp]
    gf[grp]=ret[cols].mean(axis=1)
GF=pd.DataFrame(gf)
GF['CEF_MKT']=ret.mean(axis=1)
GF['TAXABLE_minus_MUNI']=ret[[c for c in ret.columns if uni.get(c) in('multi','hy','loan','emd')]].mean(axis=1)-GF['muni']
ols(g1, GF[['CEF_MKT']],                       "CEF market factor only")
ols(g1, GF[['CEF_MKT','TAXABLE_minus_MUNI']],  "CEF market + taxable-minus-muni spread")
ols(g1, GF[['muni','multi','hy','loan','emd']],"all five CEF group factors")

print("\n"+"="*78); print("E. THE ONE-DAY LAG — MOC FILLS AT close(t+1), BACKTEST ASSUMED close(t)"); print("="*78)
for sd in (1,2,3):
    h,g,_=build(sd)
    print(f"  held = W.shift({sd})   gross SR {SR(g):+5.2f}   CAGR {100*((1+g).cumprod().iloc[-1]**(252/len(g))-1):+5.2f}%")
print("  shift(1) = what validate.py measured; shift(2) = what an MOC actually gets.")

print("\n"+"="*78); print("F. DECAY PROFILE OF THE SIGNAL (how fast does the edge die?)"); print("="*78)
for hold in (1,5,10,21):
    h,g,_=build(1,hold=hold)
    h2,g2,_=build(2,hold=hold)
    print(f"  hold {hold:>2}d:  shift1 SR {SR(g):+5.2f}   shift2 SR {SR(g2):+5.2f}   decay {100*(SR(g2)/SR(g)-1):+6.1f}%")
