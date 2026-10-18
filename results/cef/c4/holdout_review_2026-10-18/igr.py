"""REPORT-ONLY: IGR's held weight, return and P&L around the mixed-basis bars and every ex-date."""
import sys, pickle; sys.dont_write_bytecode = True
import numpy as np, pandas as pd
S = "/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/9491f9f2-8a08-4ed2-8837-1fbdbf0ca22e/scratchpad/c4_review/"
d = pickle.load(open(S + "repro.pkl", "rb"))
H, R0, T = d["H"], d["R0"], d["T"]
held = H.shift(2).fillna(0.0)
C = held * R0
lo, hi = "2023-01-01", "2026-09-30"
igr = pd.DataFrame(dict(T=T["IGR"], H=H["IGR"], held=held["IGR"], R=R0["IGR"], pnl=C["IGR"], book=C.sum(axis=1)))
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 200)
print(igr.loc["2026-07-15":"2026-09-30"].round(5))
print("IGR holdout P&L total", C["IGR"].loc[lo:hi].sum(), " book total", C.loc[lo:hi].sum().sum())
bad = pd.to_datetime(["2026-07-29","2026-07-30","2026-08-04","2026-08-05","2026-08-07","2026-08-10","2026-08-11","2026-08-12"])
print("IGR P&L on the 8 rows touched by the four mixed bars:", C.loc[bad, "IGR"].sum())
print("IGR P&L, holdout, outside those 8 rows:", C["IGR"].loc[lo:hi].drop(bad).sum())
print("IGR by year:", C["IGR"].loc[lo:hi].groupby(C.loc[lo:hi].index.year).sum().round(5).to_dict())
# top 10 single-day fund contributions in the holdout
st = C.loc[lo:hi].stack(); st = st[st != 0]
print(st.reindex(st.abs().sort_values(ascending=False).index).head(15))
