"""Zero-trial diversification screen: CEF book P&L vs family proxy return streams.
Reports CORRELATIONS ONLY (no proxy mean / Sharpe is printed, so no candidate
strategy is evaluated). Fit period only (< 2023-01-01); the holdout is untouched.
Alignment: every proxy position is decided on data through t and earns t+2
(shift(2)), exactly as evaluate() does for the book.
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
from scripts.cef.band_frontier import build_targets, band_gross_capped, band, evaluate, total_returns
from scripts.cef.spec import BAND_WIDTH, MAX_GROSS_STRESS, UNIVERSE

T, R = build_targets()
Rt = total_returns(R)
cap = MAX_GROSS_STRESS if MAX_GROSS_STRESS is not None else np.inf
H = band_gross_capped(T, BAND_WIDTH, cap)
book = evaluate(H, Rt)["pnl"]
first = H.abs().sum(axis=1).gt(0).idxmax()
print("universe", len(UNIVERSE), "band", BAND_WIDTH, "cap", cap, "book first position", first.date(), "panel last", book.index[-1].date())

e1 = pd.read_parquet(f"{REPO}/data/rv/etf_ohlc.parquet"); e2 = pd.read_parquet(f"{REPO}/data/rv/etf_ohlc_extended.parquet")
e = pd.concat([e1, e2]).drop_duplicates(["date", "ticker"]); e["date"] = pd.to_datetime(e["date"])
r = e.pivot_table(index="date", columns="ticker", values="ret_total").sort_index()
print("etf panel last date", r.index[-1].date())
rf = pd.read_parquet(f"{REPO}/data/riskfree_daily.parquet"); rf["date"] = pd.to_datetime(rf["date"])
rf = rf.set_index("date")["rf_daily"].reindex(r.index).ffill()
x = r.sub(rf, axis=0)  # excess returns

# HY_XS as in the archived stress note: HYG - rf - beta63*(IEF - rf), beta shifted 1d (H7)
def hedged(tk, hedge="IEF"):
    b = (x[tk].rolling(63).cov(x[hedge]) / x[hedge].rolling(63).var()).shift(1)
    return x[tk] - b * x[hedge]
HYXS = hedged("HYG"); IGXS = hedged("LQD")
def vs(s, n=63):  # vol scaler known at t (uses returns through t)
    return 1.0 / (s.rolling(n).std() * np.sqrt(252))
def earn(pos, ret):  # decide at t -> earn t+2
    return (pos.shift(2) * ret)

P = {}
# 1. TS trend, 12m sign, equal risk, FI/credit ETFs
tk1 = [t for t in ["HYG","LQD","IEF","TLT","EMB","PFF","MUB","BKLN","SHY","CWB"] if t in x]
sig = np.sign(np.log1p(x[tk1]).rolling(252).sum())
pos = sig * vs(x[tk1]).clip(upper=50)
P["trend_TS_FI"] = earn(pos, x[tk1]).mean(axis=1)
P["trend_credit_HYXS"] = earn(np.sign(HYXS.rolling(252).sum()) * vs(HYXS), HYXS)
P["trend_rates_IEF"] = earn(np.sign(x["IEF"].rolling(252).sum()) * vs(x["IEF"]), x["IEF"])
# 2. XS momentum 12-1 across sectors (vol-scaled returns, top third minus bottom third)
tk2 = [t for t in ["HYG","LQD","IEF","TLT","EMB","PFF","MUB","BKLN","CWB","MBB","IGSB","SHY"] if t in x]
xv = x[tk2] * vs(x[tk2]).clip(upper=50)
m = np.log1p(x[tk2]).rolling(231).sum().shift(21)
rk = m.rank(axis=1, pct=True)
w = (rk > 2/3).astype(float) - (rk <= 1/3).astype(float)
w = w.where(m.notna())
w = w.div(w.abs().sum(axis=1), axis=0)
P["xs_mom_FI"] = earn(w, xv).sum(axis=1, min_count=1)
# 3. carry proxies (the beta a carry leg would carry): long credit spread, long term premium
P["carry_long_HYXS"] = HYXS * vs(HYXS).shift(2)
P["carry_long_TLTXS"] = x["TLT"] * vs(x["TLT"]).shift(2)
# 5. defensive / bond BAB proxy: risk-parity SHY minus TLT
P["bab_SHY_minus_TLT"] = earn(vs(x["SHY"]), x["SHY"]) - earn(vs(x["TLT"]), x["TLT"])
# 6. equity -> credit: sign(SPY 63d) x HY_XS
P["eq2credit"] = earn(np.sign(x["SPY"].rolling(63).sum()) * vs(HYXS), HYXS)
# 7. quality: HY_XS minus IG_XS, risk-parity (the IG/HY rotation beta)
P["hy_minus_ig"] = earn(vs(HYXS), HYXS) - earn(vs(IGXS), IGXS)
P["SPY_xs"] = x["SPY"]; P["HY_XS_raw"] = HYXS; P["IEF_xs"] = x["IEF"]

df = pd.DataFrame(P)
df["CEF_book"] = book
df = df[(df.index >= first) & (df.index < "2023-01-01")].dropna()
print("fit sample", df.index[0].date(), "..", df.index[-1].date(), "n", len(df))
cols = [c for c in df.columns if c != "CEF_book"]
out = pd.DataFrame(index=cols)
out["rho_daily"] = df[cols].corrwith(df["CEF_book"])
g = (np.arange(len(df)) // 21)
m21 = df.groupby(g).sum()
out["rho_21d"] = m21[cols].corrwith(m21["CEF_book"])
out["n_21d"] = len(m21)
# stress: 21-day windows in the worst quintile of HY_XS
q = m21["HY_XS_raw"] <= m21["HY_XS_raw"].quantile(0.2)
out["rho_21d_HYstress"] = m21[q][cols].corrwith(m21[q]["CEF_book"])
out["n_stress"] = int(q.sum())
pd.set_option("display.width", 200)
print(out.round(3).to_string())
print("CEF book 21d P&L in HY-stress windows (mean, %):", round(100*m21[q]["CEF_book"].mean(), 3), " all windows:", round(100*m21["CEF_book"].mean(), 3))
# second method: Spearman on 21d windows; and the archived note's 63d CRD_MOM definition
print("spearman 21d:"); print(m21[cols].corrwith(m21["CEF_book"], method="spearman").round(3).to_string())
crd63 = (np.sign(HYXS.rolling(63).sum().shift(1)) * HYXS)  # archived definition: sign(sum63 as of t-1) x HY_XS_t
d2 = pd.DataFrame({"crd63": crd63, "book": book}).loc[first:"2022-12-30"].dropna()
print("crd63 (archived CRD_MOM def) daily rho:", round(d2.corr().iloc[0,1],3), "n", len(d2))
# era split of the 21d correlation for the two largest
for a,b in [("2013-06-01","2016-12-31"),("2017-01-01","2019-12-31"),("2020-01-01","2022-12-31")]:
    s = df.loc[a:b]; gg = np.arange(len(s))//21; mm = s.groupby(gg).sum()
    print(a[:4], b[:4], "n21", len(mm), {c: round(mm[c].corr(mm["CEF_book"]),3) for c in ["trend_TS_FI","trend_credit_HYXS","xs_mom_FI","eq2credit","bab_SHY_minus_TLT"]})
