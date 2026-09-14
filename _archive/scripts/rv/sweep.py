"""Structured parameter sweep. Every config is a logged trial (prereg §8)."""
import sys, json, itertools; from pathlib import Path
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

# signal depends only on SignalConfig; cache per s_entry-independent params
base=SignalConfig()
sig=compute_signals(rets,rf,dv,base)
keep=sig["s_blend"].index>=IS_START
SB, MK = sig["s_blend"][keep], sig["tradeable_mask"][keep]
SE, KP = sig["sigma_eq"], sig["kappa"]

rows=[]
grid=list(itertools.product(
    [1.5, 2.0, 2.5],          # s_entry
    [1.0, 3.0, 6.0],          # edge_margin
    [0.01, 0.05],             # no-trade band (NAV units)
    [0.05, 0.20],             # hedge tolerance
))
print(f"{len(grid)} configs")
for s_entry, em, ntb, htol in grid:
    b=BookConfig(edge_margin=em, no_trade_band_nav=ntb, hedge_tol=htol)
    res=simulate(SB, MK, sig["betas"], sig["excess_returns"], dv, hs, rf, b,
                 s_entry=s_entry, s_exit=0.50, s_stop=3.50,
                 sigma_eq=SE, kappa=KP)
    st=stats(res["path"], rf, res["median_hold"])
    tag=f"S_e{s_entry}_m{em}_b{ntb}_h{htol}"
    log_trial(tag, st, note="sweep: general book")
    turn=res["turnover_by_leg"].sum()
    rows.append(dict(s_entry=s_entry, edge_margin=em, band=ntb, htol=htol,
                     sharpe=st["sharpe"], cagr=st["cagr"], vol=st["vol"], dd=st["maxdd"],
                     cost=st["cost_drag_pct_yr"], fin=st["fin_drag_pct_yr"],
                     gross=st["avg_gross"], hold=st["median_hold_days"],
                     turn_M=turn/1e6))
    print(f"  {tag:34s} SR {st['sharpe']:6.2f}  CAGR {st['cagr']*100:6.2f}%  "
          f"vol {st['vol']*100:5.2f}%  cost {st['cost_drag_pct_yr']:5.2f}%  turn ${turn/1e6:,.0f}M")
df=pd.DataFrame(rows).sort_values("sharpe",ascending=False)
df.to_csv(ROOT/"results/credit_rv/sweep.csv",index=False)
print("\n=== TOP 8 BY SHARPE ===")
print(df.head(8).round(3).to_string(index=False))
