"""Calibration: does the RV book machinery actually convert signal into P&L?

Three planted cases, in the spirit of scripts/calibration_planted_*.py:

  A. ORACLE  - s-score built from the KNOWN forward 5-day residual. A correct book
               must make a great deal of money. If it does not, book.py is broken
               and every negative result tonight is uninterpretable.
  B. ANTI    - the oracle with its sign flipped. Must lose about as much.
  C. NOISE   - a random s-score with the same shape. Must land near zero, net of
               costs somewhat below it.
"""
import sys; from pathlib import Path
import numpy as np, pandas as pd, yaml
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.strategies.credit_rv.signal import SignalConfig, compute_signals, build_factors
from src.strategies.credit_rv.book import BookConfig, simulate, stats

IS_START,IS_END=pd.Timestamp("2012-01-01"),pd.Timestamp("2023-12-31")
panel=pd.read_parquet(ROOT/"data/rv/etf_panel.parquet")
rets=panel.pivot(index="date",columns="ticker",values="ret_total").sort_index()
dv=(panel.assign(dv=panel.close*panel.volume).pivot(index="date",columns="ticker",values="dv").sort_index())
rf=pd.read_parquet(ROOT/"data/riskfree_daily.parquet").set_index("date")["rf_daily"]; rf.index=pd.to_datetime(rf.index)
hs={k:v["half_spread_bp"] for k,v in yaml.safe_load((ROOT/"config/costs_rv.yaml").read_text())["tickers"].items()}
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
sig=compute_signals(rets,rf,dv,SignalConfig())
keep=sig["s_blend"].index>=IS_START
SB=sig["s_blend"][keep]; MK=sig["tradeable_mask"][keep]
rx=sig["excess_returns"]; F=build_factors(rx); betas=sig["betas"]; cols=list(SB.columns)

# ---- build the ORACLE s-score: standardised forward 5d residual, sign-flipped
# so that "rich" (positive s) means "will fall", matching the real convention.
h=5
fwd=np.full((len(SB),len(cols)),np.nan)
for i,d in enumerate(SB.index):
    B=betas.get(d)
    if B is None: continue
    j=rx.index.get_loc(d)
    if j+1+h>len(rx): continue
    Bv=B.reindex(cols).values
    r=rx.iloc[j+1:j+1+h][cols].values.sum(axis=0)
    fexp=F.iloc[j+1:j+1+h].values.sum(axis=0)@Bv.T
    fwd[i]=r-fexp
fwd=pd.DataFrame(fwd,index=SB.index,columns=cols)
z=(fwd-fwd.mean())/fwd.std()
oracle=-z.clip(-4,4)               # positive s = rich = will underperform

rng=np.random.default_rng(7)
noise=pd.DataFrame(rng.standard_normal(SB.shape)*SB.std().mean(),index=SB.index,columns=cols)

# Machinery correctness must be judged with costs OFF: with costs ON a NOISE
# signal is guaranteed to lose (it churns), so "noise ~ 0 net" is not a valid
# check of the machinery - only of the cost model.
res={}
for label, zero_cost in [("GROSS (costs off)", True), ("NET (costs on)", False)]:
    print(f"\n=== {label} ===")
    print(f"{'case':>10s} {'Sharpe':>9s} {'CAGR':>10s} {'vol':>8s} {'cost%/yr':>9s}")
    for name,S in [("ORACLE",oracle),("ANTI",-oracle),("NOISE",noise)]:
        b=BookConfig(edge_margin=0.0,no_trade_band_nav=0.05,hedge_tol=0.10,
                     impact_coef=0.0 if zero_cost else 1.0,
                     financing_spread_bp=0.0 if zero_cost else 150.0,
                     short_borrow_bp=0.0 if zero_cost else 50.0)
        r=simulate(S,MK,betas,rx,dv,hs,rf,b,s_entry=2.0,s_exit=0.5,s_stop=99.0,
                   spread_mult=0.0 if zero_cost else 1.0)
        st=stats(r["path"],rf,r["median_hold"]); res[(label,name)]=st
        print(f"{name:>10s} {st['sharpe']:9.2f} {st['cagr']*100:9.2f}% {st['vol']*100:7.2f}% "
              f"{st['cost_drag_pct_yr']:8.2f}%")

g=lambda n: res[("GROSS (costs off)",n)]["sharpe"]
print("\n--- MACHINERY CHECKS (gross) ---")
c1=g("ORACLE")>3.0; c2=g("ANTI")<-3.0; c3=abs(g("NOISE"))<0.75
print(f"  [{'PASS' if c1 else 'FAIL'}] oracle gross Sharpe > 3.0   : {g('ORACLE'):.2f}")
print(f"  [{'PASS' if c2 else 'FAIL'}] anti-oracle mirrors it      : {g('ANTI'):.2f}")
print(f"  [{'PASS' if c3 else 'FAIL'}] noise gross ~ 0 (|SR|<0.75) : {g('NOISE'):.2f}")
ok=c1 and c2 and c3
print(f"\nMACHINERY: {'PASS - the book converts signal into P&L; tonight negative results are REAL' if ok else 'FAIL - book machinery leaks signal; results uninterpretable'}")
n_=res[("NET (costs on)","ORACLE")]
print(f"\nCOST TAX: perfect 5-day foresight yields gross SR {g('ORACLE'):.2f} -> net SR {n_['sharpe']:.2f} "
      f"(cost {n_['cost_drag_pct_yr']:.2f}%/yr).")
