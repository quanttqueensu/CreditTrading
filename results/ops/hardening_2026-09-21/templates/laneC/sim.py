"""Lane C scratch proof. Pure local: a COPY of prod's frozen shadow ledger, real
CEF closes read-only, no broker, no network. Writes only under the scratchpad."""
import json, sys, shutil
from pathlib import Path
import pandas as pd
REPO = Path("/Users/simonjarvis/Desktop/2027/QUANTT/2027")
sys.path.insert(0, str(REPO))
from ops import common as oc
from ops.ledger import ExecutionRecord
from src.deploy.broker.simulator import Simulator
from src.deploy.broker.ibkr import IBKRBroker, ShadowLedgerBehind
from src.deploy.sleeve import PositionTarget, LONG, SHORT

SCR = Path(sys.argv[1])
spec = json.loads((REPO / "ops/specs/cef_discount.frozen.json").read_text())
uni = sorted(spec["frozen"]["universe"])
px = pd.read_parquet(REPO / "data/cef/cef_prices.parquet",
                     columns=["date", "ticker", "close", "volume"])
px = px[px.ticker.isin(uni) & (px.date >= "2026-06-01")].copy()
px["dividend"] = 0.0
# landmine 4: HYT can lag; ffill per ticker so the ledger's gap guard is not the thing under test
px = (px.sort_values("date").set_index("date").groupby("ticker", group_keys=False)
        .apply(lambda d: d.ffill()).reset_index())
class MS:  # minimal MarketState
    def __init__(self, asof): self.prices = px[px.date <= pd.Timestamp(asof)]
costs = oc.load_costs()
held = json.loads((SCR / "desync.json").read_text())["tag_book_after_fills"]
targets = [PositionTarget(instrument=k, side=LONG if v > 0 else SHORT, qty=v,
                          meta={"order_type": "MOC"}) for k, v in held.items()]

def fresh(tag):
    root = SCR / f"run_{tag}"
    if root.exists(): shutil.rmtree(root)
    shutil.copytree(SCR / "books", root)
    sim = Simulator(books_root=root / "_ibkr_shadow", verbose=True)
    sim.register_sleeve("cef_discount", "cef_discount", spec, costs, 500000.0, uni)
    return sim

print("=== A. the 09-14 session: asof == ledger.last_date (epoch 2026-09-11)")
sim = fresh("A"); lg = sim.ledger("cef_discount")
print("ledger last_date:", lg.last_date.date(), "| orders rows:", len(lg.orders))
out = sim.place_targets("cef_discount", targets, "2026-09-11", MS("2026-09-11"),
                        execution_record=ExecutionRecord(source="nothing", covers=[]))
lg = sim.ledger("cef_discount")
print("after place_targets(asof=2026-09-11): orders rows:", len(lg.orders),
      "| nav rows:", len(lg.nav), "| raised: no")

print("\n=== B. does the pre-transmit guard see the frozen ledger? asof=2026-09-18")
b = IBKRBroker.__new__(IBKRBroker); b.ledger = lambda _n: fresh("B").ledger("cef_discount")
try:
    r = b._refuse_if_ledger_is_behind("cef_discount", "2026-09-18", MS("2026-09-18"))
    print("_refuse_if_ledger_is_behind ->", r, "(None == would TRANSMIT)")
except ShadowLedgerBehind as e:
    print("REFUSED:", str(e)[:200])

print("\n=== C. the shadow advance that runs AFTER transmission, asof=2026-09-18")
sim = fresh("C")
try:
    sim.place_targets("cef_discount", targets, "2026-09-18", MS("2026-09-18"),
                      execution_record=ExecutionRecord(source="live", covers=["2026-09-18"]))
    lg = sim.ledger("cef_discount")
    print("no raise; ledger last_date", lg.last_date.date(), "orders", len(lg.orders))
except Exception as e:
    print("RAISED", type(e).__name__, ":", str(e)[:420])
