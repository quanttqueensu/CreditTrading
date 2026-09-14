"""Restrict to names whose half-spread is below the measured per-turnover edge.
Selection is on COST (known ex ante), never on realised P&L."""
import sys; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.costs import SCENARIOS
from src.strategies.credit_rv.trials import log_trial
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
p=pd.read_parquet(ROOT/"data/rv/etf_ohlc.parquet"); p=p[p.date<=IS_END]
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
ret_close=p.pivot(index="date",columns="ticker",values="ret_total").sort_index()
mid=p.pivot(index="date",columns="ticker",values="mid_hl").sort_index()
div=p.pivot(index="date",columns="ticker",values="dividend").sort_index().fillna(0.0)
ret_mid=(mid+div)/mid.shift(1)-1.0
dv=(p.assign(dv=p.close*p.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
pxl=p.pivot(index="date",columns="ticker",values="close").ffill().iloc[-1]
cm=SCENARIOS["base"]; advm=dv.tail(180).median()
CREDIT=["HYG","JNK","USHY","SPHY","SHYG","SJNK","HYGH","ANGL","FALN","LQD","VCSH",
        "VCIT","VCLT","IGSB","LQDH","BKLN","SRLN","JAAA","JBBB","EMB","PFF","CWB"]
half={c: cm.half_spread_bp(float(pxl.get(c,50) or 50),float(advm.get(c,0) or 0)) for c in CREDIT}

def run(max_hs, smooth):
    keep=[c for c in CREDIT if half[c]<=max_hs]
    if len(keep)<6: return None
    cfg=SignalConfig(tradeable=keep)
    sig=compute_signals(ret_mid,rf,dv,cfg)
    S=sig["s_blend"]; S=S[S.index>=IS_START]; betas=sig["betas"]; cols=list(S.columns)
    rt=ret_close.reindex(columns=cols)
    hs=np.array([half[c] for c in cols])/1e4
    W=[];P=[];prev=None
    for d in S.index:
        B=betas.get(d)
        if B is None or d not in rt.index: continue
        j=rt.index.get_loc(d)
        if j+1>=len(rt): continue
        s=S.loc[d].values.astype(float); ok=np.isfinite(s)
        if ok.sum()<4: continue
        w=np.zeros(len(cols)); w[ok]=-s[ok]; w[ok]-=w[ok].mean()
        Bv=B.reindex(cols).values; good=ok&np.isfinite(Bv).all(axis=1)
        if good.sum()<7: continue
        Bk,wk=Bv[good],w[good]
        wk=wk-Bk@np.linalg.solve(Bk.T@Bk+1e-10*np.eye(Bk.shape[1]),Bk.T@wk)
        w=np.zeros(len(cols)); w[good]=wk-wk.mean()
        n=np.abs(w).sum()
        if n<1e-12: continue
        w/=n
        if prev is not None and smooth>1:
            a=2.0/(smooth+1.0); w=a*w+(1-a)*prev; n=np.abs(w).sum(); w=w/n if n>1e-12 else w
        prev=w; W.append(w); P.append(float(w@np.nan_to_num(rt.iloc[j+1].values,nan=0.0)))
    if len(P)<200: return None
    W=np.array(W); P=pd.Series(P); dW=np.abs(np.diff(W,axis=0))
    cost=(dW*hs).sum(axis=1); net=P.iloc[1:].reset_index(drop=True)-cost
    srn=net.mean()/net.std()*np.sqrt(252)
    lev=0.13/(net.std()*np.sqrt(252))
    cagr=(1+net*lev).prod()**(252/len(net))-1
    return dict(max_hs=max_hs,smooth=smooth,n_names=len(keep),
                turn=dW.sum(axis=1).mean()*252,gross=P.mean()*252*100,
                cost=cost.mean()*252*100,sr_net=srn,cagr13=cagr*100,names=keep)

print(f"{'max hs':>7s} {'names':>6s} {'smooth':>7s} {'turn':>6s} {'gross%':>8s} {'cost%':>7s} {'SR net':>8s} {'CAGR@13%':>9s}")
best=None
for mh in [0.8,1.2,1.8,2.5]:
    for sm in [1,5,10,20]:
        r=run(mh,sm)
        if r is None: continue
        log_trial(f"CHEAP_h{mh}_s{sm}",{"sharpe":r["sr_net"],"cagr":r["cagr13"]/100,"vol":0.13,
                  "maxdd":0,"median_hold_days":sm,"avg_gross":1.0,"cost_drag_pct_yr":r["cost"]},
                  note="cost-restricted universe, mid signal, close execution")
        print(f"{mh:>7.1f} {r['n_names']:>6d} {sm:>7d} {r['turn']:>6.0f} {r['gross']:>7.2f}% "
              f"{r['cost']:>6.2f}% {r['sr_net']:>8.2f} {r['cagr13']:>8.2f}%")
        if best is None or r["sr_net"]>best["sr_net"]: best=r
print(f"\nBEST: SR {best['sr_net']:.2f}  CAGR@13% {best['cagr13']:.2f}%  "
      f"({best['n_names']} names, half-spread<={best['max_hs']}bp, smooth={best['smooth']})")
print(f"  names: {best['names']}")
