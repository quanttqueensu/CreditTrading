"""READ-ONLY: distribution of the target gross (= vol scalar x gross_leverage) from band_frontier.build_targets()."""
import sys
sys.path.insert(0,'/Users/simonjarvis/Desktop/2027/QUANTT/2027'); sys.path.insert(0,'/Users/simonjarvis/Desktop/2027/QUANTT/2027/scripts/cef')
import numpy as np, pandas as pd, band_frontier as bf
from spec import BAND_WIDTH
T, R = bf.build_targets()
g = T.abs().sum(axis=1); g = g[g > 0]
H = bf.band(T, BAND_WIDTH); hg = H.abs().sum(axis=1).reindex(g.index)
for lab, s in [('2013+', g.loc['2013-01-01':]), ('last 252d', g.tail(252)), ('last 63d', g.tail(63))]:
    ch = s.pct_change().abs().dropna()
    print(f'{lab:10s} target gross: mean {s.mean():.3f} median {s.median():.3f} p95 {s.quantile(.95):.3f} max {s.max():.3f} | at cap(>=2.499) {100*(s>=2.499).mean():.1f}% of days | >2.0: {100*(s>2.0).mean():.1f}% | daily |chg| median {100*ch.median():.2f}% p95 {100*ch.quantile(.95):.2f}% max {100*ch.max():.1f}%')
print('banded held gross 2013+: mean %.3f p95 %.3f max %.3f' % (hg.loc['2013-01-01':].mean(), hg.loc['2013-01-01':].quantile(.95), hg.loc['2013-01-01':].max()))
print('last 8 target gross:', g.tail(8).round(3).to_dict())
