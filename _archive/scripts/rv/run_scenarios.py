"""Re-run under each cost scenario. Every run is a logged trial."""
import sys, json, itertools; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.book import BookConfig, simulate, stats
from src.strategies.credit_rv.costs import SCENARIOS
from src.strategies.credit_rv.trials import log_trial
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
px=panel.pivot(index="date",columns="ticker",values="close").sort_index()
recent=dv.tail(180).median()
sig=compute_signals(rets,rf,dv,SignalConfig())
keep=sig["s_blend"].index>=IS_START
SB,MK=sig["s_blend"][keep],sig["tradeable_mask"][keep]

print(f"{'scenario':>13s} {'s_e':>4s} {'SR':>7s} {'CAGR':>8s} {'vol':>7s} {'DD':>7s} {'cost%':>7s} {'fin%':>6s} {'gross':>6s}")
rows=[]
for sc_name, cm in SCENARIOS.items():
    hs={t: cm.half_spread_bp(float(px[t].dropna().iloc[-1]), float(recent.get(t,0) or 0))
        for t in px.columns}
    for s_entry in [1.25, 1.5, 2.0, 2.5]:
        b=BookConfig(edge_margin=3.0,no_trade_band_nav=0.05,hedge_tol=0.10,cost_model=cm)
        res=simulate(SB,MK,sig["betas"],sig["excess_returns"],dv,hs,rf,b,
                     s_entry=s_entry,s_exit=0.5,s_stop=3.5,
                     sigma_eq=sig["sigma_eq"],kappa=sig["kappa"])
        st=stats(res["path"],rf,res["median_hold"])
        log_trial(f"SC_{sc_name}_e{s_entry}",st,note=f"cost scenario {sc_name}")
        rows.append(dict(scenario=sc_name,s_entry=s_entry,**{k:v for k,v in st.items() if k!="tag"}))
        print(f"{sc_name:>13s} {s_entry:>4.2f} {st['sharpe']:7.2f} {st['cagr']*100:7.2f}% "
              f"{st['vol']*100:6.2f}% {st['maxdd']*100:6.1f}% {st['cost_drag_pct_yr']:6.2f}% "
              f"{st['fin_drag_pct_yr']:5.2f}% {st['avg_gross']:6.2f}")
df=pd.DataFrame(rows); df.to_csv(ROOT/"results/credit_rv/scenarios.csv",index=False)
print("\n=== BEST PER SCENARIO ===")
print(df.loc[df.groupby("scenario").sharpe.idxmax()][
    ["scenario","s_entry","sharpe","cagr","vol","maxdd","cost_drag_pct_yr","fin_drag_pct_yr"]
    ].round(4).to_string(index=False))
