"""Lane C scratch: the REAL IBKRBroker.place_targets, a stub IB, a COPY of prod's
epoch ledger + durable fill record. Replays 09-14 (asof 09-11) then 09-15 (asof
09-14). No broker, no network; write_halt/alert are replaced so nothing lands in
any repo tree. Everything written goes under the scratchpad."""
import csv, json, sys
from pathlib import Path
import pandas as pd
REPO = Path("/Users/simonjarvis/Desktop/2027/QUANTT/2027"); sys.path.insert(0, str(REPO))
import ops.halt as halt
HALTS = []
halt.write_halt = lambda **kw: HALTS.append(kw) or None          # never touch ops/HALT*.md
halt.alert = lambda **kw: {}
from ops import common as oc
from src.deploy.broker.ibkr import IBKRBroker, IBKRConfig, ShadowLedgerDesync
from src.deploy.sleeve import PositionTarget, LONG, SHORT, FLAT, ETF
from src.deploy.tests.test_option_order_path import _IbInsync

ROOT = Path(sys.argv[1]) / "e2e" / "cef_live"
spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
uni = sorted(spec["frozen"]["universe"]); costs = oc.load_costs()
px = pd.read_parquet(REPO / "data/cef/cef_prices.parquet", columns=["date","ticker","close","volume"])
px = px[px.ticker.isin(uni) & (px.date >= "2026-06-01")].copy(); px["dividend"] = 0.0
class MS:
    def __init__(self, asof): self.prices = px[px.date <= pd.Timestamp(asof)]

class _C:
    def __init__(s, sym): s.symbol = s.localSymbol = sym
class _P:
    def __init__(s, sym, q): s.contract, s.position = _C(sym), q
class StubIB:
    def __init__(s, pos): s.pos, s.placed, s._oid = pos, [], 30
    def positions(s): return [_P(k, v) for k, v in s.pos.items()]
    def fills(s): return []                       # after the 03:00 gateway restart
    def reqAllOpenOrders(s): return []
    def openTrades(s): return []
    def placeOrder(s, c, o):
        s._oid += 1; o.orderId, o.permId = s._oid, 0
        s.placed.append((c.symbol, o.action, float(o.totalQuantity), o.orderType))
        return type("T", (), {"contract": c, "order": o, "fills": [],
                              "orderStatus": type("S", (), {"status": "PreSubmitted"})()})()

def session(label, asof, account, deltas, flat=()):
    ib = StubIB(account)
    b = IBKRBroker(config=IBKRConfig(client_id=45), ib_insync_module=_IbInsync(),
                   books_root=str(ROOT), verbose=True)
    b.ib = ib
    b.register_sleeve("cef_discount", "cef_discount", spec, costs, 500000.0, uni)
    rep = b.arm()
    tg = []
    for k, q in account.items():
        if k in flat:
            tg.append(PositionTarget(instrument=k, side=FLAT, kind=ETF, reason="cef: below min weight")); continue
        q2 = q + deltas.get(k, 0)
        tg.append(PositionTarget(instrument=k, side=LONG if q2 > 0 else SHORT, qty=q2, meta={"order_type": "MOC"}))
    print(f"\n##### {label}: asof={asof}  sleeve NAV used for sizing = {b._sleeve_nav('cef_discount'):,.2f}")
    err = None
    try:
        b.place_targets("cef_discount", tg, asof, MS(asof))
    except Exception as e:
        err = e
    lg = b.ledger("cef_discount")
    print(f"##### {label}: placeOrder calls = {ib.placed}")
    print(f"##### {label}: raised = {type(err).__name__ if err else None}; halts written (intercepted) = {len(HALTS)}; "
          f"ledger last_date = {lg.last_date.date()}, orders.csv rows = {len(lg.orders)}, trades rows = {len(lg.trades)}")
    b._release_transmit_lock()
    return ib

epoch = pd.read_csv(ROOT / "_ibkr_shadow/cef_discount/positions.csv")
acct0 = {r.ticker: float(r.shares) for r in epoch.itertuples() if r.ticker != "CASH"}
s1 = session("FLAT PROBE", "2026-09-11", acct0, {}, flat=("PCN",))
raise SystemExit
# production wrote these rows at 2026-09-14T13:50Z; re-stamp so the map guard sees that auction as closed
mp = ROOT / "_ibkr_shadow/_order_map.csv"; rows = list(csv.DictReader(open(mp)))
for r in rows: r["recorded_utc"] = "2026-09-14T13:50:52+00:00"
with open(mp, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
acct1 = dict(acct0)
for k, d in {"JFR": +301, "PDO": -909, "PFN": +604, "PHK": +1389}.items(): acct1[k] += d
s2 = session("SESSION 2 (2026-09-15 08:39)", "2026-09-14", acct1,
             {"AWF": -638, "JFR": +1446, "NEA": +904, "PFN": +3121})
print("\nintercepted halt reasons:", [h.get("reason") for h in HALTS])
print("desync json transmitted_fills:", json.loads(next((ROOT/'_ibkr_shadow/_desync').glob('*.json')).read_text())["transmitted_fills"])
