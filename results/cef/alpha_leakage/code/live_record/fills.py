import json, glob, os, sys
import pandas as pd
X = sys.argv[1]
S = f"{X}/vm/cef"
oc = pd.concat([pd.read_parquet('/Users/simonjarvis/prod/quantt-alpaca/data/cef/alpaca_official_close.parquet'),
                pd.read_parquet(f"{X}/vmdata/alpaca_official_close.parquet")])
# check the two panels agree on overlap
dup = oc.groupby(['date','ticker'])['price'].nunique()
print("official-close conflicts between laptop and VM panels:", int((dup>1).sum()))
oc = oc.drop_duplicates(['date','ticker']).set_index(['date','ticker'])['price']
rows = []
for d in ["2026-09-29","2026-09-30","2026-10-01","2026-10-07","2026-10-08","2026-10-12","2026-10-13"]:
    a = json.load(open(f"{S}/data/{d}/account.json"))
    fills = [f for f in a['fills'] if f['transaction_time'][:10] == d]
    other = [f for f in a['fills'] if f['transaction_time'][:10] != d]
    if other: print(d, "fills on other dates in snapshot:", len(other))
    for f in fills:
        side = 'sell' if f['side'] in ('sell','sell_short') else 'buy'
        rows.append(dict(date=d, sym=f['symbol'], side=side, rawside=f['side'], qty=int(f['qty']), px=float(f['price']), t=f['transaction_time'][11:19]))
df = pd.DataFrame(rows)
df['A'] = [oc.get((pd.Timestamp(d), s)) for d, s in zip(df.date, df.sym)]
g = df.groupby(['date','sym','side']).apply(lambda x: pd.Series(dict(qty=x.qty.sum(), vwap=(x.qty*x.px).sum()/x.qty.sum(), A=x.A.iloc[0], nfill=len(x), tmin=x.t.min(), tmax=x.t.max()))).reset_index()
g['bp'] = [((v-a)/a if s=='buy' else (a-v)/a)*1e4 for v,a,s in zip(g.vwap,g.A,g.side)]
g['notional'] = g.qty*g.A
g['cost_usd'] = g.bp/1e4*g.notional
pd.set_option('display.width',250)
print(g.to_string())
g.to_csv(f"{X}/fills_by_name.csv", index=False)
def w(x): return (x.bp*x.notional).sum()/x.notional.sum()
print("\nBy day:")
for d, x in g.groupby('date'):
    b, s = x[x.side=='buy'], x[x.side=='sell']
    print(d, f"n={len(x)} notional={x.notional.sum():.0f} all={w(x):+.2f}bp buy={w(b) if len(b) else float('nan'):+.2f} sell={w(s) if len(s) else float('nan'):+.2f} cost_usd={x.cost_usd.sum():+.2f}")
lm = g[g.date>='2026-09-30']
print("\nlate_market days (09-30..10-13): n=", len(lm), "notional", round(lm.notional.sum()), "wavg", round(w(lm),2), "median", round(lm.bp.median(),2), "sd", round(lm.bp.std(),2), "cost", round(lm.cost_usd.sum(),2))
for sd in ('buy','sell'):
    x = lm[lm.side==sd]; print(sd, "n", len(x), "wavg", round(w(x),2), "median", round(x.bp.median(),2), "sd", round(x.bp.std(),2), "mean", round(x.bp.mean(),2), "cost", round(x.cost_usd.sum(),2), "pos", int((x.bp>0).sum()), "zero", int((x.bp==0).sum()), "neg", int((x.bp<0).sum()))
print("\nBy name (late_market):")
print(lm.groupby('sym').apply(lambda x: pd.Series(dict(n=len(x), notional=round(x.notional.sum()), wbp=round(w(x),1), cost=round(x.cost_usd.sum(),2)))).to_string())
# fill time distribution
print("\nfill time range per day:", df.groupby('date').t.agg(['min','max']).to_string())
