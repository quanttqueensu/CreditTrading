"""Cluster-pair architecture, IS run."""
import sys, json; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.pairs import PairConfig, simulate_pairs
from src.strategies.credit_rv.book import stats
from src.strategies.credit_rv.trials import log_trial

IS_START, IS_END = pd.Timestamp("2012-01-01"), pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
hs={k:v["half_spread_bp"] for k,v in yaml.safe_load((ROOT/"config/costs_rv.yaml").read_text())["tickers"].items()}
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]

sig=compute_signals(rets,rf,dv,SignalConfig())
keep=sig["s_cluster"].index>=IS_START
pcfg=PairConfig()
res=simulate_pairs(sig["s_cluster"][keep], sig["halflife"][keep], sig["ar_r2"][keep],
                   sig["sigma_eq"][keep], sig["kappa"][keep], sig["excess_returns"],
                   dv, hs, rf, pcfg)
st=stats(res["path"], rf, res["median_hold"]); st["tag"]="T004_cluster_pairs"
log_trial("T004_cluster_pairs", st, note="cluster-peer hedge replaces 6-leg synthetic hedge")
print("\n=== IS: CLUSTER PAIRS ===")
for k,v in st.items(): print(f"  {k:22s} {v:>14}" if isinstance(v,str) else f"  {k:22s} {v:14.4f}")
print(f"\n  total turnover ${res['turnover_by_leg'].sum():,.0f}   total cost ${res['cost_by_leg'].sum():,.0f}")
print(f"  trades: {len(res['trades'])}")
if len(res['trades']): print(res['trades'].groupby('cluster').agg(n=('days','size'), med_days=('days','median')).to_string())
out=ROOT/"results/credit_rv"; res["path"].to_parquet(out/"pairs_path.parquet")
res["weights"].to_parquet(out/"pairs_weights.parquet"); res["trades"].to_csv(out/"pairs_trades.csv",index=False)
json.dump(st, open(out/"pairs_stats.json","w"), indent=2, default=float)
