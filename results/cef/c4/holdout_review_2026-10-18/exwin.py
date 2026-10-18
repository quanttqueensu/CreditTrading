"""REPORT-ONLY: decompose amendment 3's ex-date window [0,2] (declared and IGR-corrected holdout; fit)."""
import sys, json, pickle; sys.dont_write_bytecode = True
W = "/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/.claude/worktrees/trial-c4"
sys.path.insert(0, W)
import numpy as np, pandas as pd
from scripts.cef import c4_families as c4
S = "/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/9491f9f2-8a08-4ed2-8837-1fbdbf0ca22e/scratchpad/c4_review/"
d = pickle.load(open(S + "repro.pkl", "rb")); f = pickle.load(open(S + "corrected.pkl", "rb"))
UH = d["UH"]; H = d["H"]
U = c4.universes(); px, nav = c4.load_panels(U["pool"]); crsp = c4.crsp_returns(U["pool"]); qr = c4.qqqx_rule(crsp, px)
ruled = pd.read_parquet(S + "ruled_actions.parquet")
cx = c4.crsp_ex_dates(crsp, qr, UH)
exd = pd.concat([cx[cx["date"] <= c4.CRSP_END],
                 ruled.loc[(ruled["dividends"] > 0) & (ruled["date"] >= c4.YF_START) & ruled["ticker"].isin(UH), ["ticker", "date"]]],
                ignore_index=True)
Wm = c4.ex_window_mask(H.index, H.columns, exd)
lo, hi = c4.HOLDOUT_START, c4.HOLDOUT_END
p0 = H.shift(2).abs().sum(axis=1).gt(0).idxmax()
for lab, R0 in (("declared", d["R0"]), ("IGR-corrected", f["R0f"])):
    e = c4.ex_window_split(H, R0, Wm, lo, hi)
    print(f"{lab:<14} holdout: total {e['pnl_total']*100:+.2f}%, in [0,2] {e['pnl_in_window']*100:+.2f}% "
          f"({e['share_in_window']:.1%}), rest {e['pnl_rest']*100:+.2f}%; SR in {e['sr_in_window']:.3f}, rest {e['sr_rest']:.3f}")
ef = c4.ex_window_split(H, d["R0"], Wm, p0, c4.FIT_END)
print(f"fit: share {ef['share_in_window']:.1%} (committed 33.1%)")

held = H.shift(2).fillna(0.0)
R0 = f["R0f"]
C = (held * R0)
Wl = Wm.reindex(index=H.index, columns=H.columns).astype(bool)
# price / distribution split of each held fund-day: CRSP leg ret = retx + (ret - retx); yfinance leg R = (1+rpx)k - 1 + D/P
c_rows = crsp
retx = c4.crsp_pivot(crsp, sorted(set(UH)), H.index[H.index <= hi], qr, "retx", px=px, check_identity=False)
Rx = R0.copy()
Rx.loc[:c4.CRSP_END] = retx.reindex(index=Rx.loc[:c4.CRSP_END].index, columns=Rx.columns).fillna(0.0)
from scripts.cef import band_frontier as bf
dist, sp = bf.load_families_actions(S + "ruled_actions.parquet")
y = bf.distribution_yield(H.index[(H.index >= c4.YF_START) & (H.index <= hi)], list(H.columns), dist=dist,
                          prices=S + "cef_prices_igrfixed.parquet")
Rx.loc[c4.YF_START:hi] = R0.loc[c4.YF_START:hi] - y.reindex(index=R0.loc[c4.YF_START:hi].index, columns=R0.columns)
Dy = R0 - Rx   # the distribution leg on each fund-day
for lab, a, b in (("holdout CRSP leg 2023-24", lo, c4.CRSP_END), ("holdout yfinance leg 2025-26", c4.YF_START, hi),
                  ("fit 2005-22", p0, c4.FIT_END)):
    w = Wl.loc[a:b]; Cw = C.loc[a:b]
    pr = (held * Rx).loc[a:b]; dv = (held * Dy).loc[a:b]
    print(f"\n{lab}: total {Cw.sum().sum()*100:+.2f}%; in window {Cw.where(w,0).sum().sum()*100:+.2f}% "
          f"[price part {pr.where(w,0).sum().sum()*100:+.2f}%, distribution part {dv.where(w,0).sum().sum()*100:+.2f}%]; "
          f"rest {Cw.where(~w,0).sum().sum()*100:+.2f}% [distribution part outside window {dv.where(~w,0).sum().sum()*100:+.2f}%]")
    # by window day k = 0, 1, 2
    for k in range(3):
        wk = c4.ex_window_mask(H.index, H.columns, exd, k=(k, k)).reindex(index=H.index, columns=H.columns).astype(bool).loc[a:b]
        print(f"   day {k}: P&L {Cw.where(wk,0).sum().sum()*100:+.2f}% (price {pr.where(wk,0).sum().sum()*100:+.2f}%, dist "
              f"{dv.where(wk,0).sum().sum()*100:+.2f}%)")
    byf = Cw.where(w, 0).sum().sort_values()
    tot = Cw.where(w, 0).sum().sum()
    print("   window P&L by fund, top 8 +:", {k: round(v*100, 2) for k, v in byf.tail(8)[::-1].items()})
    print("   window P&L by fund, top 5 -:", {k: round(v*100, 2) for k, v in byf.head(5).items()})
    print(f"   top 5 funds' share of window P&L: {byf.tail(5).sum()/tot:.1%}; funds with window P&L: {(byf!=0).sum()}")
# the holdout window P&L: top single fund-days, flags for disputed ex-dates
RT = pd.read_csv(c4.RESOLUTION_TABLE, parse_dates=["date"])
disp = set(zip(RT.ticker, RT.date))
st = C.loc[lo:hi].where(Wl.loc[lo:hi], 0).stack(); st = st[st != 0]
top = st.reindex(st.abs().sort_values(ascending=False).index).head(15)
print("\nlargest holdout window fund-days:"); print((top * 100).round(3).to_string())
# window P&L on fund-days within [0,2] of a DISPUTED ex-date
Wd = c4.ex_window_mask(H.index, H.columns, RT[RT["ticker"].isin(UH)][["ticker", "date"]]).reindex(index=H.index, columns=H.columns).astype(bool)
print(f"\nwindow P&L within [0,2] of the 71 disputed ex-dates: {C.loc[lo:hi].where(Wd.loc[lo:hi],0).sum().sum()*100:+.3f}% "
      f"(distribution part {(held*Dy).loc[lo:hi].where(Wd.loc[lo:hi],0).sum().sum()*100:+.3f}%)")
print("  by fund:", {k: round(v*100, 3) for k, v in C.loc[lo:hi].where(Wd.loc[lo:hi], 0).sum().loc[lambda s: s != 0].items()})
# by calendar month of the window P&L in the holdout
m = C.loc[lo:hi].where(Wl.loc[lo:hi], 0).sum(axis=1)
print("\nholdout window P&L by year:", (m.groupby(m.index.year).sum()*100).round(2).to_dict(),
      " rest by year:", (C.loc[lo:hi].where(~Wl.loc[lo:hi], 0).sum(axis=1).groupby(m.index.year).sum()*100).round(2).to_dict())
pickle.dump(dict(Wl=Wl, Rx=Rx, Dy=Dy, exd=exd), open(S + "exwin.pkl", "wb"))
