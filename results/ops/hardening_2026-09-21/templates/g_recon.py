"""READ-ONLY reconstruction of the CEF book 2026-09-11 -> last panel date from
epoch positions.csv + broker_fills.csv + data/cef/cef_prices.parquet. Writes nothing."""
import json, pandas as pd, numpy as np
pd.set_option('display.width', 250)
B = '/Users/simonjarvis/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/'
pos = pd.read_csv(B + 'cef_discount/positions.csv')
q0 = pos.set_index('ticker').shares.astype(float)
fills = pd.read_csv(B + 'cef_discount/broker_fills.csv')
fills = fills[fills.fill_date > '2026-09-11'].copy()
fills['sq'] = np.where(fills.side == 'BUY', fills.qty, -fills.qty)
fills['comm'] = fills.note.str.extract(r'commission=([0-9.]+)').astype(float)
after = json.load(open(B + '_desync/cef_discount_2026-09-14.json'))['tag_book_after_fills']
P = pd.read_parquet('/Users/simonjarvis/Desktop/2027/QUANTT/2027/data/cef/cef_prices.parquet')
print('price panel columns:', list(P.columns), 'last date', P.date.max())
P['date'] = pd.to_datetime(P['date'])
P = P[P.ticker.isin(q0.index) & (P.date >= '2026-09-11')]
px = P.pivot_table(index='date', columns='ticker', values='close').sort_index()
divcol = [c for c in P.columns if 'div' in c.lower() or 'dist' in c.lower()]
print('dividend-like columns:', divcol)
div = P.pivot_table(index='date', columns='ticker', values=divcol[0]).sort_index().fillna(0.0) if divcol else px * 0
print('NaN closes in window:', px.isna().sum()[px.isna().sum() > 0].to_dict())
# check 1: epoch + 09-14 fills == broker book adopted by arm() 09-15 08:39
chk = q0.add(fills[fills.fill_date == '2026-09-14'].groupby('instrument').sq.sum(), fill_value=0)
diff = {k: (chk[k], after[k]) for k in chk.index if abs(chk[k] - after[k]) > 1e-9}
print('epoch + 09-14 fills vs tag_book_after_fills mismatches:', diff if diff else 'NONE (17/17 equal)')
# daily reconstruction
q = q0.copy(); nav = 500000.0; rows = []
dates = list(px.index)
pxf = px.ffill()
for i in range(1, len(dates)):
    d, dm = dates[i], dates[i-1]
    hold_pnl = float((q * (pxf.loc[d] - pxf.loc[dm])).sum())
    dist = float((q * div.loc[d]).sum())
    f = fills[fills.fill_date == str(d.date())]
    trade_pnl = float(sum(r.sq * (pxf.loc[d, r.instrument] - r.price) for r in f.itertuples()))
    comm = float(f.comm.sum())
    w_prev = q * pxf.loc[dm] / nav
    nav_new = nav + hold_pnl + dist + trade_pnl - comm
    for r in f.itertuples(): q[r.instrument] += r.sq
    rows.append(dict(date=d.date(), hold_pnl=round(hold_pnl, 2), dist=round(dist, 2), trade_vs_close=round(trade_pnl, 2), comm=round(comm, 2), nav=round(nav_new, 2), ret_bp=round(1e4 * (nav_new / nav - 1), 1), gross_prev=round(float(w_prev.abs().sum()), 4), net_prev=round(float(w_prev.sum()), 4), n_fills=len(f)))
    nav = nav_new
print(pd.DataFrame(rows).to_string(index=False))
last = dates[-1]
mv = q * pxf.loc[last]
print(f'positions after all 8 fills, marked {last.date()}: gross ${mv.abs().sum():,.0f} net ${mv.sum():,.0f}  NAV ${nav:,.2f} -> gross {mv.abs().sum()/nav:.3f}x net {mv.sum()/nav:+.4f}')
print(q.astype(int).to_dict())
