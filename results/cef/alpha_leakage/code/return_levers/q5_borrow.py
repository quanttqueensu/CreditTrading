"""Borrow line, SEPARATE and labelled: IBKR FEE_RATE daily panel [S] (data/cef/cef_borrow_history.parquet,
2021-09-13..2026-09-09), charged on the LIVE book's short weights held each day (shift(2) as evaluate).
Alpaca's real-money borrow fees are unmeasured. Also: kurtosis and worst day of the live book."""
import numpy as np, pandas as pd
import common as c
bf = c.bf
d = c.live(); Rt, Hc = d["Rt"], d["Hc"]
pnl = bf.evaluate(Hc, Rt)["pnl"]
b = pd.read_parquet(c.REPO / "data/cef/cef_borrow_history.parquet"); b["date"] = pd.to_datetime(b["date"])
F = b.pivot_table(index="date", columns="ticker", values="fee_rate_pct").reindex(columns=Hc.columns)
a, z = F.index.min(), F.index.max()
Hl = Hc.shift(2).fillna(0.0).loc[a:z]
Ff = F.reindex(Hl.index).ffill()
miss = Ff.isna() & (Hl < 0)
print("fee window", a.date(), z.date(), " short name-days with no fee:", int(miss.sum().sum()))
sh = (-Hl.clip(upper=0))
drag = (sh * Ff / 100 / 252).sum(axis=1)
p = pnl.loc[a:z]
for lab, s, e in [("2021-09-13..2026-09-09", a, z), ("2023-01..2026-09", "2023", z)]:
    dd, pp, ss = drag.loc[s:e], p.loc[s:e], sh.loc[s:e].sum(axis=1)
    print(f"{lab}: gross P&L {pp.mean()*252*100:.2f}%/yr  borrow {dd.mean()*252*100:.2f}%/yr  avg short book {ss.mean():.2f}x  fee per unit short {dd.mean()*252/ss.mean()*100:.2f}%/yr  SR gross {pp.mean()/pp.std()*np.sqrt(252):.2f} after borrow {(pp-dd).mean()/(pp-dd).std()*np.sqrt(252):.2f}")
print("by name, mean fee % (window) where book short:", (Ff.where(Hl<0)).mean().round(1).to_dict())
te = pnl.loc[c.TRADED_START:]
print(f"live book traded era: excess kurtosis {te.kurt():.1f}  worst day {te.min()*100:.2f}%  on {te.idxmin().date()}  skew {te.skew():.2f}")
