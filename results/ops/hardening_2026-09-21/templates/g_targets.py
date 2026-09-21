"""READ-ONLY. Instantiate the PROD sleeve class and compute (a) the unbanded target,
(b) the banded output against the epoch holdings, for given asof. Writes nothing."""
import sys, json, copy
sys.path.insert(0, '/Users/simonjarvis/prod/QUANTT')
import pandas as pd
from src.deploy.sleeves.cef_discount import CEFDiscountSleeve
from src.deploy.sleeve import MarketState
spec = json.load(open('/Users/simonjarvis/prod/QUANTT/ops/specs/cef_discount.frozen.json'))
pos = pd.read_csv('/Users/simonjarvis/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/cef_discount/positions.csv')
epoch_hold = dict(zip(pos.ticker, pos.shares))
desync = json.load(open('/Users/simonjarvis/prod/QUANTT/ops/books/cef_live/_ibkr_shadow/_desync/cef_discount_2026-09-14.json'))
after = desync['tag_book_after_fills']
def run(asof, holdings, nav, band=True):
    sp = copy.deepcopy(spec)
    if not band:
        sp['frozen'].pop('band_width')
    s = CEFDiscountSleeve(sp, 500000.0)
    ms = MarketState(asof=pd.Timestamp(asof), prices=pd.DataFrame(), holdings=holdings, extras={'sleeve_nav': nav})
    return s.target_positions(pd.Timestamp(asof), ms)
for asof in ['2026-09-11', '2026-09-18']:
    t = run(asof, {}, 500000.0, band=False)
    w = {x.instrument: (x.weight or 0.0) for x in t}
    L = sum(v for v in w.values() if v > 0); Sh = sum(v for v in w.values() if v < 0)
    print(f'UNBANDED target asof {asof}: long {L:+.4f} short {Sh:+.4f} net {L+Sh:+.5f} gross {L-Sh:.4f}  reason0={t[0].reason}')
    for k in sorted(w): print(f'   {k} {w[k]:+.4f}')
