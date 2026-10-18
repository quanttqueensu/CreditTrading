"""Report-only: find one-day spike-and-revert closes in the families price panel (frozen 74)."""
import pandas as pd, numpy as np
R="/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/.claude/worktrees/trial-c4/"
px=pd.read_parquet(R+"data/cef_families/cef_prices.parquet"); px["date"]=pd.to_datetime(px["date"])
nav=pd.read_parquet(R+"data/cef_families/cef_nav.parquet"); nav["date"]=pd.to_datetime(nav["date"])
fz=pd.read_csv(R+"results/cef/c4/c4_universe_frozen_2026-10-14.csv")["ticker"].tolist()
c=px[px.ticker.isin(fz)].pivot_table(index="date",columns="ticker",values="close").sort_index()
n=nav[nav.ticker.isin(fz)].pivot_table(index="date",columns="ticker",values="nav").sort_index()
r=c.pct_change(fill_method=None)
rows=[]
for t in c.columns:
    s=r[t]
    big=s[(s.abs()>0.25)]
    for d,v in big.items():
        i=c.index.get_loc(d)
        nxt=r[t].iloc[i+1] if i+1<len(c) else np.nan
        rows.append(dict(ticker=t,date=d.date(),ret=round(v,4),next_ret=round(nxt,4) if pd.notna(nxt) else None,
                         close_prev=c[t].iloc[i-1],close=c[t].iloc[i],close_next=c[t].iloc[i+1] if i+1<len(c) else None,
                         nav=n[t].get(d,np.nan),nav_prev=n[t].iloc[n.index.get_indexer([d])[0]-1] if d in n.index else np.nan))
df=pd.DataFrame(rows)
pd.set_option("display.width",250); pd.set_option("display.max_rows",500)
print(df.to_string())
