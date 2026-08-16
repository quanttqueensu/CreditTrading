"""Break-even cost, and the single most favourable corner: cheapest pairs only."""
import sys; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals, CLUSTERS
from src.strategies.credit_rv.pairs import PairConfig, simulate_pairs
from src.strategies.credit_rv.book import BookConfig, simulate, stats
from src.strategies.credit_rv.trials import log_trial
IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
hs={k:v["half_spread_bp"] for k,v in yaml.safe_load((ROOT/"config/costs_rv.yaml").read_text())["tickers"].items()}
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
keep=sig["s_blend"].index>=IS_START

print("=== BREAK-EVEN: scale ALL costs by a factor ===")
print(f"{'cost x':>8s} {'Sharpe':>8s} {'CAGR':>9s} {'cost%/yr':>9s}")
for mult in [0.0,0.1,0.25,0.5,0.75,1.0]:
    b=BookConfig(edge_margin=3.0,no_trade_band_nav=0.05,hedge_tol=0.10,
                 impact_coef=mult, financing_spread_bp=150.0*mult,
                 short_borrow_bp=50.0*mult)
    res=simulate(sig["s_blend"][keep],sig["tradeable_mask"][keep],sig["betas"],
                 sig["excess_returns"],dv,hs,rf,b,s_entry=2.0,s_exit=0.5,s_stop=3.5,
                 spread_mult=mult,sigma_eq=sig["sigma_eq"],kappa=sig["kappa"])
    st=stats(res["path"],rf,res["median_hold"])
    log_trial(f"BREAKEVEN_x{mult}",st,note="cost-scaling break-even curve")
    print(f"{mult:>8.2f} {st['sharpe']:8.2f} {st['cagr']*100:8.2f}% {st['cost_drag_pct_yr']:8.2f}%")

print("\n=== MOST FAVOURABLE CORNER: only the cheapest, deepest clusters ===")
CHEAP={"HY_BROAD":["HYG","JNK"], "IG_BROAD":["LQD","VCIT"]}
for se in [1.5,2.0,2.5]:
    p=PairConfig(s_entry=se,clusters=CHEAP,edge_margin=1.0)
    res=simulate_pairs(sig["s_cluster"][keep],sig["halflife"][keep],sig["ar_r2"][keep],
                       sig["sigma_eq"][keep],sig["kappa"][keep],sig["excess_returns"],
                       dv,hs,rf,p)
    st=stats(res["path"],rf,res["median_hold"])
    log_trial(f"CHEAPPAIRS_e{se}",st,note="HYG/JNK + LQD/VCIT only, 1-2bp legs")
    print(f"  s_entry={se}: SR {st['sharpe']:6.2f}  CAGR {st['cagr']*100:6.2f}%  "
          f"vol {st['vol']*100:5.2f}%  cost {st['cost_drag_pct_yr']:5.2f}%  trades {len(res['trades'])}")
