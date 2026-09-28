import sys; from pathlib import Path
src = open(Path(__file__).with_name("verify.py")).read().split('print("\\n=== 1.')[0]
exec(src)
print("=== 'clear the halt and do nothing else': prod ledger as it stands, first armed session asof=2026-09-18, targets = HOLD the broker-true book")
s, st = sim("clearonly"); s.verbose = False; lg = s.ledger("cef_discount")
truth = dict(lg.held_shares()); 
for k, v in dict(AWF=-638, JFR=301+1446, NEA=904, PDO=-909, PFN=604+3121, PHK=1389).items(): truth[k] += v
try:
    s.place_targets("cef_discount", tg(truth), "2026-09-18", MS(px), execution_record=rec(st, "2026-09-18"))
    print("NO RAISE")
except Exception as e:
    print(type(e).__name__, ":", str(e)[:200])
