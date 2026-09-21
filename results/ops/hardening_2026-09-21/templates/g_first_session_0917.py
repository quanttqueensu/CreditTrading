"""READ-ONLY. What would the prod sleeve ask for on asof 2026-09-17 against the REAL holdings
(epoch + 8 broker fills), under two NAV bases? Writes nothing, opens no socket."""
import sys, json, math
sys.path.insert(0, '/Users/simonjarvis/prod/QUANTT')
import pandas as pd
from src.deploy.sleeves.cef_discount import CEFDiscountSleeve
from src.deploy.sleeve import MarketState
spec = json.load(open('/Users/simonjarvis/prod/QUANTT/ops/specs/cef_discount.frozen.json'))
q = {'AWF': 1288, 'BIT': 6842, 'DSL': 3720, 'HYT': 3210, 'JFR': -8720, 'MHD': -8741, 'MQY': -1565, 'NAD': -5237, 'NEA': -10672, 'NVG': -4679, 'NZF': -271, 'PCN': 720, 'PDI': 3746, 'PDO': 6402, 'PFN': 5280, 'PHK': 8478, 'PTY': 630}
P = pd.read_parquet('/Users/simonjarvis/prod/QUANTT/data/cef/cef_prices.parquet'); P['date'] = pd.to_datetime(P['date'])
px = P[P.date == '2026-09-17'].set_index('ticker').close
for nav in (500000.0,):
    s = CEFDiscountSleeve(spec, 500000.0)
    ms = MarketState(asof=pd.Timestamp('2026-09-17'), prices=pd.DataFrame(), holdings={k: float(v) for k, v in q.items()}, extras={'sleeve_nav': nav})
    t = s.target_positions(pd.Timestamp('2026-09-17'), ms)
    tot = 0.0; n = 0; post = dict(q)
    print(f'--- NAV base ${nav:,.2f}')
    for x in t:
        if x.qty is not None: continue
        if x.weight is None:
            tq = 0
        else:
            mag = math.floor(nav * abs(x.weight) / px[x.instrument]); tq = -mag if x.weight < 0 else mag
        d = tq - q[x.instrument]
        if d:
            n += 1; tot += abs(d) * px[x.instrument]; post[x.instrument] = tq
            print(f'   {x.instrument} held {q[x.instrument]:>7} -> target {tq:>7}  delta {d:+6d}  ${abs(d)*px[x.instrument]:>9,.0f}   ({x.reason})')
    mv = pd.Series(post) * px
    print(f'   {n} orders, ${tot:,.0f} traded = {100*tot/nav:.2f}% of NAV; post-trade gross ${mv.abs().sum():,.0f} ({mv.abs().sum()/nav:.3f}x) net ${mv.sum():,.0f} ({mv.sum()/nav:+.4f})')
