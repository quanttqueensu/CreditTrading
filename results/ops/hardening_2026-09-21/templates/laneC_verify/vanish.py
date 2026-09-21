"""Verifier scratch: multi-day catch-up with a record that covers only asof. Do executions on the
uncovered intermediate days raise, or vanish? Pure local Simulator on a scratch copy; no broker."""
import json, sys, shutil
from pathlib import Path
import pandas as pd
REPO = Path("/Users/simonjarvis/Desktop/2027/QUANTT/2027"); sys.path.insert(0, str(REPO))
from ops import common as oc
from ops.ledger import ExecutionRecord
from src.deploy.broker.simulator import Simulator
from src.deploy.sleeve import PositionTarget, LONG, SHORT
SCR = Path(sys.argv[1]); root = SCR/"run_vanish"
if root.exists(): shutil.rmtree(root)
shutil.copytree(SCR/"books", root)
spec = json.loads((REPO/"ops/specs/cef_discount.frozen.json").read_text()); uni = sorted(spec["frozen"]["universe"])
px = pd.read_parquet(REPO/"data/cef/cef_prices.parquet", columns=["date","ticker","close","volume"])
px = px[px.ticker.isin(uni) & (px.date >= "2026-06-01")].copy(); px["dividend"]=0.0
px = (px.sort_values("date").set_index("date").groupby("ticker", group_keys=False).apply(lambda d: d.ffill()).reset_index())
class MS:
    def __init__(s, asof): s.prices = px[px.date <= pd.Timestamp(asof)]
sim = Simulator(books_root=root/"_ibkr_shadow", verbose=False)
sim.register_sleeve("cef_discount","cef_discount",spec,oc.load_costs(),500000.0,uni)
lg = sim.ledger("cef_discount"); held = {k:v for k,v in lg.held_shares().items() if k!="CASH"}
tg = [PositionTarget(instrument=k, side=LONG if v>0 else SHORT, qty=v, meta={"order_type":"MOC"}) for k,v in held.items()]
fills = pd.read_csv(root/"_ibkr_shadow/cef_discount/broker_fills.csv"); fills = fills[fills.fill_date>="2026-09-14"]
print("durable record holds", len(fills), "execution(s) dated", sorted(fills.fill_date.unique()))
try:
    sim.place_targets("cef_discount", tg, "2026-09-18", MS("2026-09-18"),
                      execution_record=ExecutionRecord(source="live", covers=["2026-09-18"]))
    lg = sim.ledger("cef_discount")
    print("NO RAISE. ledger last_date", lg.last_date.date(), "| nav rows", len(lg.nav), "| trades", len(lg.trades), "| orders", len(lg.orders))
except Exception as e:
    print("RAISED", type(e).__name__, str(e)[:200])
