"""Breadth x rebalance-frequency x impact sensitivity. All logged as trials."""
import sys, itertools; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.book import BookConfig, simulate, stats
from src.strategies.credit_rv.trials import log_trial
IS_START, IS_END = pd.Timestamp("2012-01-01"), pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
hs={k:v["half_spread_bp"] for k,v in yaml.safe_load((ROOT/"config/costs_rv.yaml").read_text())["tickers"].items()}
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
keep=sig["s_blend"].index>=IS_START
SB,MK=sig["s_blend"][keep],sig["tradeable_mask"][keep]
print(f"{'cfg':>30s} {'SR':>6s} {'CAGR':>8s} {'vol':>7s} {'cost':>7s} {'turn$M':>8s} {'gross':>6s} {'npos':>5s}")
rows=[]
for s_entry, reb, mrs, icoef in itertools.product([1.5,2.0],[1,5,10],[0.20,0.35],[1.0,0.5]):
    b=BookConfig(edge_margin=3.0,no_trade_band_nav=0.05,hedge_tol=0.10,
                 rebalance_every=reb,max_risk_share=mrs,impact_coef=icoef)
    res=simulate(SB,MK,sig["betas"],sig["excess_returns"],dv,hs,rf,b,
                 s_entry=s_entry,s_exit=0.5,s_stop=3.5,
                 sigma_eq=sig["sigma_eq"],kappa=sig["kappa"])
    st=stats(res["path"],rf,res["median_hold"]); turn=res["turnover_by_leg"].sum()
    tag=f"e{s_entry}_r{reb}_m{mrs}_i{icoef}"
    log_trial(tag,st,note="sweep2: breadth x rebalance freq x impact coef")
    rows.append(dict(tag=tag,s_entry=s_entry,reb=reb,mrs=mrs,icoef=icoef,sharpe=st["sharpe"],
                     cagr=st["cagr"],vol=st["vol"],dd=st["maxdd"],cost=st["cost_drag_pct_yr"],
                     turn_M=turn/1e6,gross=st["avg_gross"],npos=st["avg_n_pos"]))
    print(f"{tag:>30s} {st['sharpe']:6.2f} {st['cagr']*100:7.2f}% {st['vol']*100:6.2f}% "
          f"{st['cost_drag_pct_yr']:6.2f}% {turn/1e6:8,.0f} {st['avg_gross']:6.2f} {st['avg_n_pos']:5.1f}")
df=pd.DataFrame(rows).sort_values("sharpe",ascending=False)
df.to_csv(ROOT/"results/credit_rv/sweep2.csv",index=False)
print("\n=== TOP 6 ===");print(df.head(6).round(3).to_string(index=False))
