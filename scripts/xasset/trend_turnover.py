"""Turnover only (no P&L) of a MOP-style 12m-sign, vol-scaled trend target on the
FI/credit ETF basket, through the harness's own calendar() and evaluate() turn
definition. Purpose: cost-drag arithmetic against the 5/15/30bp grid. Fit period only.
INPUT PANELS. `data/rv/etf_ohlc*.parquet`, `data/rv/etf_panel.parquet` and
`data/riskfree_daily.parquet` were staged before the 2026-09-28 clean slate; their
fetchers (`scripts/rv/stage_ohlc.py`, `stage_ohlc_extended.py`) exist only at tag
`pre-clean-slate`. CLAUDE.md requires a fetcher for anything fetched, so restore
them (with a docs/REFERENCES.md source note) before any TRIAL uses these panels.
This script is a zero-trial description and runs on them as they stand; it prints
each panel's last date. Written 2026-10-08 for results/cef/RESEARCH_AGENDA_2026-10-08.md.
"""
import sys, numpy as np, pandas as pd
from pathlib import Path
REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, REPO)
from scripts.cef.band_frontier import calendar
from scripts.cef.spec import VOL_TARGET
e = pd.concat([pd.read_parquet(f"{REPO}/data/rv/etf_ohlc.parquet"), pd.read_parquet(f"{REPO}/data/rv/etf_ohlc_extended.parquet")]).drop_duplicates(["date","ticker"])
e["date"] = pd.to_datetime(e["date"])
r = e.pivot_table(index="date", columns="ticker", values="ret_total").sort_index()
tk = ["HYG","LQD","IEF","TLT","EMB","PFF","MUB","BKLN","SHY","CWB"]
x = r[tk]
sig = np.sign(np.log1p(x).rolling(252).sum())
vol = x.rolling(63).std()*np.sqrt(252)
n = sig.notna().sum(axis=1).replace(0, np.nan)
# equal risk per asset, each asset at VOL_TARGET/sqrt(n) ex-ante (ignores correlation: a gross upper bound)
T = (sig * (VOL_TARGET/np.sqrt(n)).values[:,None] / vol).fillna(0.0)
T = T.loc["2008-01-01":"2022-12-30"]
for k in [1, 21]:
    H = calendar(T, k)
    turn = H.diff().abs().sum(axis=1).fillna(0).sum()*252/len(H)
    gross = H.abs().sum(axis=1).mean()
    print(f"calendar {k:>2}: turn/yr {turn:.2f}  mean gross {gross:.2f}  cost drag at 5/15/30bp: {turn*5:.0f}/{turn*15:.0f}/{turn*30:.0f} bp/yr")
print("VOL_TARGET from spec:", VOL_TARGET)
print("--- without SHY ---")
tk2 = [t for t in tk if t != "SHY"]
T2 = (sig[tk2] * (VOL_TARGET/np.sqrt(sig[tk2].notna().sum(axis=1))).values[:,None] / vol[tk2]).fillna(0.0).loc["2008-01-01":"2022-12-30"]
print("median per-asset 63d vol (ann) over fit:", (vol[tk].loc["2008":"2022"].median()).round(3).to_dict())
for k in [1, 21]:
    H = calendar(T2, k)
    turn = H.diff().abs().sum(axis=1).fillna(0).sum()*252/len(H)
    print(f"calendar {k:>2}: turn/yr {turn:.2f}  mean gross {H.abs().sum(axis=1).mean():.2f}  p95 gross {H.abs().sum(axis=1).quantile(.95):.2f}  drag 5/15/30: {turn*5:.0f}/{turn*15:.0f}/{turn*30:.0f} bp/yr")
