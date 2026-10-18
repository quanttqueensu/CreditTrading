"""REPORT-ONLY: inference on the IGR-corrected holdout; NAV-panel spike scan (frozen 74)."""
import sys, pickle; sys.dont_write_bytecode = True
W = "/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/.claude/worktrees/trial-c4"
sys.path.insert(0, W)
import numpy as np, pandas as pd
from scripts.cef import c4_families as c4
from scripts.cef import w4_artifacts as w4
S = "/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/9491f9f2-8a08-4ed2-8837-1fbdbf0ca22e/scratchpad/c4_review/"
d = pickle.load(open(S + "repro.pkl", "rb")); f = pickle.load(open(S + "corrected.pkl", "rb"))
for lab, P in (("declared", d["P"]), ("IGR-corrected", f["Pf"])):
    m, s = c4._boot(P, c4.BOOT_BLOCK)   # (means, sharpes); C4's draws, chunk 500 (merge 2026-10-18)
    print(f"{lab}: mean {P.mean()*1e4:+.3f}bp/day, NW t21 {w4.nw_t(P, 21):.2f}, t5 {w4.nw_t(P, 5):.2f}, boot SR CI "
          f"{np.percentile(s, 2.5):+.2f}..{np.percentile(s, 97.5):+.2f}; worst day {P.min()*100:.2f}% on {P.idxmin().date()}")
nav = pd.read_parquet(c4.FAM_DIR / "cef_nav.parquet"); nav["date"] = pd.to_datetime(nav["date"])
n = nav[nav.ticker.isin(d["UF"])].pivot_table(index="date", columns="ticker", values="nav").sort_index()
r = n.pct_change(fill_method=None)
sp = ((r.abs() > 0.4) & ((r.shift(-1) * r) < 0) & (r.shift(-1).abs() > 0.25)).stack(); sp = sp[sp]
print("NAV one-day spike-and-revert (>40% then reverting >25%) on the 74:", [(str(a.date()), t) for a, t in sp.index])
