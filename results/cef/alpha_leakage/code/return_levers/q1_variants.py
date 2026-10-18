"""Q1 VARIANTS -- REPORT ONLY, FIT PERIOD, NOT EVIDENCE FOR ADOPTION.
The 2023-01-01 holdout stays sealed: T and R are truncated by bf.fit_only BEFORE
any policy (band / cap / evaluate) runs, so no 2023+ P&L for a variant is computed.
build_targets is causal (H7), so truncating its output is exact (FRONTIER_REPRO §B).
Vol target varied by setting bf.VOL_TARGET (the module global build_targets reads);
nothing in the repo is modified."""
import pickle, numpy as np, pandas as pd
import common as c
bf = c.bf
FIT_A = c.TRADED_START
def build(vt):
    p = c.SCR / f"T_vt{vt}.pkl"
    if p.exists(): return pickle.loads(p.read_bytes())
    old = bf.VOL_TARGET; bf.VOL_TARGET = vt
    try:
        T, R = bf.build_targets()
    finally:
        bf.VOL_TARGET = old
    T, R = bf.fit_only(T, R)                     # truncate BEFORE anything else
    p.write_bytes(pickle.dumps((T, R))); return T, R
T6, R6 = build(0.06)
assert T6.index.max() < bf.HOLDOUT_START
Rt = bf.total_returns(R6); assert Rt.index.max() < bf.HOLDOUT_START
def stats(H, a, b, lab):
    r = bf.evaluate(H, Rt); p = r["pnl"].loc[a:b]; t = r["turn_series"].loc[a:b]
    g = H.abs().sum(axis=1).loc[a:b]
    ann, vol = p.mean()*252, p.std()*np.sqrt(252); tu = t.mean()*252
    eq = (1+p).cumprod(); mdd = (eq/eq.cummax()-1).min()
    w5 = p.rolling(5).sum().min()
    print(f"{lab:<44}{ann/vol:6.2f}{ann*100:7.2f}{vol*100:7.2f}{mdd*100:8.2f}{p.min()*100:7.2f}{w5*100:7.2f}{tu:6.1f}{g.mean():6.2f}{g.max():6.2f}"
          + "".join(f"{(ann-tu*k/1e4)/vol:6.2f}" for k in (5,15,30)) + "  |" + "".join(f"{(ann-tu*k/1e4)*100:6.2f}" for k in (5,15,30)))
hdr = f"{'variant (fit period only)':<44}{'SR':>6}{'ann%':>7}{'vol%':>7}{'mdd%':>8}{'wDay%':>7}{'w5d%':>7}{'turn':>6}{'gAvg':>6}{'gMax':>6}{'n5':>6}{'n15':>6}{'n30':>6}  | ann% net 5/15/30"
B, CAP = c.BAND_WIDTH, c.MAX_GROSS_STRESS
books = {"LIVE vt6 cap1.80": bf.band_gross_capped(T6, B, CAP), "vt6 no ceiling": bf.band(T6, B)}
for vt in (0.10, 0.15, 0.20):
    Tv, _ = build(vt); assert Tv.index.equals(T6.index)
    books[f"vt{int(vt*100)} clip2.5 cap1.80 (RegT)"] = bf.band_gross_capped(Tv, B, CAP)
    books[f"vt{int(vt*100)} clip2.5 no ceiling"] = bf.band(Tv, B)
    books[f"vt{int(vt*100)} clip scaled, no ceiling"] = bf.band(T6 * (vt/0.06), B)
for era, a, b in [("FIT traded 2013-06-14..2022-12-30", FIT_A, "2022-12-30"), ("2015-19", "2015", "2019"), ("2020-22", "2020", "2022")]:
    print(f"\n=== {era} -- report only, fit period, not evidence for adoption; TOTAL returns, gross P&L headline; no borrow ===")
    print(hdr)
    for k, H in books.items():
        stats(H, a, b, k)
