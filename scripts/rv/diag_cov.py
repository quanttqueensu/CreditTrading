"""Is diagonal shrinkage strangling the vol target on a hedged book?"""
import sys, json; from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
sys.argv=[sys.argv[0]]
from scripts.rv.run_is import load, run
from src.strategies.credit_rv.signal import SignalConfig, compute_signals
from src.strategies.credit_rv.book import BookConfig, shrunk_cov
import pandas as pd

rets,dv,rf,hs=load()
IS_END=pd.Timestamp("2023-12-31")
rets=rets[rets.index<=IS_END]; dv=dv[dv.index<=IS_END]
scfg=SignalConfig()
sig=compute_signals(rets,rf,dv,scfg)
w=pd.read_parquet(ROOT/"results/credit_rv/is_weights.parquet")
rx=sig["excess_returns"].reindex(columns=w.columns)

# take a day the book was on; compare estimated vs realised vol of that weight vector
on=w[(w.abs().sum(axis=1)>0.3)]
print(f"days on risk: {len(on)} / {len(w)}")
rows=[]
for shrink in [0.0,0.05,0.10,0.20,0.40]:
    ests=[]
    for d in on.index[::50]:
        j=rx.index.get_loc(d)
        hist=rx.iloc[max(0,j-119):j+1].values
        S=shrunk_cov(hist,shrink)
        wv=on.loc[d].values
        ests.append(np.sqrt(max(wv@S@wv,1e-18))*np.sqrt(252))
    rows.append((shrink,np.nanmedian(ests)))
# realised vol of the actual book
path=pd.read_parquet(ROOT/"results/credit_rv/is_path.parquet")
real=path.loc[path.gross>0.3,"ret"].std()*np.sqrt(252)
print(f"\nREALISED vol on risk-on days: {real*100:.2f}%")
print(f"{'shrink':>8s} {'median ex-ante vol':>20s} {'ratio to realised':>19s}")
for s,e in rows:
    print(f"{s:>8.2f} {e*100:>19.2f}% {e/real:>19.2f}")
