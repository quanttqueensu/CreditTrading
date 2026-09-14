"""MINIMAL implementation. The point is that there is almost nothing here.

    w_t  proportional to  -s_t   (cross-sectionally demeaned)
    projected factor-neutral
    scaled to a vol target
    return earned on r_{t+1}

No state machine, no entry/exit thresholds, no admissibility mask, no risk-parity
units, no no-trade band, no economic gate. If the signal carries information, this
must show it. Costs are OFF here on purpose: this measures the INFORMATION, and
cost is applied separately afterwards.
"""
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
rx=sig["excess_returns"]; betas=sig["betas"]

def run(S, label, neutral=True, vol_target=0.13):
    S=S[S.index>=IS_START]
    cols=list(S.columns); pnl=[]; dates=[]
    for i,d in enumerate(S.index):
        B=betas.get(d)
        if B is None: continue
        j=rx.index.get_loc(d)
        if j+1>=len(rx): break
        s=S.loc[d].values.astype(float)
        ok=np.isfinite(s)
        if ok.sum()<4: continue
        w=np.zeros(len(cols)); w[ok]=-s[ok]
        w[ok]-=w[ok].mean()                       # dollar neutral
        if neutral:
            Bv=B.reindex(cols).values
            good=ok&np.isfinite(Bv).all(axis=1)
            if good.sum()<7: continue
            Bk=Bv[good]; wk=w[good]
            G=Bk.T@Bk+1e-10*np.eye(Bk.shape[1])
            wk=wk-Bk@np.linalg.solve(G,Bk.T@wk)
            w=np.zeros(len(cols)); w[good]=wk-wk.mean()
        n=np.abs(w).sum()
        if n<1e-12: continue
        w=w/n                                     # unit gross, scale later
        r=np.nan_to_num(rx.iloc[j+1][cols].values,nan=0.0)
        pnl.append(float(w@r)); dates.append(rx.index[j+1])
    p=pd.Series(pnl,index=dates)
    sr=p.mean()/p.std()*np.sqrt(252)
    lev=vol_target/(p.std()*np.sqrt(252))
    cagr=(1+p*lev).prod()**(252/len(p))-1
    dd=((1+p*lev).cumprod()/(1+p*lev).cumprod().cummax()-1).min()
    print(f"  {label:34s} SR {sr:6.2f}   gross {p.mean()*252*100:7.2f}%/unit  "
          f"levered CAGR {cagr*100:6.2f}%  DD {dd*100:6.1f}%  n={len(p):,}")
    return sr,p

print("PURE SIGNAL, zero cost, unit-gross then levered to 13% vol\n")
run(sig["s_blend"],   "s_blend  (as traded)")
run(sig["s_complex"], "s_complex only")
run(sig["s_cluster"], "s_cluster only")
run(sig["s_blend"],   "s_blend, NO factor neutralisation", neutral=False)
print()
# masked version, to isolate what the admissibility filter costs
m=sig["tradeable_mask"]
run(sig["s_blend"].where(m), "s_blend x admissibility mask")
