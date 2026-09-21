"""READ-ONLY: account composition from the 16:20 broker snapshots (files) + ledger marks. No broker call."""
import json, glob, pandas as pd, numpy as np
R = '/Users/simonjarvis/prod/QUANTT/ops/books/'
CEF = ["AWF","BIT","DSL","HYT","JFR","MHD","MQY","NAD","NEA","NVG","NZF","PCN","PDI","PDO","PFN","PHK","PTY"]
recon = {'2026-09-14': {'AWF': 1926, 'BIT': 6842, 'DSL': 3720, 'HYT': 3210, 'JFR': -10166, 'MHD': -8741, 'MQY': -1565, 'NAD': -5237, 'NEA': -11576, 'NVG': -4679, 'NZF': -271, 'PCN': 720, 'PDI': 3746, 'PDO': 6402, 'PFN': 2159, 'PHK': 8478, 'PTY': 630}}
post = {'AWF': 1288, 'BIT': 6842, 'DSL': 3720, 'HYT': 3210, 'JFR': -8720, 'MHD': -8741, 'MQY': -1565, 'NAD': -5237, 'NEA': -10672, 'NVG': -4679, 'NZF': -271, 'PCN': 720, 'PDI': 3746, 'PDO': 6402, 'PFN': 5280, 'PHK': 8478, 'PTY': 630}
for d in ('2026-09-15', '2026-09-16', '2026-09-17'): recon[d] = post
snaps = {}
for f in sorted(glob.glob(R + 'cef_live/_broker_archive/*/broker_*.json')):
    j = json.load(open(f)); snaps[j['auction']] = j
    got = {k: j['positions'].get(k, 0.0) for k in CEF}
    exp = recon.get(j['auction'])
    bad = {k: (got[k], exp[k]) for k in CEF if abs(got[k] - exp[k]) > 1e-9} if exp else 'n/a'
    print(j['auction'], j['measured_et'][:19], 'resting', len(j['resting']), 'executions', len(j['executions']), '| CEF names broker vs (epoch+fills):', 'MATCH 17/17' if bad == {} else bad)
# composition on the last snapshot
j = snaps[max(snaps)]; acct = pd.Series(j['positions'], dtype=float)
P = pd.read_parquet('/Users/simonjarvis/Desktop/2027/QUANTT/2027/data/cef/cef_prices.parquet'); P['date'] = pd.to_datetime(P['date'])
cpx = P[P.date == max(snaps)].set_index('ticker').close
marks = {}; book_of = {}
led = {}
for book, root, sleeves in [('phase0', 'phase0_live', ['null_trader']), ('bench', 'benchmarks_live', ['bench_b1_hyg','bench_b3_agg','bench_b4_60_40','bench_b5_shy','bench_b6_ew_credit'])]:
    for s in sleeves:
        p = pd.read_csv(R + f'{root}/_ibkr_shadow/{s}/positions.csv'); p = p[(p.date == p.date.max()) & (p.ticker != 'CASH')]
        for r in p.itertuples():
            marks[r.ticker] = (r.close, r.date); led.setdefault(book, {}); led[book][r.ticker] = led[book].get(r.ticker, 0) + r.shares
rows = []
for sym, qty in acct.items():
    if sym in CEF: px, md, bk = cpx[sym], max(snaps), 'CEF'
    else: px, md = marks[sym]; bk = 'ETF(phase0+bench)'
    rows.append(dict(sym=sym, qty=qty, px=px, mark_date=md, mv=qty * px, bk=bk))
df = pd.DataFrame(rows)
tot = df.mv.abs().sum()
print(f'\naccount snapshot {max(snaps)}: {len(df)} symbols, gross ${tot:,.0f} net ${df.mv.sum():,.0f}  (CEF marks {max(snaps)} panel; ETF marks = ledger closes dated {sorted(set(df[df.bk!="CEF"].mark_date))})')
for bk, g in df.groupby('bk'): print(f'  {bk:20s} gross ${g.mv.abs().sum():>10,.0f} ({100*g.mv.abs().sum()/tot:.1f}%)  net ${g.mv.sum():>10,.0f}')
bench = pd.Series(led['bench']); ph = pd.Series(led['phase0'])
bg = sum(abs(q) * marks[t][0] for t, q in bench.items()); pg = sum(abs(q) * marks[t][0] for t, q in ph.items())
print(f'  of the ETF block, by LEDGER claim: benchmarks gross ${bg:,.0f}, phase0 gross ${pg:,.0f}')
etf = df[df.bk != 'CEF'].set_index('sym')
res = (etf.qty - (bench.reindex(etf.index).fillna(0) + ph.reindex(etf.index).fillna(0)))
res = res[res.abs() > 1e-9]
print('  account minus (phase0+bench ledgers), shares:', res.astype(int).to_dict())
print(f'  residual gross at ledger marks: ${sum(abs(v) * marks[k][0] for k, v in res.items()):,.0f};  ledger-claimed symbols the account lacks:', sorted((set(bench.index) | set(ph.index)) - set(acct.index)))
