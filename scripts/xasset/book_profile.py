"""Zero-trial description of the DEPLOYED book: its daily gross P&L (live band policy,
shift(2) via evaluate) correlated with raw ETF returns, and the gap between its
price-return and total-return P&L (= the distribution leg paper does not credit).
No new signal is constructed or scored.
INPUT PANELS. `data/rv/etf_ohlc*.parquet`, `data/rv/etf_panel.parquet` and
`data/riskfree_daily.parquet` were staged before the 2026-09-28 clean slate. The
`data/rv/` fetchers were restored on 2026-10-11 (`scripts/rv/stage_ohlc.py`,
`stage_ohlc_extended.py`, `stage_universe.py`; source notes in docs/REFERENCES.md
§8) and the panels rebuilt: yfinance up to their old last dates, Alpaca after.
`data/riskfree_daily.parquet` still has no fetcher; CLAUDE.md requires one, so
restore it before any TRIAL uses that panel.
This script is a zero-trial description and runs on them as they stand; it prints
each panel's last date. Written 2026-10-08 for results/cef/RESEARCH_AGENDA_2026-10-08.md.
"""
import sys
from pathlib import Path
R0 = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, R0); sys.path.insert(0, R0 + "/scripts/cef")
import numpy as np, pandas as pd
from band_frontier import build_targets, band_gross_capped, evaluate, total_returns
from spec import BAND_WIDTH, MAX_GROSS_STRESS
T, R = build_targets()
# The live v7 policy: band to edge, gross-capped (spec max_gross_stress), as the
# sleeve trades it. A missing cap raises rather than silently trading uncapped.
if MAX_GROSS_STRESS is None:
    raise RuntimeError('spec has no max_gross_stress; the live book is gross-capped')
H = band_gross_capped(T, BAND_WIDTH, MAX_GROSS_STRESS)
first = H.abs().sum(axis=1).gt(0).idxmax()  # the book's first position (pre-2013 is flat, CLAUDE.md landmine 8)
print('book first position', first.date())
px = evaluate(H, R)["pnl"]
tr = evaluate(H, total_returns(R))["pnl"]
print("book P&L span", px.index.min().date(), px.index.max().date())
eras = [("2005-09","2005","2009"),("2010-14","2010","2014"),("2015-19","2015","2019"),("2020-22","2020","2022"),("2023-26","2023","2026")]
print("era  price_ret_ann  total_ret_ann  dist_leg_ann(total-price)")
for lab,a,b in eras:
    p=px.loc[a:b]; t=tr.loc[a:b]
    print(f"{lab}  {p.mean()*252:+.4f}  {t.mean()*252:+.4f}  {(t.mean()-p.mean())*252:+.4f}")
e = pd.read_parquet(R0 + "/data/rv/etf_panel.parquet")
W = e.pivot(index="date", columns="ticker", values="ret_total")
X = pd.DataFrame({k: W[k] for k in ["TLT","IEF","SPY","HYG","LQD"]})
X["SPY_minus_IEF"] = W["SPY"] - W["IEF"]
df = pd.concat([tr.rename("book")], axis=1).join(X, how="inner").dropna()
df = df[df.index >= first]  # flat pre-first-position days would dilute every correlation
print("etf_panel last date", e["date"].max()); print("overlap", df.index.min().date(), df.index.max().date(), len(df))
print("same-day corr of book total-return P&L with:"); print(df.corr()["book"].drop("book").round(3).to_string())
for lab,a,b in [("fit <2023",str(first.date()),"2022"),("2023-26","2023","2026")]:
    d=df.loc[a:b]; print(lab, "corr:", d.corr()["book"].drop("book").round(3).to_dict())
q = df["book"].quantile(0.05)
w = df[df["book"] <= q]
print("on the book worst-5pct days n=", len(w), "mean same-day return, bp:"); print((w.drop(columns="book").mean()*1e4).round(1).to_string())
print("unconditional mean, bp:"); print((df.drop(columns="book").mean()*1e4).round(1).to_string())
# monthly aggregation: correlation of the book's monthly P&L with monthly ETF returns
m = df.resample("ME").sum()
print("monthly corr:", m.corr()["book"].drop("book").round(3).to_dict())
