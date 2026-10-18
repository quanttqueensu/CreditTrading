"""REPORT-ONLY: (a) IGR 2026-08-20 at $0.18 instead of $0.06; (b) the yfinance leg re-built on Alpaca raw closes;
(c) yfinance ex-dates against CRSP ex-dates, 2023-24; (d) IGR's CRSP-leg distribution basis."""
import sys, json, pickle; sys.dont_write_bytecode = True
W = "/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/.claude/worktrees/trial-c4"
sys.path.insert(0, W)
import numpy as np, pandas as pd
from scripts.cef import c4_families as c4
from scripts.cef import band_frontier as bf
S = "/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/9491f9f2-8a08-4ed2-8837-1fbdbf0ca22e/scratchpad/c4_review/"
d = pickle.load(open(S + "repro.pkl", "rb")); f = pickle.load(open(S + "corrected.pkl", "rb"))
UH, H = d["UH"], d["H"]; held = H.shift(2).fillna(0.0); lo, hi = c4.HOLDOUT_START, c4.HOLDOUT_END
def st(P, TU): s = c4.row_stats(P.loc[lo:hi], TU.loc[lo:hi]); return f"SR {s['sr']:.3f} net5 {s['net5']:.3f} net15 {s['net15']:.3f} net30 {s['net30']:.3f}"
TU = d["TU"]
# (a) the other reading of 2026-08-20
p_prev = 4.73   # the panel's IGR close of 2026-08-19 (checked below)
px = pd.read_parquet(c4.FAM_DIR / "cef_prices.parquet"); px["date"] = pd.to_datetime(px["date"])
pp = px[(px.ticker == "IGR") & (px.date == "2026-08-19")]["close"].iloc[0]; assert abs(pp - p_prev) < 1e-6
dd = pd.Timestamp("2026-08-20"); bump = (0.18 - 0.06) / pp
for lab, R0 in (("declared", d["R0"]), ("IGR-corrected", f["R0f"])):
    R1 = R0.copy(); R1.loc[dd, "IGR"] += bump
    P1 = (held * R1).sum(axis=1)
    print(f"(a) {lab}: 08-20 at $0.06 -> {st((held*R0).sum(axis=1), TU)};  at $0.18 -> {st(P1, TU)}  (IGR held {held.loc[dd,'IGR']:+.5f}, "
          f"P&L change {held.loc[dd,'IGR']*bump*100:+.4f}% of capital)")
# (b) Alpaca raw closes for the yfinance leg
b = pd.read_parquet(c4.ALP_POOL); b["date"] = pd.to_datetime(b["date"])
ac = b[b.adjustment == "raw"].pivot(index="date", columns="ticker", values="close").sort_index()
idx = H.index[(H.index >= c4.YF_START) & (H.index <= hi)]
full_idx = ac.index
rpx = ac.pct_change(fill_method=None)
# Alpaca's raw IGR series crosses the 1:3 reverse split on 2026-09-08: apply the share-count multiplier k = 1/3 there
rpx.loc["2026-09-08", "IGR"] = (1 + rpx.loc["2026-09-08", "IGR"]) / 3.0 - 1
ruled = pd.read_parquet(S + "ruled_actions.parquet")
dist, _ = bf.load_families_actions(S + "ruled_actions.parquet")
# the yield on Alpaca's own raw prior close
prev = ac.shift(1)
amt = dist[dist.ticker.isin(UH)].groupby(["ex_date", "ticker"])["amount"].sum().unstack().reindex(index=idx, columns=UH)
yA = (amt / prev.reindex(index=idx, columns=UH))
lost = int((amt.notna() & yA.isna()).sum().sum())
RA = rpx.reindex(index=idx, columns=UH) + yA.fillna(0.0)
hy = held.loc[idx, UH]
miss = (hy != 0) & RA.isna()
print(f"(b) Alpaca raw-close leg: held fund-days with no Alpaca return: {int(miss.sum().sum())}; ex-dates with no Alpaca prior close: {lost}")
if miss.sum().sum():
    print("    missing:", [(str(a.date()), t) for a, t in miss.stack()[miss.stack()].index[:10]])
