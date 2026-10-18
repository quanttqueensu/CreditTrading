import sys; R='/Users/simonjarvis/Downloads/2027/Projects/Quant - PM2027/2027'; sys.path.insert(0,R)
import numpy as np, pandas as pd
from scripts.cef import band_frontier as bf
from scripts.cef.spec import MIN_ADV_USD, MIN_NAMES
p=bf.build_panel()
z,adv=p['z'],p['adv']
elig=(z.notna() & (adv>=MIN_ADV_USD)).sum(axis=1)
print('panel last', z.index[-1].date())
e=elig.loc['2013-06-14':]
print('traded-era days', len(e), 'days with < MIN_NAMES eligible:', int((e<MIN_NAMES).sum()))
for y in range(2019,2027):
    ey=elig.loc[str(y)]
    print(y, 'min', ey.min(), 'p5', ey.quantile(.05), 'median', ey.median(), 'days<6', int((ey<MIN_NAMES).sum()))
print('last 10 days eligible:', elig.tail(10).to_dict())
a=adv.iloc[-1].sort_values(); print('ADV last day ($m):', (a/1e6).round(2).to_dict())
