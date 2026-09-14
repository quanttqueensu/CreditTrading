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
hv=rx["HYG"].rolling(21).std()*np.sqrt(252); stress=hv.rolling(504,min_periods=252).rank(pct=True)
s=s[s.index>=START]; mask=mask[mask.index>=START]
rec=[]
h=5
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
            rec.append((d,c,sv[k],resid[k],st))
df=pd.DataFrame(rec,columns=["date","ticker","s","resid","stress"])
df["pnl_bp"]=-np.sign(df.s)*df.resid*1e4; df["cost"]=2*df.ticker.map(hs)
df["net_bp"]=df.pnl_bp-df.cost
sel=df[(df.s>=2.0)&(df.stress>=0.8)].copy()          # short-rich in stress
print(f"n = {len(sel)}   total net = {sel.net_bp.sum():,.0f}bp   mean = {sel.net_bp.mean():.1f}bp")
print("\n--- by calendar year ---")
by=sel.groupby(sel.date.dt.year).agg(n=("net_bp","size"),mean_bp=("net_bp","mean"),
                                     total_bp=("net_bp","sum"),hit=("net_bp",lambda x:(x>0).mean()))
print(by.round(1).to_string())
print("\n--- episode concentration (contiguous stress runs) ---")
sel=sel.sort_values("date")
gap=sel.date.diff().dt.days.fillna(0)>20
sel["episode"]=gap.cumsum()
ep=sel.groupby("episode").agg(start=("date","min"),end=("date","max"),n=("net_bp","size"),
                              total_bp=("net_bp","sum"),mean_bp=("net_bp","mean"))
print(ep.sort_values("total_bp",ascending=False).round(1).to_string())
tot=sel.net_bp.sum()
print(f"\ntop episode = {ep.total_bp.max()/tot*100:.1f}% of all P&L")
print(f"top 2       = {ep.total_bp.nlargest(2).sum()/tot*100:.1f}%")
print("\n--- DROP-ONE-EPISODE robustness ---")
for e in ep.total_bp.nlargest(3).index:
    r=sel[sel.episode!=e]
    t=r.net_bp.mean()/r.net_bp.std()*np.sqrt(len(r))
    print(f"  drop episode {ep.loc[e,'start'].date()}..{ep.loc[e,'end'].date()}: "
          f"n={len(r):>4d} mean={r.net_bp.mean():>7.1f}bp t={t:>5.2f}")
r=sel[~sel.episode.isin(ep.total_bp.nlargest(2).index)]
t=r.net_bp.mean()/r.net_bp.std()*np.sqrt(len(r)) if len(r)>2 else np.nan
print(f"  drop TOP TWO episodes:      n={len(r):>4d} mean={r.net_bp.mean():>7.1f}bp t={t:>5.2f}")
print("\n--- by instrument ---")
print(sel.groupby("ticker").agg(n=("net_bp","size"),mean_bp=("net_bp","mean"),
      total_bp=("net_bp","sum")).sort_values("total_bp",ascending=False).round(1).to_string())
df.to_parquet(ROOT/"results/credit_rv/stress_diag_dated.parquet")
