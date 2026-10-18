import pandas as pd, numpy as np
R='/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027/'
P=pd.read_parquet(R+'data/cef/cef_prices.parquet'); N=pd.read_parquet(R+'data/cef/cef_nav.parquet')
D=pd.read_parquet(R+'data/cef/cef_distributions.parquet')
U=['AWF','BIT','DSL','HYT','JFR','MHD','MQY','PCN','PDI','PDO','PFN','PHK','PTY']
P=P[P.ticker.isin(U)]; N=N[N.ticker.isin(U)]
d=P.merge(N,on=['date','ticker'],how='inner'); d['date']=pd.to_datetime(d.date)
px=d.pivot_table(index='date',columns='ticker',values='close'); nav=d.pivot_table(index='date',columns='ticker',values='nav')
D['ex_date']=pd.to_datetime(D.ex_date); D=D[D.ticker.isin(U)]
# log returns of price and nav, around ex-dates
rp=np.log(px).diff(); rn=np.log(nav).diff()
rows=[]
for _,r in D.iterrows():
    t,e=r.ticker,r.ex_date
    if e not in px.index or t not in px.columns: continue
    i=px.index.get_loc(e)
    if i<2 or i+2>=len(px.index): continue
    pp=px[t].iloc[i-1]
    if not np.isfinite(pp): continue
    y=r.amount/pp
    rows.append(dict(t=t,e=e,y=y, rp_m1=rp[t].iloc[i-1], rp0=rp[t].iloc[i], rp1=rp[t].iloc[i+1], rn_m1=rn[t].iloc[i-1], rn0=rn[t].iloc[i], rn1=rn[t].iloc[i+1]))
X=pd.DataFrame(rows).dropna()
X['era']=np.where(X.e>='2020-01-01','2020+','pre2020')
# regress the nav return on day offsets onto -yield: slope ~1 on the day NAV goes ex
for era,g in X.groupby('era'):
    print(era, len(g), 'mean yield %.4f'%g.y.mean())
    for c in ['rp_m1','rp0','rp1','rn_m1','rn0','rn1']:
        b=np.polyfit(-g.y, g[c],1)[0]
        print(f'  {c}: mean {g[c].mean()*1e4:+7.1f}bp  slope on -yield {b:+.2f}')
# by ticker, recent (2024+)
Y=X[X.e>='2024-01-01']
print('2024+ by ticker: slope of nav ret on -y at day0, day+1; price day0')
for t,g in Y.groupby('t'):
    if len(g)<5: continue
    print(t, len(g), ' nav0 %+.2f nav+1 %+.2f px0 %+.2f'%(np.polyfit(-g.y,g.rn0,1)[0], np.polyfit(-g.y,g.rn1,1)[0], np.polyfit(-g.y,g.rp0,1)[0]),
          ' mean nav0 %+.1fbp nav+1 %+.1fbp y %.1fbp'%(g.rn0.mean()*1e4,g.rn1.mean()*1e4,g.y.mean()*1e4))
print('--- medians and robust')
for era,g in X.groupby('era'):
    print(era, {c: round(g[c].median()*1e4,1) for c in ['rp_m1','rp0','rp1','rn_m1','rn0','rn1']}, 'y med', round(g.y.median()*1e4,1))
# fraction of ex-dates where NAV drop is on day 0 vs day +1 (|rn + y| smaller)
X['nav_on0']= (X.rn0+X.y).abs() < (X.rn1+X.y).abs()
X['px_on0']= (X.rp0+X.y).abs() < (X.rp1+X.y).abs()
X['yr']=X.e.dt.year
print(X.groupby('yr')[['nav_on0','px_on0']].mean().tail(12))
print(X[X.yr>=2025].groupby('t')[['nav_on0','px_on0']].mean())
