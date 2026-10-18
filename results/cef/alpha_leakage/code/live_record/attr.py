import json, sys
import pandas as pd
X=sys.argv[1]; S=f"{X}/vm/cef"
oc = pd.concat([pd.read_parquet('/Users/simonjarvis/prod/quantt-alpaca/data/cef/alpaca_official_close.parquet'),
                pd.read_parquet(f"{X}/vmdata/alpaca_official_close.parquet")]).drop_duplicates(['date','ticker'])
A = {d.strftime('%Y-%m-%d'): g.set_index('ticker')['price'].to_dict() for d, g in oc.groupby('date')}
days = ["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06","2026-10-07","2026-10-08","2026-10-09","2026-10-12","2026-10-13"]
prev={}; pday="2026-09-28"; rows=[]
for d in days:
    a=json.load(open(f"{S}/data/{d}/account.json"))
    fills=[f for f in a['fills'] if f['transaction_time'][:10]==d]
    per={}
    for s,q in prev.items(): per[s]=per.get(s,0)+q*(A[d][s]-A[pday][s])
    for f in fills:
        sg=1 if f['side']=='buy' else -1; s=f['symbol']
        per[s]=per.get(s,0)+sg*int(f['qty'])*(A[d][s]-float(f['price']))
    per['date']=d; rows.append(per)
    prev={k:int(v) for k,v in a['positions']['qty'].items()}; pday=d
df=pd.DataFrame(rows).set_index('date').fillna(0)
df['MUNI']=df[['MHD','MQY']].sum(axis=1); df['TAX']=df.drop(columns=['MHD','MQY','MUNI']).sum(axis=1); df['ALL']=df.MUNI+df.TAX
pd.set_option('display.width',250)
print(df.round(0).to_string())
print(df.sum().round(0).to_string())
