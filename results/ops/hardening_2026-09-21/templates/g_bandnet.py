"""READ-ONLY: net exposure of the research band(T, BAND_WIDTH) book. Writes nothing."""
import sys
sys.path.insert(0,'/Users/simonjarvis/Desktop/2027/QUANTT/2027')
sys.path.insert(0,'/Users/simonjarvis/Desktop/2027/QUANTT/2027/scripts/cef')
import numpy as np, pandas as pd
import band_frontier as bf
from spec import BAND_WIDTH
out = bf.build_targets()
T = out[0] if isinstance(out, tuple) else out
H = bf.band(T, BAND_WIDTH)
net = H.sum(axis=1); gross = H.abs().sum(axis=1)
tn = T.sum(axis=1)
print('band width', BAND_WIDTH, 'panel', T.index.min().date(), '->', T.index.max().date(), 'rows', len(T))
for lab, s in [('full', slice(None)), ('2013+', slice('2013-01-01', None)), ('2023+', slice('2023-01-01', None))]:
    n = net.loc[s]; g = gross.loc[s]; a = n[g > 0]
    print(f'{lab:6s} target|net| max {tn.loc[s].abs().max():.2e}  banded net: mean {a.mean():+.4f} sd {a.std():.4f} min {a.min():+.4f} max {a.max():+.4f}  p1 {a.quantile(.01):+.4f} p99 {a.quantile(.99):+.4f}  |net|>0.10 on {(a.abs()>0.10).mean():.1%} of days, >0.13 on {(a.abs()>0.13).mean():.1%}')
print('last 5 banded net:', net.tail(5).round(4).to_dict())
