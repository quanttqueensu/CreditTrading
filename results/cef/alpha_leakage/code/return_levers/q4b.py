"""Q4b: is the 2023-26 leg exposure or ex-date timing? leg = sum_i E[w_i y_i]*252
 = static sum_i E[w_i]E[y_i]*252 + timing sum_i Cov(w_i, y_i)*252. And: held weight
 earning the ex-date vs the same name's weight 5-15 sessions either side."""
import numpy as np, pandas as pd
import common as c
bf = c.bf
d = c.live(); R, Hc = d["R"], d["Hc"]
y = bf.distribution_yield(R.index, R.columns).reindex_like(R)
Hl = Hc.shift(2).fillna(0.0)
for lab, a, b in [("traded", c.TRADED_START, None), ("fit 2013-22", c.TRADED_START, "2022"), ("2023-26", "2023", None)]:
    w, yy = Hl.loc[a:b], y.loc[a:b]
    leg = (w*yy).mean()*252*100; st = (w.mean()*yy.mean())*252*100
    print(f"{lab}: leg {leg.sum():+.2f}%/yr = static {st.sum():+.2f} + timing {(leg-st).sum():+.2f}")
# weight on ex-date vs neighbourhood
rows = []
idx = Hl.index
for t in Hl.columns:
    ex = y.index[(y[t] != 0)]
    for dt in ex:
        i = idx.get_loc(dt)
        if i < 20 or i + 20 >= len(idx) or dt < pd.Timestamp(c.TRADED_START): continue
        nb = pd.concat([Hl[t].iloc[i-15:i-4], Hl[t].iloc[i+5:i+16]]).mean()
        rows.append((dt, t, Hl[t].iloc[i], nb, y[t].iloc[i]))
E = pd.DataFrame(rows, columns=["date", "t", "w_ex", "w_nb", "y"]).set_index("date").sort_index()
for lab, a, b in [("traded", None, None), ("fit 2013-22", None, "2022"), ("2023-26", "2023", None)]:
    e = E.loc[a:b]
    print(f"{lab}: n ex-dates {len(e)}  mean w on ex-date {e.w_ex.mean():+.4f}  mean w +/-5..15 sessions {e.w_nb.mean():+.4f}  diff {(e.w_ex-e.w_nb).mean():+.4f}  t {(e.w_ex-e.w_nb).mean()/(e.w_ex-e.w_nb).std()*np.sqrt(len(e)):+.1f}")
