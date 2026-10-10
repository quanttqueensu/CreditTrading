"""Per-name and per-family tradability/liquidity map.

Liquidity is CRSP-only (dsf, last 252 trading days ending 2024-12-31): dollar volume = |prc| * vol.
  adv252 = mean daily $ volume over those 252 days (days with prc & vol present);
  adv63  = mean over the last 63 of them -- the sleeve's own ADV definition
           (src/deploy/sleeves/cef_discount.py:409: (px*vol).rolling(63).mean()), used for the floor test;
  rel_spread = median over the 252 days of (ask-bid)/mid from CRSP closing bid/ask, where 0<bid<ask.
NO return statistic is computed (the non-deployed CEFs are a sealed holdout).
Tradability is the Alpaca snapshot of 2026-10-08 (true on that date only).
"""
import json, sys
import numpy as np, pandas as pd
SCR = sys.argv[1]; FLOOR = float(sys.argv[2])
a = pd.DataFrame(json.load(open(f"{SCR}/alpaca_assets_active_us_equity.json"))).set_index("symbol")
dn = pd.read_parquet(f"{SCR}/crsp_dsenames_alive_20241231.parquet").sort_values("namedt").groupby("permno").tail(1)
tk2perm = dn.drop_duplicates("ticker", keep="last").set_index("ticker").permno
first = pd.read_parquet(f"{SCR}/crsp_first_namedt.parquet").set_index("permno").first_namedt
d = pd.read_parquet(f"{SCR}/crsp_dsf_pool_2024.parquet")
dates = np.sort(d.date.unique())[-252:]
assert pd.Timestamp(dates[-1]) == pd.Timestamp("2024-12-31") and len(dates) == 252
d = d[d.date.isin(dates)].copy()
for c in ("prc", "vol", "bid", "ask"): d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
d["dv"] = d.prc.abs() * d.vol
ok = (d.bid > 0) & (d.ask > d.bid)
d["rs"] = np.where(ok, (d.ask - d.bid) / ((d.ask + d.bid) / 2), np.nan)
last63 = set(dates[-63:])
g = d.groupby("permno")
liq = pd.DataFrame({"adv252": g.dv.mean(), "n_days": g.dv.count(), "rel_spread": g.rs.median(),
                    "adv63": d[d.date.isin(last63)].groupby("permno").dv.mean()})

e = pd.read_parquet(f"{SCR}/etf_classified.parquet")[["symbol", "family", "sub"]]
e = e[e.family.notna()]
e["permno"] = e.symbol.map(tk2perm)
# Ticker reuse guard: an ETF symbol that maps to a NON-ETF CRSP security is a different issuer
# (found 2026-10-08: PINC -> Premier Inc, MCVT -> Mill City Ventures). Unlink, never borrow its history.
shrcd = dn.set_index("permno").shrcd
e.loc[e.permno.map(shrcd).ne(73) & e.permno.notna(), "permno"] = np.nan
c = pd.read_parquet(f"{SCR}/cef_classified.parquet")
RENAME = {"CUBA": "HERZ", "PTMN": "BCIC", "NYMT": "ADAM"}   # CRSP ticker -> current Alpaca symbol
c["crsp_ticker"] = c.symbol
c.loc[c.permno.isna(), "crsp_ticker"] = None
c["symbol"] = c.symbol.replace(RENAME)
c = c[~(c.permno.isna() & c.symbol.isin(RENAME.values()))]       # drop the duplicate 'new listing' rows
c.loc[c.crsp_ticker == "CUBA", "family"] = "cef_taxable_credit"  # now Herzfeld Credit Income Fund (Alpaca name)
c["sub"] = np.where(c.deployed, "deployed13", "")
u = pd.concat([e.assign(crsp_ticker=e.symbol), c[["symbol", "family", "sub", "permno", "crsp_ticker"]]], ignore_index=True)
u["permno"] = u.permno.astype("Int64")
u = u.join(liq, on="permno").join(first.rename("first_crsp"), on="permno")
for f in ("tradable", "shortable", "easy_to_borrow", "exchange", "name"):
    u[f] = u.symbol.map(a[f])
u["at_alpaca"] = u.symbol.isin(a.index)
# CEF ticker reuse: the CRSP fund is gone and the symbol now belongs to another issuer at Alpaca
# (BNY = Bank of New York Mellon; BTA = Beacon Tactical Alternatives Risk ETF). The fund is NOT tradable.
REUSED = ["BNY", "BTA"]
m = u.symbol.isin(REUSED) & u.family.str.startswith("cef")
u.loc[m, ["tradable", "shortable", "easy_to_borrow", "exchange"]] = None
u.loc[m, "at_alpaca"] = False
u["clears_floor"] = u.adv63 >= FLOOR
u.to_parquet(f"{SCR}/universe_map.parquet")
u.to_csv(f"{SCR}/universe_map.csv", index=False)

def agg(s):
    t = s[s.tradable == True]
    adv = s.adv252.dropna()
    ex = t.exchange.value_counts()
    return pd.Series({
        "cand": len(s), "tradable": int((s.tradable == True).sum()),
        "shortable": int(((s.tradable == True) & (s.shortable == True)).sum()),
        "etb": int(((s.tradable == True) & (s.easy_to_borrow == True)).sum()),
        "in_crsp": int(s.adv252.notna().sum()),
        "adv_med_$m": round(adv.median() / 1e6, 2) if len(adv) else np.nan,
        "adv_p25_$m": round(adv.quantile(.25) / 1e6, 2) if len(adv) else np.nan,
        "spread_med_bp": round(s.rel_spread.median() * 1e4, 1) if s.rel_spread.notna().any() else np.nan,
        "clear_floor": int((s.clears_floor & (s.tradable == True)).sum()),
        "first_crsp_min": s.first_crsp.min().date() if s.first_crsp.notna().any() else None,
        "first_crsp_med": s.first_crsp.median().date() if s.first_crsp.notna().any() else None,
        "exch": " ".join(f"{k}:{v}" for k, v in ex.items())})
fam = u.groupby("family").apply(agg)
fam.to_csv(f"{SCR}/family_table.csv")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print("252-day window:", pd.Timestamp(dates[0]).date(), "->", pd.Timestamp(dates[-1]).date(), "| floor", FLOOR)
print(fam.to_string())
