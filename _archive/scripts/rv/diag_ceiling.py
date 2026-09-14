"""THE CEILING: what does this signal earn with FREE execution, at full risk budget?

If double digits is unreachable even at zero cost, then no cost assumption -
however favourable, however verified at the open - can rescue it, and the
constraint that must move is not cost.
"""
import sys; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.book import BookConfig, simulate, stats
from src.strategies.credit_rv.costs import CostModel
from src.strategies.credit_rv.trials import log_trial
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
keep=sig["s_blend"].index>=IS_START
SB,MK=sig["s_blend"][keep],sig["tradeable_mask"][keep]
FREE=CostModel(scenario="free",tick_usd=0.0,touch_frac_of_adv=1.0,impact_coef=0.0,
               borrow_fee_bp=0.0,margin_spread_bp=0.0)
hs={t:0.0 for t in rets.columns}
print("FREE EXECUTION — zero spread, zero impact, zero financing\n")
print(f"{'vol tgt':>8s} {'s_entry':>8s} {'SR':>7s} {'CAGR':>9s} {'vol':>7s} {'maxDD':>8s} {'gross':>6s}")
best=None
for vt in [0.13,0.20,0.30]:
    for se in [1.5,2.0,2.5]:
        b=BookConfig(vol_target=vt,max_gross=20.0,vol_scale_cap=30.0,edge_margin=0.0,
                     no_trade_band_nav=0.0,hedge_tol=0.02,cost_model=FREE,max_risk_share=0.35)
        r=simulate(SB,MK,sig["betas"],sig["excess_returns"],dv,hs,rf,b,
                   s_entry=se,s_exit=0.5,s_stop=3.5,spread_mult=0.0,
                   sigma_eq=sig["sigma_eq"],kappa=sig["kappa"])
        st=stats(r["path"],rf,r["median_hold"])
        log_trial(f"CEILING_v{vt}_e{se}",st,note="FREE execution ceiling")
        print(f"{vt*100:7.0f}% {se:8.2f} {st['sharpe']:7.2f} {st['cagr']*100:8.2f}% "
              f"{st['vol']*100:6.2f}% {st['maxdd']*100:7.1f}% {st['avg_gross']:6.2f}")
        if best is None or st["cagr"]>best[0]: best=(st["cagr"],vt,se,st)
c,vt,se,st=best
print(f"\nBEST FREE-EXECUTION RESULT: CAGR {c*100:.2f}%/yr at vol target {vt*100:.0f}%, "
      f"s_entry {se}")
print(f"  Sharpe {st['sharpe']:.2f}   realised vol {st['vol']*100:.1f}%   maxDD {st['maxdd']*100:.1f}%")
print(f"\n  double-digit target reached with FREE execution? "
      f"{'YES' if c>=0.10 else 'NO'}")
print(f"  within the 25% drawdown tolerance?              "
      f"{'YES' if st['maxdd']>-0.25 else 'NO'}")
