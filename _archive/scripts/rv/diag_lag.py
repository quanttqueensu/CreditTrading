"""Lag ladder. Real predictive information decays smoothly with extra lag.
Look-ahead collapses the moment you stop letting it see the present."""
import sys; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
rx=sig["excess_returns"]; betas=sig["betas"]; S=sig["s_blend"]; S=S[S.index>=IS_START]
cols=list(S.columns)

def sharpe_at_lag(lag):
    pnl=[]
    for d in S.index:
        B=betas.get(d)
        if B is None: continue
        j=rx.index.get_loc(d)
        if j+lag>=len(rx) or j+lag<0: continue
        s=S.loc[d].values.astype(float); ok=np.isfinite(s)
        if ok.sum()<4: continue
        w=np.zeros(len(cols)); w[ok]=-s[ok]; w[ok]-=w[ok].mean()
        Bv=B.reindex(cols).values
        good=ok&np.isfinite(Bv).all(axis=1)
        if good.sum()<7: continue
        Bk=Bv[good]; wk=w[good]
        wk=wk-Bk@np.linalg.solve(Bk.T@Bk+1e-10*np.eye(Bk.shape[1]),Bk.T@wk)
        w=np.zeros(len(cols)); w[good]=wk-wk.mean()
        n=np.abs(w).sum()
        if n<1e-12: continue
        w/=n
        pnl.append(float(w@np.nan_to_num(rx.iloc[j+lag][cols].values,nan=0.0)))
    p=pd.Series(pnl)
    return p.mean()/p.std()*np.sqrt(252), p.mean()*252*100, len(p)

print("lag  0 = SAME DAY as the signal (must be unusable in live trading)")
print("lag +1 = the traded convention\n")
print(f"{'lag':>5s} {'Sharpe':>9s} {'gross %/yr per unit gross':>28s} {'n':>8s}")
for lag in [0,1,2,3,5,10]:
    sr,g,n=sharpe_at_lag(lag)
    flag=""
    if lag==0: flag="  <- contains the signal's own day"
    print(f"{lag:>5d} {sr:9.2f} {g:>27.2f}% {n:>8,d}{flag}")
