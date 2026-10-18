import json, os, sys, math
import pandas as pd
X = sys.argv[1]; S = f"{X}/vm/cef"
oc = pd.concat([pd.read_parquet('/Users/simonjarvis/prod/quantt-alpaca/data/cef/alpaca_official_close.parquet'),
                pd.read_parquet(f"{X}/vmdata/alpaca_official_close.parquet")]).drop_duplicates(['date','ticker'])
A = {d.strftime('%Y-%m-%d'): g.set_index('ticker')['price'].to_dict() for d, g in oc.groupby('date')}
days = ["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06","2026-10-07","2026-10-08","2026-10-09","2026-10-12","2026-10-13"]
eq = pd.read_csv(f"{S}/equity.csv").set_index('date')
sc = pd.read_csv(f"{S}/scores.csv").set_index('date')
pos_prev = {}
prevday = "2026-09-28"
out = []
cum_shares = {}
for d in days:
    a = json.load(open(f"{S}/data/{d}/account.json"))
    pos = {k: int(v) for k, v in a['positions']['qty'].items()}
    fills = [f for f in a['fills'] if f['transaction_time'][:10] == d]
    # consistency: prev positions + fills == positions
    chk = dict(pos_prev)
    for f in fills:
        sgn = 1 if f['side'] == 'buy' else -1
        chk[f['symbol']] = chk.get(f['symbol'], 0) + sgn*int(f['qty'])
    chk = {k: v for k, v in chk.items() if v}
    mismatch = {k: (chk.get(k,0), pos.get(k,0)) for k in set(chk)|set(pos) if chk.get(k,0) != pos.get(k,0)}
    Ad = A.get(d, {}); Ap = A.get(prevday, {})
    hold = sum(q*(Ad[s]-Ap[s]) for s, q in pos_prev.items())
    fillp = sum((1 if f['side']=='buy' else -1)*int(f['qty'])*(Ad[f['symbol']]-float(f['price'])) for f in fills)
    longv = sum(q*Ad[s] for s, q in pos.items() if q > 0); shortv = sum(q*Ad[s] for s, q in pos.items() if q < 0)
    muni = sum(q*Ad[s] for s, q in pos.items() if s in ('MHD','MQY'))
    tax = sum(q*Ad[s] for s, q in pos.items() if s not in ('MHD','MQY'))
    traded_notional = sum(int(f['qty'])*float(f['price']) for f in fills)
    out.append(dict(date=d, auction=hold+fillp, hold=hold, fill=fillp, long=longv, short=shortv, net=longv+shortv, gross=longv-shortv,
                    muni_net=muni, tax_net=tax, traded=traded_notional, npos=len(pos), mismatch=mismatch,
                    acct_eq=a['account']['equity'], acct_last=a['account']['last_equity'], acct_read=a['read_at_utc'][:16]))
    pos_prev, prevday = pos, d
df = pd.DataFrame(out).set_index('date')
# settled EOD equity = next row's last_equity (Alpaca)
le = eq['last_equity']
settled = {}
for i, d in enumerate(days[:-1]):
    nxt = days[i+1]
    settled[d] = le.get(nxt)
df['settled_eod_eq'] = pd.Series(settled)
df['settled_chg'] = df['settled_eod_eq'].diff()
df.loc['2026-09-29','settled_chg'] = df.loc['2026-09-29','settled_eod_eq'] - 100000.0
df['official_chg'] = [sc.loc[d,'alpaca_equity_change_usd'] if d in sc.index else (eq.loc[d,'equity']-eq.loc[d,'last_equity']) for d in days]
df['official_src'] = ['scores.csv' if d in sc.index else 'equity.csv' for d in days]
df['verify_auction'] = [sc.loc[d,'auction_pnl_usd'] if d in sc.index else None for d in days]
pd.set_option('display.width', 300); pd.set_option('display.max_columns', 40)
print(df[['auction','verify_auction','hold','fill','settled_chg','official_chg','official_src','acct_eq','acct_last','acct_read']].round(2).to_string())
print(df[['long','short','net','gross','muni_net','tax_net','traded','npos','mismatch']].round(0).to_string())
df.to_pickle(f"{X}/pnl.pkl")
