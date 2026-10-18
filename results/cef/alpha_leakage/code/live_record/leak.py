import json, sys
import pandas as pd
X = sys.argv[1]; S = f"{X}/vm/cef"
oc = pd.concat([pd.read_parquet('/Users/simonjarvis/prod/quantt-alpaca/data/cef/alpaca_official_close.parquet'),
                pd.read_parquet(f"{X}/vmdata/alpaca_official_close.parquet")]).drop_duplicates(['date','ticker'])
A = {d.strftime('%Y-%m-%d'): g.set_index('ticker')['price'].to_dict() for d, g in oc.groupby('date')}
days = ["2026-09-29","2026-09-30","2026-10-01","2026-10-02","2026-10-05","2026-10-06","2026-10-07","2026-10-08","2026-10-09","2026-10-12","2026-10-13"]
actual = {d: {k:int(v) for k,v in json.load(open(f"{S}/data/{d}/account.json"))['positions']['qty'].items()} for d in days}
def plan_targets(d):
    p = json.load(open(f"{S}/{d}/plan.json"))
    return {s: int(t['target']) for s, t in p['targets'].items() if int(t['target'])}
cause = {"2026-09-29":"cls under-fill (11/13 expired)","2026-09-30":None,"2026-10-01":"HYT skipped (not shortable at send)",
         "2026-10-02":"missed: laptop offline (DNS) at send","2026-10-05":"missed: laptop offline (DNS) at send",
         "2026-10-06":"refused: buying-power gate at decide","2026-10-07":None,"2026-10-08":None,
         "2026-10-09":"refused: gross-stress cap at send","2026-10-12":None,"2026-10-13":"send scale-down + PDO flip deferred"}
intended = {}
for d in days:
    intended[d] = plan_targets(d)
# gap after each day; P&L of gap on next day
rows=[]
for i in range(1,len(days)):
    p, d = days[i-1], days[i]
    gap = {s: intended[p].get(s,0)-actual[p].get(s,0) for s in set(intended[p])|set(actual[p])}
    gap = {s:q for s,q in gap.items() if q}
    pnl = sum(q*(A[d][s]-A[p][s]) for s,q in gap.items())
    gross = sum(abs(q)*A[p][s] for s,q in gap.items()); net = sum(q*A[p][s] for s,q in gap.items())
    rows.append(dict(day=d, gap_from=p, cause=cause[p], gap_gross=round(gross), gap_net=round(net), pnl=round(pnl,2), names=len(gap)))
df = pd.DataFrame(rows)
pd.set_option('display.width',250)
print(df.to_string())
print("total P&L of intended-minus-actual (MODELLED):", round(df.pnl.sum(),2))
print(df.groupby('cause').pnl.sum().round(2))
# the 10-13 end gap (not yet scored)
p="2026-10-13"; gap={s: intended[p].get(s,0)-actual[p].get(s,0) for s in set(intended[p])|set(actual[p])}
print("gap after 10-13:", {s:q for s,q in gap.items() if q}, "gross $", round(sum(abs(q)*A[p][s] for s,q in gap.items()),0), "net $", round(sum(q*A[p][s] for s,q in gap.items()),0))
