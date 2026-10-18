"""REPORT-ONLY: where the families close disagrees with Alpaca's raw close (yfinance leg), and whether
any of those fund-days is held or on an ex-date."""
import sys, pickle; sys.dont_write_bytecode = True
import numpy as np, pandas as pd
W = "/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/.claude/worktrees/trial-c4/"
S = "/private/tmp/claude-501/-Users-simonjarvis-Downloads-2027-Projects-Quant---PM2027-2027/9491f9f2-8a08-4ed2-8837-1fbdbf0ca22e/scratchpad/c4_review/"
d = pickle.load(open(S + "repro.pkl", "rb")); H = d["H"]; held = H.shift(2).fillna(0.0)
px = pd.read_parquet(W + "data/cef_families/cef_prices.parquet"); px["date"] = pd.to_datetime(px["date"])
b = pd.read_parquet(W + "results/cef/c4/_cache_c4/alpaca_bars_c4pool_2024-12-02_2026-09-30.parquet"); b["date"] = pd.to_datetime(b["date"])
ac = b[b.adjustment == "raw"].pivot(index="date", columns="ticker", values="close")
yc = px.pivot_table(index="date", columns="ticker", values="close")
idx = yc.index[(yc.index >= "2025-01-02") & (yc.index <= "2026-09-30")]
cols = d["UF"]
ac, yc = ac.reindex(index=idx, columns=cols), yc.reindex(index=idx, columns=cols)
diff = (yc - ac).where(ac.notna() & yc.notna())
bad = diff.abs().gt(0.005).stack(); bad = bad[bad]
rows = []
for (dt, t) in bad.index:
    rows.append(dict(date=dt.date(), ticker=t, panel=yc.loc[dt, t], alpaca_raw=ac.loc[dt, t], diff=round(diff.loc[dt, t], 4),
                     held_t=round(held.loc[dt, t], 5) if dt in held.index else None,
                     held_t1=round(held.shift(-1).loc[dt, t], 5) if dt in held.index else None))
df = pd.DataFrame(rows)
print(len(df), "disagreeing fund-days (> $0.005)")
print(df.groupby("ticker").size().sort_values(ascending=False).to_string())
pd.set_option("display.width", 200); pd.set_option("display.max_rows", 300)
big = df[df["diff"].abs() > 0.02]
print("\n|diff| > $0.02:\n", big.to_string())
