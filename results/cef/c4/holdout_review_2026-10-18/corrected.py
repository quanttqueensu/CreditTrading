"""REPORT-ONLY diagnostic (not a trial, selects nothing): the declared holdout with IGR's four mixed-basis
bars (2026-07-29, 08-04, 08-07, 08-11: post-split-basis rows in a raw pre-split series) replaced by
Alpaca's raw bars, the fetched second source already on disk. Same harness, same rules, same actions."""
import sys, json, pickle; sys.dont_write_bytecode = True
W = "/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/.claude/worktrees/trial-c4"
sys.path.insert(0, W)
import numpy as np, pandas as pd
from scripts.cef import c4_families as c4
from scripts.cef import band_frontier as bf
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS
S = "/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/9491f9f2-8a08-4ed2-8837-1fbdbf0ca22e/scratchpad/c4_review/"
d = pickle.load(open(S + "repro.pkl", "rb"))
UH, UF, snap = d["UH"], d["UF"], d["snap"]
BAD = pd.to_datetime(["2026-07-29", "2026-08-04", "2026-08-07", "2026-08-11"])
raw = pd.read_parquet(c4.FAM_DIR / "cef_prices.parquet"); raw["date"] = pd.to_datetime(raw["date"])
b = pd.read_parquet(c4.ALP_POOL); b["date"] = pd.to_datetime(b["date"])
ar = b[(b.ticker == "IGR") & (b.adjustment == "raw")].set_index("date")
fixed = raw.copy()
for dt in BAD:
    m = (fixed.ticker == "IGR") & (fixed.date == dt)
    assert m.sum() == 1
    old = fixed.loc[m, "close"].iloc[0]
    assert abs(old - b[(b.ticker == "IGR") & (b.adjustment == "split") & (b.date == dt)]["close"].iloc[0]) < 1e-6
    for c in ("open", "high", "low", "close", "volume"):
        fixed.loc[m, c] = float(ar.loc[dt, c])
    print(dt.date(), "panel close", old, "-> Alpaca raw", fixed.loc[m, "close"].iloc[0], "volume", fixed.loc[m, "volume"].iloc[0])
fixed["date"] = fixed["date"].dt.strftime("%Y-%m-%d") if raw["date"].dtype != object else fixed["date"]
orig = pd.read_parquet(c4.FAM_DIR / "cef_prices.parquet")
fixed["date"] = orig["date"].values  # keep the original dtype/values for the date column
fixed.to_parquet(S + "cef_prices_igrfixed.parquet", index=False)
FIX_SRC = (S + "cef_prices_igrfixed.parquet", str(c4.FAM_SRC[1]))

lo, hi = c4.HOLDOUT_START, c4.HOLDOUT_END
T0, H0, R00 = d["T"], d["H"], d["R0"]
sess = T0.index[T0.index <= hi]
cols = sorted(set(UF) | set(snap))
pxf = fixed.copy(); pxf["date"] = pd.to_datetime(pxf["date"])
close = pxf.pivot_table(index="date", columns="ticker", values="close").sort_index()
rpx = close.pct_change(fill_method=None).reindex(index=sess, columns=cols)
yf = bf.total_returns(rpx, actions=S + "ruled_actions.parquet", prices=S + "cef_prices_igrfixed.parquet")
for dt, v in d["fill"].items():
    assert pd.isna(yf.loc[dt, "IGR"]); yf.loc[dt, "IGR"] = v
Rf = pd.concat([d["cr"].loc[:c4.CRSP_END], yf.loc[c4.YF_START:]])
assert Rf.index.equals(sess)
diffR = (Rf[UH] - d["R"][UH]).abs().stack(); diffR = diffR[diffR > 1e-12]
print("return cells changed:", diffR.round(4).to_dict())

def stats(H, R, label):
    R0 = c4.check_held(H, R[UH].reindex(index=H.index), label)
    r = bf.evaluate(H, R0)
    P, TU = r["pnl"].loc[lo:hi], r["turn_series"].loc[lo:hi]
    s = c4.row_stats(P, TU)
    print(f"{label:<62} SR {s['sr']:.3f} ann {s['ann_pct']:+.2f}% vol {s['vol_pct']:.2f}% turn {s['turn']:.1f} "
          f"net5 {s['net5']:.3f} net15 {s['net15']:.3f} net30 {s['net30']:.3f} flips {s['flips']}")
    return dict(H=H, R0=R0, P=P, TU=TU, s=s, pnl=r["pnl"])

out = {}
out["declared"] = stats(H0, d["R"], "declared (committed inputs, reproduced)")
out["R_only"] = stats(H0, Rf, "returns corrected only (book unchanged)")
Tf = bf.build_targets(universe=list(UH), source=FIX_SRC, mask=c4.declared_mask(list(UH)))[0]
print("targets changed on", int((Tf - T0).abs().gt(1e-15).any(axis=1).sum()), "dates; first",
      (Tf - T0).abs().gt(1e-15).any(axis=1).idxmax().date() if (Tf - T0).abs().gt(1e-15).any().any() else None)
Hf = bf.band_gross_capped(Tf.loc[:hi], BAND_WIDTH, MAX_GROSS_STRESS)
assert np.array_equal(Hf.loc[:c4.FIT_END].to_numpy(), H0.loc[:c4.FIT_END].to_numpy())
out["full"] = stats(Hf, Rf, "signal AND returns corrected (IGR bars from Alpaca raw)")
for lab, a, b_ in (("CRSP leg", lo, c4.CRSP_END), ("yfinance leg", c4.YF_START, hi)):
    x, tx = out["full"]["P"].loc[a:b_], out["full"]["TU"].loc[a:b_]
    s = c4.row_stats(x, tx); print(f"   corrected {lab}: SR {s['sr']:.3f} ann {s['ann_pct']:+.2f}% net15 {s['net15']:.3f} net30 {s['net30']:.3f}")
yrs = out["full"]["P"].groupby(out["full"]["P"].index.year).sum()
print("   corrected gross P&L by year:", {k: round(v * 100, 2) for k, v in yrs.items()})
C = Hf.shift(2).fillna(0) * out["full"]["R0"]
print("   corrected IGR holdout P&L:", float(C["IGR"].loc[lo:hi].sum()), "; IGR by year",
      C["IGR"].loc[lo:hi].groupby(C.loc[lo:hi].index.year).sum().round(5).to_dict())
pickle.dump(dict(Tf=Tf, Hf=Hf, Rf=Rf, R0f=out["full"]["R0"], Pf=out["full"]["P"], TUf=out["full"]["TU"]), open(S + "corrected.pkl", "wb"))
