"""Bounce or real? If the lag-1 edge is bid-ask bounce, its size per name must
scale with that name's SPREAD. Genuine end-of-day flow reversal would not."""
import sys; from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats as sps
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
rx=sig["excess_returns"]; S=sig["s_blend"]; S=S[S.index>=IS_START]
cols=list(S.columns)
cm=SCENARIOS["base"]; advm=dv.tail(180).median()
half=pd.Series({c: cm.half_spread_bp(float(px[c].dropna().iloc[-1]), float(advm.get(c,0) or 0))
                for c in cols})

rows=[]
for lag in [1,2]:
    for c in cols:
        s=S[c]; j0=[rx.index.get_loc(d) for d in S.index]
        v=[]
        for d in S.index:
            j=rx.index.get_loc(d)
            if j+lag>=len(rx): continue
            sv=s.get(d,np.nan)
            r=rx[c].iloc[j+lag]
            if np.isfinite(sv) and np.isfinite(r):
                v.append(-np.sign(sv)*r*1e4)
        if len(v)<200: continue
        v=np.array(v)
        rows.append(dict(lag=lag,ticker=c,n=len(v),edge_bp=v.mean(),
                         t=v.mean()/v.std()*np.sqrt(len(v)),half_bp=half[c]))
df=pd.DataFrame(rows)
for lag in [1,2]:
    d=df[df.lag==lag]
    r=sps.linregress(d.half_bp,d.edge_bp)
    print(f"\n=== lag {lag}: per-name daily edge (bp) vs that name's half-spread (bp) ===")
    print(d.sort_values("half_bp")[["ticker","half_bp","edge_bp","t","n"]].round(2).to_string(index=False))
    print(f"  slope {r.slope:+.3f} bp of edge per 1bp of half-spread   "
          f"r={r.rvalue:+.3f}  p={r.pvalue:.4f}")
    if lag==1:
        print(f"  a slope near +2.0 would mean the edge IS the round-trip spread")
df.to_csv(ROOT/"results/credit_rv/bounce_test.csv",index=False)
