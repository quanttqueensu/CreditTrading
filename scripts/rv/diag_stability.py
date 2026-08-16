"""Is the BASE signal (pre-cost) stable across time, or also episode-driven?"""
import sys; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
df=pd.read_parquet(ROOT/"results/credit_rv/stress_diag_dated.parquet")
d=df[df.s.abs()>=2.0].copy()
print("=== BASE signal |s|>=2, gross bp, by year (no stress condition) ===")
by=d.groupby(d.date.dt.year).agg(n=("pnl_bp","size"),gross=("pnl_bp","mean"),
                                 net=("net_bp","mean"),hit=("pnl_bp",lambda x:(x>0).mean()))
by["t"]=d.groupby(d.date.dt.year).pnl_bp.apply(lambda x:x.mean()/x.std()*np.sqrt(len(x)))
print(by.round(2).to_string())
print(f"\npooled: n={len(d)}  gross={d.pnl_bp.mean():.2f}bp  net={d.net_bp.mean():.2f}bp  "
      f"t={d.pnl_bp.mean()/d.pnl_bp.std()*np.sqrt(len(d)):.2f}")
print("\n=== drop the COVID window entirely (2020-02-15..2020-04-30) ===")
mask=~((d.date>=pd.Timestamp('2020-02-15'))&(d.date<=pd.Timestamp('2020-04-30')))
x=d[mask]
print(f"  n={len(x)}  gross={x.pnl_bp.mean():.2f}bp  net={x.net_bp.mean():.2f}bp  "
      f"t={x.pnl_bp.mean()/x.pnl_bp.std()*np.sqrt(len(x)):.2f}")
print("\n=== ALL name-days (no |s| filter), ex-COVID, by year ===")
a=df[~((df.date>=pd.Timestamp('2020-02-15'))&(df.date<=pd.Timestamp('2020-04-30')))]
ay=a.groupby(a.date.dt.year).agg(n=("pnl_bp","size"),gross=("pnl_bp","mean"))
ay["t"]=a.groupby(a.date.dt.year).pnl_bp.apply(lambda x:x.mean()/x.std()*np.sqrt(len(x)))
print(ay.round(2).to_string())
print(f"\npooled ex-COVID all-|s|: n={len(a):,}  gross={a.pnl_bp.mean():.3f}bp  "
      f"t={a.pnl_bp.mean()/a.pnl_bp.std()*np.sqrt(len(a)):.2f}")
