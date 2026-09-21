"""Verifier scratch: does the adapter transmit a leg the shadow ledger writes no order for?
Real IBKRBroker.place_targets, stub IB, scratch copy of prod's epoch ledger, EMPTY durable fill file.
No broker, no network; halt writer intercepted."""
import json, sys, math
from pathlib import Path
import pandas as pd
REPO = Path("/Users/simonjarvis/Desktop/2027/QUANTT/2027"); sys.path.insert(0, str(REPO))
import ops.halt as halt
HALTS=[]; halt.write_halt=lambda **kw: HALTS.append(kw) or None; halt.alert=lambda **kw: {}
from ops import common as oc
from src.deploy.broker.ibkr import IBKRBroker, IBKRConfig
from src.deploy.sleeve import PositionTarget, LONG, SHORT, ETF
from src.deploy.tests.test_option_order_path import _IbInsync
ROOT = Path(sys.argv[1]) / "mt" / "cef_live"
spec = json.loads((REPO/"ops/specs/cef_discount.frozen.json").read_text()); uni = sorted(spec["frozen"]["universe"]); costs = oc.load_costs()
px = pd.read_parquet(REPO/"data/cef/cef_prices.parquet", columns=["date","ticker","close","volume"])
px = px[px.ticker.isin(uni) & (px.date >= "2026-06-01")].copy(); px["dividend"]=0.0
class MS:
    def __init__(s, asof): s.prices = px[px.date <= pd.Timestamp(asof)]
class _C:
    def __init__(s, sym): s.symbol = s.localSymbol = sym
class _P:
    def __init__(s, sym, q): s.contract, s.position = _C(sym), q
class StubIB:
    def __init__(s,pos): s.pos,s.placed,s._oid=pos,[],100
    def positions(s): return [_P(k,v) for k,v in s.pos.items()]
    def fills(s): return []
    def reqAllOpenOrders(s): return []
    def openTrades(s): return []
    def placeOrder(s,c,o):
        s._oid+=1; o.orderId,o.permId=s._oid,0; s.placed.append((c.symbol,o.action,float(o.totalQuantity),o.orderType))
        return type("T",(),{"contract":c,"order":o,"fills":[],"orderStatus":type("S",(),{"status":"PreSubmitted"})()})()
epoch = pd.read_csv(ROOT/"_ibkr_shadow/cef_discount/positions.csv")
acct = {r.ticker: float(r.shares) for r in epoch.itertuples() if r.ticker!="CASH"}
asof="2026-09-14"
close = px[px.date==pd.Timestamp(asof)].set_index("ticker")["close"]
b = IBKRBroker(config=IBKRConfig(client_id=45), ib_insync_module=_IbInsync(), books_root=str(ROOT), verbose=True)
b.ib = StubIB(acct); b.register_sleeve("cef_discount","cef_discount",spec,costs,500000.0,uni); b.arm()
nav_adapter = b._sleeve_nav("cef_discount")
# ledger NAV at the asof close, computed the way advance() marks it (cash + shares*close); no fills to book
cash = float(pd.read_csv(ROOT/"_ibkr_shadow/cef_discount/nav.csv")["cash"].iloc[-1])
nav_ledger = cash + sum(q*float(close[t]) for t,q in acct.items())
print(f"adapter sizing NAV = {nav_adapter:,.2f} | ledger nav_today at {asof} close = {nav_ledger:,.2f}")
tk = max((t for t,q in acct.items() if q>0), key=lambda t: acct[t]*float(close[t]))   # largest long
p = float(close[tk]); q0 = acct[tk]
sign = +1 if nav_ledger < nav_adapter else -1      # pick the side on which the ledger's delta shrinks
w = (q0*p + sign*540.0)/nav_adapter
ad = math.floor(nav_adapter*w/p)-q0; ld = math.floor(nav_ledger*w/p)-q0
print(f"{tk}: px {p}, held {q0:+.0f}, weight target {w:.6f} -> adapter delta {ad:+.0f} (${abs(ad)*p:,.0f}) | ledger delta {ld:+.0f} (${abs(ld)*p:,.0f}) | min_trade 517")
tg = [PositionTarget(instrument=k, side=LONG if v>0 else SHORT, kind=ETF, qty=v, meta={"order_type":"MOC"}) for k,v in acct.items() if k!=tk]
tg.append(PositionTarget(instrument=tk, side=LONG, kind=ETF, weight=w, meta={"order_type":"MOC"}))
err=None
try: b.place_targets("cef_discount", tg, asof, MS(asof))
except Exception as e: err=e
lg=b.ledger("cef_discount")
print("placeOrder calls:", b.ib.placed)
print("raised:", type(err).__name__ if err else None, "| ledger last_date:", lg.last_date.date(), "| orders.csv rows:", len(lg.orders), lg.orders[["decision_date","ticker","delta_shares"]].to_dict("records") if len(lg.orders) else "")
b._release_transmit_lock()
