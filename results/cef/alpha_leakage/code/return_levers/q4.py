"""Q4: the distribution leg of the LIVE book. Trailing distribution yield DY_i(t) =
sum of distributions with ex_date in (t-365d, t] / close_t  -- known at t (no lookahead).
Dist leg = total-return P&L minus price-return P&L = sum_i H_{t-2,i} * y_{i,t} (bf.distribution_yield)."""
import numpy as np, pandas as pd
from scipy.stats import spearmanr
import common as c
bf = c.bf
d = c.live(); R, Rt, Hc = d["R"], d["Rt"], d["Hc"]; U = list(Hc.columns)
y = bf.distribution_yield(R.index, R.columns).reindex_like(R)
Hl = Hc.shift(2).fillna(0.0)
leg = Hl * y                                        # daily per-name distribution cash, signed
dist = pd.read_parquet(c.REPO / "data/cef/cef_distributions.parquet"); dist["ex_date"] = pd.to_datetime(dist["ex_date"])
dist = dist[dist.ticker.isin(U)]
amt = dist.groupby(["ex_date", "ticker"])["amount"].sum().unstack().reindex(columns=U)
P = pd.read_parquet(c.REPO / "data/cef/cef_prices.parquet"); P = P[P.ticker.isin(U)]; P["date"] = pd.to_datetime(P["date"])
px = P.pivot_table(index="date", columns="ticker", values="close").sort_index()[U]
cal = amt.reindex(pd.date_range(min(amt.index.min(), px.index.min()), px.index.max(), freq="D")).fillna(0.0)
ttm = cal.rolling(365, min_periods=1).sum().reindex(px.index)
DY = (ttm / px).reindex(Hc.index)                   # annual trailing yield at t
print("dist panel last ex-date", dist.ex_date.max().date(), "; price panel last", px.index.max().date(), "; book sample end", Hc.index[-1].date())
per = [("traded 2013-06-14..", c.TRADED_START, None), ("fit 2013-06..2022", c.TRADED_START, "2022"), ("2023-26", "2023", None)]
tab = {}
for lab, a, b in per:
    tab[(lab, "avg w")] = Hc.loc[a:b].mean()
    tab[(lab, "DY%")] = DY.loc[a:b].mean() * 100
    tab[(lab, "leg %/yr")] = leg.loc[a:b].mean() * 252 * 100
tab = pd.DataFrame(tab)
print("\nPer name: average signed held weight, average trailing distribution yield, distribution-leg contribution (%/yr of equity)")
print(tab.round(3).to_string())
for lab, a, b in per:
    w, dy = tab[(lab, "avg w")], tab[(lab, "DY%")]
    print(f"{lab}: cross-name Spearman(avg w, avg DY) {spearmanr(w, dy).statistic:+.2f}; sum leg {tab[(lab,'leg %/yr')].sum():+.2f}%/yr; book net yield exposure sum(avg w*DY) {(w*dy).sum():+.2f}%")
# daily: cross-sectional Spearman between held weight and DY; and book net yield exposure
cs, ny = [], []
for dt in Hc.loc[c.TRADED_START:].index:
    w = Hc.loc[dt]; dy = DY.loc[dt]
    m = (w != 0) & dy.notna()
    if m.sum() >= 6:
        cs.append((dt, spearmanr(w[m], dy[m]).statistic))
    ny.append((dt, float((w * dy).sum()) * 100))
cs = pd.Series(dict(cs)); ny = pd.Series(dict(ny))
print("\nDaily: Spearman(held w, DY) across names, and book net yield exposure sum(w*DY) in %/yr of equity")
for lab, a, b in [(e, a_, b_) for e, a_, b_ in c.ERAS[1:]]:
    s, n = cs.loc[a:b], ny.loc[a:b]
    if len(n) == 0: continue
    print(f"  {lab}: Spearman mean {s.mean():+.2f} (share<0 {(s<0).mean():.0%}, n {len(s)})   net yield exp mean {n.mean():+.2f}% (share<0 {(n<0).mean():.0%})")
yr = leg.sum(axis=1).loc[c.TRADED_START:].groupby(lambda t: t.year).sum() * 100
print("\nDistribution leg by calendar year (%):", yr.round(2).to_dict())
print(f"negative years {int((yr<0).sum())} of {len(yr)}")
r252 = leg.sum(axis=1).loc[c.TRADED_START:].rolling(252).sum() * 100
print(f"rolling-252d dist leg: share of windows < 0 {(r252.dropna()<0).mean():.0%}; 2023+ share<0 {(r252.loc['2023':]<0).mean():.0%}; min {r252.min():.2f} max {r252.max():.2f}")
# muni vs taxable split of the leg
mu = ["MHD", "MQY"]
for lab, a, b in per:
    l = leg.loc[a:b].mean() * 252 * 100
    print(f"{lab}: leg from munis {l[mu].sum():+.2f}%/yr, taxable {l.drop(mu).sum():+.2f}%/yr")
