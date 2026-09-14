import sys, json; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.book_opt import OptBookConfig, simulate_opt
from src.strategies.credit_rv.book import stats
from src.strategies.credit_rv.costs import SCENARIOS
from src.strategies.credit_rv.trials import log_trial
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
px=panel.pivot(index="date",columns="ticker",values="close").sort_index()
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig(s_entry=0.0))
keep=sig["s_blend"].index>=IS_START
SB,MK=sig["s_blend"][keep],sig["tradeable_mask"][keep]
print(f"{'scenario':>13s} {'SR':>7s} {'CAGR':>8s} {'vol':>7s} {'DD':>7s} {'cost%':>7s} {'fin%':>6s} {'gross':>6s} {'hold':>5s} {'turn$M':>8s}")
rows=[]
for name,cm in SCENARIOS.items():
    cfg=OptBookConfig(cost_model=cm)
    r=simulate_opt(SB,MK,sig["betas"],sig["sigma_eq"],sig["kappa"],sig["excess_returns"],
                   dv,px,rf,cfg)
    st=stats(r["path"],rf,r["median_hold"]); t=r["turnover_by_leg"].sum()
    log_trial(f"OPT_{name}",st,note="cost-aware mean-variance optimiser")
    rows.append(dict(scenario=name,**{k:v for k,v in st.items() if k!="tag"},turn_M=t/1e6))
    print(f"{name:>13s} {st['sharpe']:7.2f} {st['cagr']*100:7.2f}% {st['vol']*100:6.2f}% "
          f"{st['maxdd']*100:6.1f}% {st['cost_drag_pct_yr']:6.2f}% {st['fin_drag_pct_yr']:5.2f}% "
          f"{st['avg_gross']:6.2f} {st['median_hold_days']:5.1f} {t/1e6:8,.0f}")
pd.DataFrame(rows).to_csv(ROOT/"results/credit_rv/opt_scenarios.csv",index=False)
