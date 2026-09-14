"""Separate signal quality from execution cost."""
import sys; from pathlib import Path
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

print(f"{'cost level':>26s} {'Sharpe':>8s} {'CAGR':>9s} {'vol':>7s} {'cost%/yr':>9s}")
for label, mult, fin, imp in [
    ("ZERO cost (signal only)", 0.0, 0.0, 0.0),
    ("spreads only, no impact", 1.0, 0.0, 0.0),
    ("half spreads",            0.5, 150.0, 1.0),
    ("full model (as traded)",  1.0, 150.0, 1.0),
    ("double spreads (G-COST)", 2.0, 150.0, 1.0),
]:
    b=BookConfig(edge_margin=3.0, no_trade_band_nav=0.05, hedge_tol=0.05,
                 financing_spread_bp=fin, short_borrow_bp=(50.0 if fin else 0.0),
                 impact_coef=imp)
    res=simulate(SB,MK,sig["betas"],sig["excess_returns"],dv,hs,rf,b,
                 s_entry=2.0,s_exit=0.5,s_stop=3.5,spread_mult=mult,
                 sigma_eq=sig["sigma_eq"],kappa=sig["kappa"])
    st=stats(res["path"],rf,res["median_hold"])
    log_trial(f"GROSS_{label.replace(' ','_')}", st, note="cost decomposition diagnostic")
    print(f"{label:>26s} {st['sharpe']:8.2f} {st['cagr']*100:8.2f}% {st['vol']*100:6.2f}% {st['cost_drag_pct_yr']:8.2f}%")
