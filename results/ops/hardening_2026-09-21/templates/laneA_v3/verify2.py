import sys; from pathlib import Path
src = open(Path(__file__).with_name("verify.py")).read().split('print("\\n=== 1.')[0]
exec(src)
from src.deploy.exec_ledger import LongOnlySleeveLedger
OM = pd.read_csv(PROD/"ops/books/cef_live/_ibkr_shadow/_order_map.csv")
close = px.pivot(index="date", columns="ticker", values="close")
def inject(st, dates):
    lg = LongOnlySleeveLedger(st)
    om = OM[(OM.sleeve=="cef_discount") & OM["asof"].astype(str).str[:10].isin(dates)]
    rows = [{"decision_date": pd.Timestamp(str(r[1])[:10]), "ticker": r.instrument, "current_shares": np.nan,
             "target_shares": np.nan, "delta_shares": float(r.qty)*(1 if r.action=="BUY" else -1),
             "decision_price": float(close.loc[pd.Timestamp(str(r[1])[:10]), r.instrument]), "target_weight": np.nan,
             "reason": f"order_map id={r.order_id}", "status": "open", "fill_date": pd.NaT} for r in om.itertuples()]
    lg.orders = _concat(lg.orders, rows, ORDER_COLUMNS); lg.save(); return len(rows)
def run(tag, dates, days, suppress=True):
    s, st = sim(tag); s.verbose = False
    n = inject(st, dates); s, _ = (lambda: (None, None))() if False else (s, None)
    s = Simulator(books_root=st.parent, verbose=False)
    s.register_sleeve("cef_discount", "cef_discount", {"rebalance": spec["rebalance"]}, COSTS, 500000.0, NAMES)
    lg = s.ledger("cef_discount")
    if suppress: lg._make_orders = lambda *a, **k: []
    print(f"--- {tag}: injected {n}")
    for day in days:
        try:
            # HOLD targets == current ledger book, so even un-suppressed _make_orders derives nothing
            s.place_targets("cef_discount", tg(lg.held_shares()), day, MS(px), execution_record=rec(st, day))
            print(f"   {day}: ok trades={len(lg.trades)} last={lg.last_date.date()}")
        except Exception as e:
            print(f"   {day}: {type(e).__name__}: {str(e)[:110]}"); break
    return s, st, lg
run("naive", ["2026-09-11"], ["2026-09-14", "2026-09-15"])
s, st, lg = run("full", ["2026-09-11", "2026-09-14"], ["2026-09-14","2026-09-15","2026-09-16","2026-09-17","2026-09-18"])
held = lg.held_shares(); print("positions:", {t: held[t] for t in sorted(held)})
print(lg.trades[["fill_date","ticker","side","shares","fill_price","exec_ids"]].to_string(index=False))
print("exec ids unique:", lg.trades.exec_ids.is_unique, "n=", len(lg.trades))
print(lg.orders[["decision_date","ticker","delta_shares","status","fill_date"]].to_string(index=False))
print("\n=== stop-date claim: ledger through 09-18, Monday session asof=09-18 (un-suppressed _make_orders, a target that wants a trade)")
del lg._make_orders
n0 = len(lg.orders)
s.verbose = True
s.place_targets("cef_discount", tg(lg.held_shares(), PHK=500), "2026-09-18", MS(px), execution_record=rec(st, "2026-09-18"))
print("new order rows:", len(lg.orders) - n0)
print("\n=== same, but replay stopped at 09-17")
s2, st2, lg2 = run("thru17", ["2026-09-11", "2026-09-14"], ["2026-09-14","2026-09-15","2026-09-16","2026-09-17"])
del lg2._make_orders; n0 = len(lg2.orders)
s2.place_targets("cef_discount", tg(lg2.held_shares(), PHK=500), "2026-09-18", MS(px), execution_record=rec(st2, "2026-09-18"))
print("new order rows:", len(lg2.orders) - n0, lg2.orders.tail(1)[["decision_date","ticker","delta_shares","status"]].to_dict("records"))
