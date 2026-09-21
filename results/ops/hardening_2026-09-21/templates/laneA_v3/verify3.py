import sys; from pathlib import Path
src = open(Path(__file__).with_name("verify2.py")).read().split('run("naive"')[0]
exec(src)
print("=== multi-bar catch-up on the CURRENT code: ledger repaired through 09-15, halt cleared late, first armed session asof=09-18")
s, st, lg = run("gap3", ["2026-09-11", "2026-09-14"], ["2026-09-14","2026-09-15"])
del lg._make_orders
print("open orders before:", int((lg.orders.status=="open").sum()), "| last_date:", lg.last_date.date())
try:
    s.place_targets("cef_discount", tg(lg.held_shares(), PHK=500), "2026-09-18", MS(px), execution_record=rec(st, "2026-09-18"))
    print("NO RAISE")
except Exception as e:
    print(type(e).__name__, ":", str(e)[:230])
print("=== same with a 2-bar gap (ledger through 09-16, asof=09-18)")
s, st, lg = run("gap2", ["2026-09-11", "2026-09-14"], ["2026-09-14","2026-09-15","2026-09-16"])
del lg._make_orders
try:
    s.verbose=False
    s.place_targets("cef_discount", tg(lg.held_shares(), PHK=500), "2026-09-18", MS(px), execution_record=rec(st, "2026-09-18"))
    print("NO RAISE; orders:"); print(lg.orders.tail(3)[["decision_date","ticker","delta_shares","status","fill_date"]].to_string(index=False))
except Exception as e:
    print(type(e).__name__, ":", str(e)[:230])
