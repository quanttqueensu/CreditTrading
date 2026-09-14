"""Prereg §2.5: does reversion strengthen when dealer/AP capacity is constrained?
Stress proxy is built from TRADEABLE prices only (live-computable): trailing 21d
realised vol of the HY complex, as a percentile of its own trailing 2y history."""
import sys; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals, build_factors

panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
hs={k:v["half_spread_bp"] for k,v in yaml.safe_load((ROOT/"config/costs_rv.yaml").read_text())["tickers"].items()}
IS_END=pd.Timestamp("2023-12-31"); START=pd.Timestamp("2012-01-01")
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
s=sig["s_blend"]; mask=sig["tradeable_mask"]; rx=sig["excess_returns"]; F=build_factors(rx); betas=sig["betas"]
cols=list(s.columns)

# STRESS: 21d realised vol of HYG, percentile-ranked on a trailing 504d window.
# All from tradeable prices -> computable live, no external data dependency.
hv=rx["HYG"].rolling(21).std()*np.sqrt(252)
stress=hv.rolling(504,min_periods=252).rank(pct=True)

s=s[s.index>=START]; mask=mask[mask.index>=START]
recs=[]
for h in [5]:
    for d in s.index[:-h-1]:
        B=betas.get(d)
        if B is None: continue
        m=mask.loc[d].values; sv=s.loc[d].values
        j=rx.index.get_loc(d); fwd=rx.iloc[j+1:j+1+h]
        if len(fwd)<h: continue
        Bv=B.reindex(cols).values
        resid=fwd[cols].values.sum(axis=0)-(F.iloc[j+1:j+1+h].values.sum(axis=0)@Bv.T)
        st=stress.get(d,np.nan)
        for k,c in enumerate(cols):
            if m[k] and np.isfinite(sv[k]) and np.isfinite(resid[k]):
                recs.append((c,sv[k],resid[k],st))
df=pd.DataFrame(recs,columns=["ticker","s","resid","stress"])
df["pnl_bp"]=-np.sign(df.s)*df.resid*1e4
df["abs_s"]=df.s.abs(); df["cost"]=2*df.ticker.map(hs)
df=df.dropna(subset=["stress"])

print("=== edge (bp, h=5) by |s| x stress regime ===")
print(f"{'|s|':>10s} {'stress':>14s} {'n':>7s} {'gross':>8s} {'t':>6s} {'cost':>6s} {'NET':>8s}")
for lo,hi in [(1.5,2.0),(2.0,2.5),(2.5,3.5),(3.5,99)]:
    for sl,sh,lbl in [(0.0,0.5,"calm  <p50"),(0.5,0.8,"mid p50-80"),(0.8,1.01,"STRESS >p80")]:
        g=df[(df.abs_s>=lo)&(df.abs_s<hi)&(df.stress>=sl)&(df.stress<sh)]
        if len(g)<30: continue
        t=g.pnl_bp.mean()/g.pnl_bp.std()*np.sqrt(len(g))
        print(f"  {lo:>4.1f}-{hi:<4.1f} {lbl:>14s} {len(g):>7,d} {g.pnl_bp.mean():>8.2f} {t:>6.1f} "
              f"{g.cost.mean():>6.2f} {g.pnl_bp.mean()-g.cost.mean():>8.2f}")

print("\n=== direction asymmetry (|s|>=2.0): is buying the CHEAP one the payer? ===")
d2=df[df.abs_s>=2.0]
for lbl,side in [("BUY cheap (s<0)",d2[d2.s<0]),("SHORT rich (s>0)",d2[d2.s>0])]:
    t=side.pnl_bp.mean()/side.pnl_bp.std()*np.sqrt(len(side))
    print(f"  {lbl:>18s} n={len(side):>5,d}  gross {side.pnl_bp.mean():>7.2f}bp  t={t:>5.2f}  "
          f"NET {side.pnl_bp.mean()-side.cost.mean():>7.2f}bp")
    for sl,sh,l2 in [(0.0,0.8,"calm/mid"),(0.8,1.01,"STRESS")]:
        gg=side[(side.stress>=sl)&(side.stress<sh)]
        if len(gg)<30: continue
        tt=gg.pnl_bp.mean()/gg.pnl_bp.std()*np.sqrt(len(gg))
        print(f"      {l2:>10s} n={len(gg):>5,d} gross {gg.pnl_bp.mean():>7.2f}bp t={tt:>5.2f} "
              f"NET {gg.pnl_bp.mean()-gg.cost.mean():>7.2f}bp")
df.to_parquet(ROOT/"results/credit_rv/stress_diag.parquet")
