"""Lane A scratch: simulate the REPAIR on a copy. Inject order rows from the order map,
then advance from the durable record. Scratch only."""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.argv = ["x"]
exec(open(Path(__file__).with_name("replay.py")).read().split('print("=== STEP 1')[0])
from ops.ledger import ORDER_COLUMNS, _concat  # noqa

class ReplayLedger(LongOnlySleeveLedger):
    """Orders come from the order map (what was TRANSMITTED); never re-derived."""
    def _make_orders(self, *a, **k):
        return []

def inject(lg, decision_dates):
    om = pd.read_csv(PROD / "ops/books/cef_live/_ibkr_shadow/_order_map.csv")
    om = om[(om.sleeve == "cef_discount") & om["asof"].astype(str).str[:10].isin(decision_dates)]
    close = px.pivot(index="date", columns="ticker", values="close")
    rows = []
    for r in om.itertuples():
        d = pd.Timestamp(str(r[1])[:10]); delta = float(r.qty) * (1 if r.action == "BUY" else -1)
        rows.append({"decision_date": d, "ticker": r.instrument, "current_shares": np.nan,
                     "target_shares": np.nan, "delta_shares": delta,
                     "decision_price": float(close.loc[d, r.instrument]), "target_weight": np.nan,
                     "reason": f"order_map id={r.order_id}", "status": "open", "fill_date": pd.NaT})
    lg.orders = _concat(lg.orders, rows, ORDER_COLUMNS); lg.save()
    return len(rows)

def run(tag, decision_dates, days):
    st = fresh(tag); lg = ReplayLedger(st)
    n = inject(lg, decision_dates); lg = ReplayLedger(st)
    print(f"--- {tag}: injected {n} order row(s) for decisions {decision_dates}")
    for day in days:
        try:
            r = adv(lg, day, record_for(st, day), [])
            print(f"   {day}: ok n_fills={r['n_fills']} nav={r['nav']:,.2f}")
        except Exception as e:
            print(f"   {day}: {type(e).__name__}: {str(e)[:140]}"); break
    return st, lg

print("=== STEP 3a: NAIVE repair (only the 09-11 decision's orders made representable)")
run("naive", ["2026-09-11"], ["2026-09-14", "2026-09-15"])
print("\n=== STEP 3b: FULL repair (both transmitted sets injected), day by day through 09-18")
st, lg = run("full", ["2026-09-11", "2026-09-14"], ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"])
lg = ReplayLedger(st)
print("\norders:"); print(lg.orders[["decision_date","ticker","delta_shares","status","fill_date"]].to_string(index=False))
print("\ntrades:"); print(lg.trades[["fill_date","ticker","side","shares","fill_price","exec_ids"]].to_string(index=False))
print("\nnav:"); print(lg.nav[["date","nav","cash","invested","cost_usd","traded_usd","daily_return","decision"]].to_string(index=False))
held = lg.held_shares()
epoch = pd.read_csv(SRC / "positions.csv").set_index("ticker")["shares"].to_dict()
bf = pd.read_csv(SRC / "broker_fills.csv"); bf = bf[bf.fill_date >= "2026-09-12"]
bf["s"] = bf.qty * bf.side.map({"BUY": 1, "SELL": -1}); net = bf.groupby("instrument")["s"].sum().to_dict()
expect = {t: epoch.get(t, 0) + net.get(t, 0) for t in set(epoch) | set(net)}
bad = {t: (held.get(t, 0), expect[t]) for t in expect if abs(held.get(t, 0) - expect[t]) > 1e-9}
print("\nINVARIANT epoch + sum(post-epoch executions) == replayed positions:", "HOLDS" if not bad else bad)
print("replayed positions:", {t: held[t] for t in sorted(held)})
