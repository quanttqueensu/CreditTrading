"""Verifier's independent replay. Prod code, COPY of prod ledger, scratch only. No broker."""
import shutil, sys
from pathlib import Path
import pandas as pd, numpy as np
PROD = Path("/Users/simonjarvis/prod/QUANTT"); SCR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROD))
import os; os.chdir(PROD)
from ops.ledger import Execution, ExecutionRecord, UnbookedExecution, ORDER_COLUMNS, _concat
from ops import capture_fills as cf
from src.deploy.broker.simulator import Simulator
from src.deploy.sleeve import PositionTarget, LONG, SHORT
from src.deploy import run_book as rb
import json
SRC = PROD/"ops/books/cef_live/_ibkr_shadow/cef_discount"
spec = json.load(open(PROD/"ops/specs/cef_discount.frozen.json"))
NAMES = sorted(pd.read_csv(SRC/"positions.csv").ticker)
px = rb._cef_px(); px = px[px.ticker.isin(NAMES) & (px.date >= "2026-06-01")].copy()
print("panel last date:", px.date.max().date(), "| HYT last:", px[px.ticker=="HYT"].dropna(subset=["close"]).date.max().date())
class MS:  # minimal market_state
    def __init__(s, p): s.prices = p
COSTS = {"tickers": {t: {"half_spread_bp": 10.0} for t in NAMES}, "slippage_extra_bp": 0.0,
         "impact_coefficient": 0.5, "max_participation_pct": 100.0, "commission_usd_per_trade": 0.0}  # synthetic: modelled price only
def sim(tag):
    root = SCR/f"root_{tag}"
    if root.exists(): shutil.rmtree(root)
    (root).mkdir(parents=True); shutil.copytree(SRC, root/"cef_discount")
    s = Simulator(books_root=root, verbose=True)
    s.register_sleeve("cef_discount", "cef_discount", {"rebalance": spec["rebalance"]}, COSTS, 500000.0, NAMES)
    return s, root/"cef_discount"
def rec(state, day, covered=True):
    r = ExecutionRecord(source=f"scratch {day}", covers=[pd.Timestamp(day)] if covered else [])
    if covered:
        for x in cf.captured_executions(state, day):
            r.add(Execution(x["instrument"], x["side"], x["qty"], x["price"], x["commission"], x["exec_id"]), date=x["date"])
    return r
def tg(held, **chg):
    w = dict(held)
    for k, v in chg.items(): w[k] = w.get(k, 0) + v
    return [PositionTarget(instrument=t, side=LONG if q > 0 else SHORT, qty=float(q)) for t, q in w.items()]

print("\n=== 1. 09-14 morning session, asof=2026-09-11, via Simulator.place_targets")
s, st = sim("a"); lg = s.ledger("cef_discount")
t1 = tg(lg.held_shares(), JFR=301, PDO=-909, PFN=604, PHK=1389)
out = s.place_targets("cef_discount", t1, "2026-09-11", MS(px), execution_record=rec(st, "2026-09-11", covered=False))
print("fills returned:", out, "| orders on disk:", len(pd.read_csv(st/"orders.csv")), "| nav rows:", len(pd.read_csv(st/"nav.csv")))
print("\n=== 2. 09-15 morning session, asof=2026-09-14")
try:
    s.place_targets("cef_discount", tg(lg.held_shares()), "2026-09-14", MS(px), execution_record=rec(st, "2026-09-14"))
    print("NO RAISE")
except UnbookedExecution as e:
    print("RAISED UnbookedExecution:", str(e)[:120])
print("orders on disk:", len(pd.read_csv(st/"orders.csv")), "| nav rows:", len(pd.read_csv(st/"nav.csv")))
