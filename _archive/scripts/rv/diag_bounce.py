"""Is the lag-1 edge just the spread we would have to pay to capture it?"""
import sys; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.costs import SCENARIOS
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
px=panel.pivot(index="date",columns="ticker",values="close").sort_index()
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
rx=sig["excess_returns"]; betas=sig["betas"]; S=sig["s_blend"]; S=S[S.index>=IS_START]
cols=list(S.columns)
cm=SCENARIOS["base"]; advm=dv.tail(180).median()
hs=np.array([cm.half_spread_bp(float(px[c].dropna().iloc[-1]), float(advm.get(c,0) or 0))
             for c in cols])/1e4

def run(lag):
    W=[]; P=[]; D=[]
    for d in S.index:
        B=betas.get(d)
        if B is None: continue
        j=rx.index.get_loc(d)
        if j+lag>=len(rx): continue
        s=S.loc[d].values.astype(float); ok=np.isfinite(s)
        if ok.sum()<4: continue
        w=np.zeros(len(cols)); w[ok]=-s[ok]; w[ok]-=w[ok].mean()
        Bv=B.reindex(cols).values; good=ok&np.isfinite(Bv).all(axis=1)
        if good.sum()<7: continue
        Bk=Bv[good]; wk=w[good]
        wk=wk-Bk@np.linalg.solve(Bk.T@Bk+1e-10*np.eye(Bk.shape[1]),Bk.T@wk)
        w=np.zeros(len(cols)); w[good]=wk-wk.mean()
        n=np.abs(w).sum()
        if n<1e-12: continue
        w/=n
        W.append(w); P.append(float(w@np.nan_to_num(rx.iloc[j+lag][cols].values,nan=0.0)))
        D.append(d)
    W=np.array(W); P=pd.Series(P,index=D)
    turn=np.abs(np.diff(W,axis=0)).sum(axis=1)
    cost=(np.abs(np.diff(W,axis=0))*hs).sum(axis=1)
    gross=P.mean()*252*100
    costyr=cost.mean()*252*100
    net=gross-costyr
    sr_g=P.mean()/P.std()*np.sqrt(252)
    netp=P.iloc[1:]-cost
    sr_n=netp.mean()/netp.std()*np.sqrt(252)
    print(f"  lag {lag}:  gross {gross:6.2f}%/yr (SR {sr_g:5.2f})   "
          f"turnover {turn.mean()*252:6.0f}x/yr   cost {costyr:6.2f}%/yr   "
          f"NET {net:6.2f}%/yr (SR {sr_n:5.2f})")
    return gross,costyr

print("Unit-gross pure signal portfolio, daily rebalance, BASE cost scenario\n")
for lag in [1,2,3,5]:
    run(lag)
print("\nIf gross and cost are the same size at lag 1, the 'edge' IS the spread:")
print("the signal says buy what printed at the bid, and you must lift the ask to own it.")
