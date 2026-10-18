"""Q3: effective breadth on the latest panel date. LIVE policy diagnostic.
Covariance: trailing 252 sessions of TOTAL returns ending on the weight date (inclusive;
diagnostic of risk on that day, not a decision input)."""
import json, numpy as np, pandas as pd
import common as c
d = c.live(); Rt, Hc, T = d["Rt"], d["Hc"], d["T"]
U = list(Hc.columns); MUNI = [t for t in U if t in ("MHD", "MQY")]
g = pd.read_parquet(c.REPO / "data/cef/cef_prices.parquet", columns=["ticker", "grp"]).drop_duplicates("ticker").set_index("grp" if False else "ticker")["grp"]
print("groups:", {t: g[t] for t in U})
assert set(MUNI) == {t for t in U if g[t] == "muni"}
def measures(w, end, lab):
    X = Rt.loc[:end].iloc[-252:][U]
    S = X.cov().values * 252; w = np.asarray(w, float)
    var = w @ S @ w
    # (1) weight-scaled covariance M = diag(w) S diag(w)
    M = np.diag(w) @ S @ np.diag(w); lm = np.clip(np.linalg.eigvalsh(M)[::-1], 0, None); sh = lm / lm.sum()
    # (2) book variance on covariance PCs (Meucci)
    ev, E = np.linalg.eigh(S); ev, E = ev[::-1], E[:, ::-1]; p = (E.T @ w) ** 2 * ev / var
    # (3) book variance on correlation PCs (plan_diagnostics.pca convention)
    sd = np.sqrt(np.diag(S)); C = S / np.outer(sd, sd); cv, CE = np.linalg.eigh(C); cv, CE = cv[::-1], CE[:, ::-1]
    ws = w * sd; q = (CE.T @ ws) ** 2 * cv / (ws @ C @ ws)
    # (4) Euler risk contributions by group
    rc = w * (S @ w) / var; mi = [U.index(t) for t in MUNI]
    # (5) R^2 of today's-weight book on the muni-minus-taxable EW spread, same window
    br = X.values @ w; spread = X[MUNI].mean(axis=1) - X[[t for t in U if t not in MUNI]].mean(axis=1)
    r2 = np.corrcoef(br, spread.values)[0, 1] ** 2
    print(f"\n{lab}  (cov window {X.index[0].date()}..{X.index[-1].date()}, n={len(X)})")
    print(f"  gross {np.abs(w).sum():.3f}  net {w.sum():+.3f}  muni net {w[mi].sum():+.3f}  taxable net {w.sum()-w[mi].sum():+.3f}   ex-ante vol {np.sqrt(var)*100:.2f}%")
    print(f"  (1) weight-scaled cov: lambda1 share {sh[0]:.1%}, top3 {sh[:3].round(3).tolist()}, effective bets 1/sum(s^2) {1/np.sum(sh**2):.2f}")
    print(f"  (2) book var on cov PCs: p1..p4 {p[:4].round(3).tolist()}  BR_eff 1/sum(p^2) {1/np.sum(p**2):.2f}   ENB exp(H) {np.exp(-np.sum(p[p>0]*np.log(p[p>0]))):.2f}")
    print(f"  (3) book var on corr PCs: q1..q4 {q[:4].round(3).tolist()}  BR_eff {1/np.sum(q**2):.2f}")
    print(f"      corr PC loadings PC1 {dict(zip(U, CE[:,0].round(2)))}\n      PC2 {dict(zip(U, CE[:,1].round(2)))}")
    print(f"  (4) Euler risk share: muni {rc[mi].sum():.1%}  taxable {1-rc[mi].sum():.1%}   by name {dict(zip(U, rc.round(3)))}")
    print(f"  (5) R^2 of book on muni-minus-taxable EW spread: {r2:.3f}")
    return 1/np.sum(p**2), rc[mi].sum(), sh[0]
end = Hc.index[-1]
measures(Hc.loc[end].values, end, f"MODELLED LIVE held book Hc on {end.date()} (latest panel date)")
measures(T.loc[end].values, end, f"TARGET T on {end.date()}")
a = json.load(open(c.REPO / "results/ops/alpaca_probe/2026-10-13_cef.json"))
eq = float(a["account"]["equity"]); pos = {p["symbol"]: float(p["market_value"]) / eq for p in a["positions"]}
wb = np.array([pos.get(t, 0.0) for t in U])
measures(wb, end, "BROKER positions, Alpaca paper probe 2026-10-13 (cov to latest panel date; weights 18 days later)")
# context: monthly history of the same measures on the modelled held book
rows = []
for dt in Hc.loc["2014":].resample("ME").last().index:
    dd = Hc.index[Hc.index <= dt][-1]; w = Hc.loc[dd].values
    if np.abs(w).sum() == 0: continue
    X = Rt.loc[:dd].iloc[-252:][U]; S = X.cov().values * 252
    var = w @ S @ w; ev, E = np.linalg.eigh(S); p = (E.T @ w) ** 2 * ev / var
    mi = [U.index(t) for t in MUNI]; rc = w * (S @ w) / var
    rows.append((dd, 1/np.sum(p**2), rc[mi].sum()))
H = pd.DataFrame(rows, columns=["date", "br", "muni"]).set_index("date")
for e, a_, b_ in c.ERAS[2:]:
    h = H.loc[a_:b_]; print(f"monthly {e}: BR_eff(cov PCs) median {h.br.median():.2f}  muni Euler share median {h.muni.median():.1%}  p10/p90 {h.muni.quantile(.1):.1%}/{h.muni.quantile(.9):.1%}")
