"""Does the s-score predict residual reversion? Signal quality, no portfolio."""
import sys; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals, build_factors

panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
IS_END=pd.Timestamp("2023-12-31")
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]

cfg=SignalConfig()
sig=compute_signals(rets,rf,dv,cfg)
s=sig["s_blend"]; mask=sig["tradeable_mask"]; rx=sig["excess_returns"]
F=build_factors(rx)
start=pd.Timestamp("2012-01-01")
s=s[s.index>=start]; mask=mask[mask.index>=start]

# forward RESIDUAL return: strip contemporaneous factor moves with the same betas
betas=sig["betas"]
cols=list(s.columns)
print(f"{'h':>3s} {'IC(s,fwd resid)':>16s} {'t-stat':>9s} {'n':>9s} {'top-vs-bottom bp':>18s}")
for h in [1,2,3,5,10,20]:
    ics=[]; spreads=[]
    dates=s.index[:-h-1]
    for i,d in enumerate(dates):
        B=betas.get(d)
        if B is None: continue
        m=mask.loc[d].values
        if m.sum()<4: continue
        sv=s.loc[d].values
        # forward window returns, residualised on the SAME betas (no look-ahead in betas)
        j=rx.index.get_loc(d)
        fwd=rx.iloc[j+1:j+1+h]
        if len(fwd)<h: continue
        Fv=F.iloc[j+1:j+1+h].values
        Bv=B.reindex(cols).values
        rfwd=fwd[cols].values.sum(axis=0)              # cumulative simple sum
        fexp=(Fv.sum(axis=0)@Bv.T)
        resid_fwd=rfwd-fexp
        ok=m&np.isfinite(sv)&np.isfinite(resid_fwd)
        if ok.sum()<4: continue
        a,b=sv[ok],resid_fwd[ok]
        if a.std()<1e-12: continue
        ics.append(np.corrcoef(a,b)[0,1])
        # long cheapest half, short richest half
        med=np.median(a)
        spreads.append(b[a<=med].mean()-b[a>med].mean())
    ics=np.array(ics); sp=np.array(spreads)
    t=ics.mean()/ics.std()*np.sqrt(len(ics)) if len(ics)>2 else np.nan
    print(f"{h:>3d} {ics.mean():>16.4f} {t:>9.2f} {len(ics):>9,d} {sp.mean()*1e4:>18.2f}")
