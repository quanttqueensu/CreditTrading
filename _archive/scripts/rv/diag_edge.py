"""Where is the edge? By |s| magnitude, by cost tier, by instrument."""
import sys; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals, build_factors

panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
costs=yaml.safe_load((ROOT/"config/costs_rv.yaml").read_text())
HS={k:v["half_spread_bp"] for k,v in costs["tickers"].items()}
IS_END=pd.Timestamp("2023-12-31"); START=pd.Timestamp("2012-01-01")
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
s=sig["s_blend"]; mask=sig["tradeable_mask"]; rx=sig["excess_returns"]; F=build_factors(rx); betas=sig["betas"]
cols=list(s.columns); s=s[s.index>=START]; mask=mask[mask.index>=START]

recs=[]
for h in [3,5,10]:
    for i,d in enumerate(s.index[:-h-1]):
        B=betas.get(d)
        if B is None: continue
        m=mask.loc[d].values; sv=s.loc[d].values
        j=rx.index.get_loc(d); fwd=rx.iloc[j+1:j+1+h]
        if len(fwd)<h: continue
        Bv=B.reindex(cols).values
        resid=fwd[cols].values.sum(axis=0)-(F.iloc[j+1:j+1+h].values.sum(axis=0)@Bv.T)
        for k,c in enumerate(cols):
            if m[k] and np.isfinite(sv[k]) and np.isfinite(resid[k]):
                recs.append((h,c,sv[k],resid[k]))
df=pd.DataFrame(recs,columns=["h","ticker","s","resid"])
df["pnl_bp"]=-np.sign(df.s)*df.resid*1e4          # signed as the trade would be taken
df["abs_s"]=df.s.abs()
df["hs"]=df.ticker.map(HS)
df["rt_cost_bp"]=2*df.hs

print("=== edge by |s| bucket (bp per trade, before cost) ===")
buckets=[(1.0,1.25),(1.25,1.5),(1.5,2.0),(2.0,2.5),(2.5,3.0),(3.0,99)]
for h in [3,5,10]:
    d0=df[df.h==h]
    print(f"\n h={h}d")
    print(f"  {'|s|':>10s} {'n':>8s} {'gross bp':>10s} {'t':>7s} {'cost bp':>9s} {'NET bp':>9s}")
    for lo,hi in buckets:
        g=d0[(d0.abs_s>=lo)&(d0.abs_s<hi)]
        if len(g)<50: continue
        t=g.pnl_bp.mean()/g.pnl_bp.std()*np.sqrt(len(g))
        net=g.pnl_bp.mean()-g.rt_cost_bp.mean()
        print(f"  {lo:>4.2f}-{hi:<5.2f} {len(g):>8,d} {g.pnl_bp.mean():>10.2f} {t:>7.1f} {g.rt_cost_bp.mean():>9.2f} {net:>9.2f}")

print("\n=== by instrument, |s|>=1.25, h=5 ===")
d0=df[(df.h==5)&(df.abs_s>=1.25)]
r=d0.groupby("ticker").agg(n=("pnl_bp","size"),gross_bp=("pnl_bp","mean"),
                            sd=("pnl_bp","std"),cost=("rt_cost_bp","mean"))
r["t"]=r.gross_bp/r.sd*np.sqrt(r.n); r["net_bp"]=r.gross_bp-r.cost
print(r.sort_values("net_bp",ascending=False).round(2).to_string())
df.to_parquet(ROOT/"results/credit_rv/edge_diag.parquet")
