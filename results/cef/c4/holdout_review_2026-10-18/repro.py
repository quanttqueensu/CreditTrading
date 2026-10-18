"""REPORT-ONLY audit of the committed C4 holdout (CEF trial 52). Not a trial; selects nothing.
Rebuilds the holdout book through the canonical harness (build_targets / band_gross_capped /
evaluate) from the committed inputs, writes ONLY to this scratch dir, and pickles the frames."""
import sys, json, pickle
sys.dont_write_bytecode = True
W = "/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/.claude/worktrees/trial-c4"
sys.path.insert(0, W)
import numpy as np, pandas as pd
from scripts.cef import c4_families as c4
from scripts.cef import band_frontier as bf
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, SPEC_ID
S = "/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/9491f9f2-8a08-4ed2-8837-1fbdbf0ca22e/scratchpad/c4_review/"
print(SPEC_ID, BAND_WIDTH, MAX_GROSS_STRESS)
U = c4.universes(); UF, snap = U["frozen"], U["snap68"]
px, nav = c4.load_panels(U["pool"])
crsp = c4.crsp_returns(U["pool"]); qr = c4.qqqx_rule(crsp, px)
RT = pd.read_csv(c4.RESOLUTION_TABLE, parse_dates=["date"])
excluded = json.loads(c4.EXCLUSIONS_A4.read_text())["excluded"]
UH = [t for t in UF if t not in excluded]
T = c4.build_book(UH)
sess = T.index[T.index <= c4.HOLDOUT_END]
cols = sorted(set(UF) | set(snap))
yfa = pd.read_parquet(c4.FAM_DIR / "cef_actions.parquet"); yfa["date"] = pd.to_datetime(yfa["date"])
ruled = c4.ruled_actions(yfa, RT, excluded)
ruled.to_parquet(S + "ruled_actions.parquet", index=False)
committed = pd.read_parquet(c4.CACHE / "c4_holdout_actions_ruled_2026-10-18.parquet")
print("ruled actions equal the committed cache:", ruled.reset_index(drop=True).equals(committed.reset_index(drop=True)))
cr = c4.crsp_pivot(crsp, cols, sess, qr, "ret", px=px)
alp = c4.alpaca_pool(); fill, fchk = c4.igr_fill(alp, px, sess)
yf = c4.yf_total_returns(px, cols, sess, actions=S + "ruled_actions.parquet")
for d, v in fill.items():
    assert pd.isna(yf.loc[d, "IGR"]); yf.loc[d, "IGR"] = v
R = pd.concat([cr.loc[:c4.CRSP_END], yf.loc[c4.YF_START:]])
H = bf.band_gross_capped(T.loc[:c4.HOLDOUT_END], BAND_WIDTH, MAX_GROSS_STRESS)
R0 = c4.check_held(H, R[UH].reindex(index=H.index), "audit")
r = bf.evaluate(H, R0)
lo, hi = c4.HOLDOUT_START, c4.HOLDOUT_END
P, TU = r["pnl"].loc[lo:hi], r["turn_series"].loc[lo:hi]
Pc = pd.read_parquet(c4.CACHE / "c4_holdout_pnl_2026-10-18.parquet")["c4_holdout_gross_pnl"]
print("days", len(P), "max |P - committed P|", float((P - Pc).abs().max()))
print("headline", c4.row_stats(P, TU))
pickle.dump(dict(T=T, H=H, R0=R0, R=R, yf=yf, cr=cr, UH=UH, UF=UF, snap=snap, fill=fill, fchk=fchk, P=P, TU=TU,
                 pnl=r["pnl"], turn=r["turn_series"]), open(S + "repro.pkl", "wb"))
