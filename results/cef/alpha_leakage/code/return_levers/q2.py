"""Q2: cash on collateral, LIVE policy. Cash line kept SEPARATE; it is not alpha.
cash/equity on return day t uses the weights that earned day t: H.shift(2) (as evaluate()).
  with short proceeds credited:  1 - sum(w)          (Reg T credit balance / equity)
  excl. short proceeds:          1 - sum(w+)          (equity not spent on longs)"""
import numpy as np, pandas as pd
import common as c
bf = c.bf
d = c.live(); Rt, Hc = d["Rt"], d["Hc"]
pnl = bf.evaluate(Hc, Rt)["pnl"]
Hl = Hc.shift(2).fillna(0.0)
cash_all = 1 - Hl.sum(axis=1)
cash_free = 1 - Hl.clip(lower=0).sum(axis=1)
e = pd.read_parquet(c.REPO / "data/etf_daily.parquet"); e = e[e.ticker == "BIL"].set_index("date")["ret_total"]
p = pd.read_parquet(c.REPO / "data/rv/etf_panel.parquet"); p = p[p.ticker == "BIL"].set_index("date")["ret_total"]
rf = pd.read_parquet(c.REPO / "data/riskfree_daily.parquet").set_index("date")["rf_daily"]
print("BIL etf_daily", e.index.min().date(), e.index.max().date(), " etf_panel", p.index.min().date(), p.index.max().date(), " DGS3MO rf", rf.index.min().date(), rf.index.max().date())
j = pd.concat([e.rename("a"), p.rename("b")], axis=1).dropna()
print("BIL etf_daily vs etf_panel: n", len(j), "max |diff| bp", round((j.a-j.b).abs().max()*1e4, 3), " ann mean diff bp", round((j.a-j.b).mean()*252*1e4, 2))
bil = e.reindex(pnl.index); rfa = rf.reindex(pnl.index)
rows = [("traded 2013-06-14..", c.TRADED_START, None)] + [(x, a, b) for x, a, b in c.ERAS] + [("last 252d", str(pnl.index[-252].date()), None)]
print(f"\n{'era':<20}{'cash/eq':>8}{'free/eq':>8}{'BIL%/yr':>8}{'BILcov':>7}{'3m T%':>7}{'book%':>7}{'cashBIL':>8}{'book+cash':>10}{'SRbook':>7}{'SR+cash':>8}{'cash(free)':>11}")
for lab, a, b in rows:
    pp = pnl.loc[a:b]; ca = cash_all.loc[a:b]; cf = cash_free.loc[a:b]
    bb = bil.loc[a:b]; cov = bb.notna().mean(); r3 = rfa.loc[a:b]
    m = bb.notna()
    cl = (ca * bb)[m]; clf = (cf * bb)[m]
    tot = (pp + ca * bb)[m]
    print(f"{lab:<20}{ca.mean():8.3f}{cf.mean():8.3f}{bb.mean()*252*100:8.2f}{cov:7.0%}{r3.mean()*252*100:7.2f}{pp[m].mean()*252*100:7.2f}{cl.mean()*252*100:8.2f}{tot.mean()*252*100:10.2f}"
          f"{pp[m].mean()/pp[m].std()*np.sqrt(252):7.2f}{tot.mean()/tot.std()*np.sqrt(252):8.2f}{clf.mean()*252*100:11.2f}")
print("note: SR+cash is an absolute-return ratio, not an alpha Sharpe (the cash line is the bill rate).")
# broker-observed (Alpaca paper probe 2026-10-13, read-only snapshot)
import json
a = json.load(open(c.REPO / "results/ops/alpaca_probe/2026-10-13_cef.json"))["account"]
eq, cash, L, S = (float(a[k]) for k in ("equity", "cash", "long_market_value", "short_market_value"))
print(f"\nAlpaca paper probe {a['balance_asof']} (fetched 2026-10-13): equity {eq:,.0f} cash {cash:,.0f} long {L:,.0f} short {S:,.0f} -> cash/equity {cash/eq:.3f}; (equity-long)/equity {(eq-L)/eq:.3f}; gross/equity {(L-S)/eq:.3f}")