R0A = f["R0f"].copy(); R0A.loc[idx, UH] = RA.where(~RA.isna(), f["R0f"].loc[idx, UH])
PA = (held * R0A).sum(axis=1)
print("    yfinance leg on Alpaca raw closes (gaps keep the IGR-corrected panel's return):", st(PA, TU))
yleg = lambda P: c4.row_stats(P.loc[c4.YF_START:hi], TU.loc[c4.YF_START:hi])
print(f"    2025-26 leg only: panel(IGR-corrected) SR {yleg((held*f['R0f']).sum(axis=1))['sr']:.3f}; Alpaca raw closes SR {yleg(PA)['sr']:.3f}; "
      f"declared SR {yleg(d['P'].reindex(H.index).fillna(0))['sr']:.3f}")
dif = (held * (R0A - f["R0f"])).loc[idx].stack(); dif = dif[dif.abs() > 1e-5]
print("    largest fund-day P&L differences Alpaca vs corrected panel (% of capital):", (dif.reindex(dif.abs().sort_values(ascending=False).index).head(6)*100).round(4).to_dict())
# (c) ex-date calendars 2023-24
U = c4.universes(); crsp = c4.crsp_returns(U["pool"]); qr = c4.qqqx_rule(crsp, px)
cx = c4.crsp_ex_dates(crsp, qr, UH); cx = cx[(cx.date >= lo) & (cx.date <= c4.CRSP_END)]
ya = pd.read_parquet(c4.FAM_DIR / "cef_actions.parquet"); ya["date"] = pd.to_datetime(ya["date"])
ya = ya[(ya.dividends > 0) & ya.ticker.isin(UH) & (ya.date >= lo) & (ya.date <= c4.CRSP_END)]
A, B = set(zip(cx.ticker, cx.date)), set(zip(ya.ticker, ya.date))
print(f"(c) 2023-24 ex-dates: CRSP {len(A)}, yfinance {len(B)}, both {len(A & B)}, CRSP only {len(A - B)}, yfinance only {len(B - A)}")
# (d) IGR CRSP-leg distribution basis: (ret - retx) * prc(t-1) on CRSP ex-dates, 2023-24
c = crsp[(crsp.ticker == "IGR")].sort_values("date").copy(); c["pp"] = c["prc"].abs().shift(1)
e = c[(c.date >= lo) & (c.date <= c4.CRSP_END) & (c.ret != c.retx)]
print("(d) IGR CRSP 2023-24: implied amount (ret-retx)*prc(t-1):", sorted(set((e["ret"] - e["retx"]).mul(e["pp"]).round(3))),
      f"on {len(e)} ex-dates; prc range not printed (CRSP is licensed data)")
# (e) pooled NAV change on IGR's 20 holdout ex-dates against other days
nav = pd.read_parquet(c4.FAM_DIR / "cef_nav.parquet"); nav["date"] = pd.to_datetime(nav["date"])
n = nav[nav.ticker == "IGR"].set_index("date")["nav"].sort_index().loc["2024-12-01":"2026-09-04"]
dn = n.diff()
RT = pd.read_csv(c4.RESOLUTION_TABLE, parse_dates=["date"]); ex = RT[RT.ticker == "IGR"]["date"]
on, off = dn.reindex(ex).dropna(), dn.drop(ex, errors="ignore").loc["2025-01-02":]
off = off[off != 0]
print(f"(e) IGR NAV change on its 20 ex-dates: mean {on.mean():+.4f} (n {len(on)}, of which unchanged {int((on==0).sum())}); other days mean "
      f"{off.mean():+.4f}, sd {off.std():.4f}; mean on ex-dates net of other days {on.mean()-off.mean():+.4f} "
      f"(se {off.std()/np.sqrt(len(on)):.4f}) against 0.06 and 0.18")
