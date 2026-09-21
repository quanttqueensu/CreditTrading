"""Lane A scratch replay. Reads prod code + a COPY of the prod CEF shadow ledger.
Writes ONLY under the scratchpad. No broker, no network (asof <= panel last date)."""
import shutil, sys, io, contextlib
from pathlib import Path
import pandas as pd, numpy as np

PROD = Path("/Users/simonjarvis/prod/QUANTT")
SCR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROD))
from ops.ledger import Execution, ExecutionRecord, UnbookedExecution, ExecutionRecordGap  # noqa
from ops import capture_fills as cf  # noqa
from src.deploy.exec_ledger import LongOnlySleeveLedger  # noqa
from src.deploy.sleeve import PositionTarget, LONG, SHORT  # noqa
from src.deploy import run_book as rb  # noqa

SRC = PROD / "ops/books/cef_live/_ibkr_shadow/cef_discount"
NAMES = ['AWF','BIT','DSL','HYT','JFR','MHD','MQY','NAD','NEA','NVG','NZF','PCN','PDI','PDO','PFN','PHK','PTY']

def fresh(tag):
    dst = SCR / f"state_{tag}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst)
    return dst

px = rb._cef_px()
px = px[px.ticker.isin(NAMES) & (px.date >= "2026-06-01") & (px.date <= "2026-09-18")].copy()
COSTS = {"tickers": {t: {"half_spread_bp": 10.0} for t in NAMES},   # SYNTHETIC: only feeds modelled_fill_price
         "slippage_extra_bp": 0.0, "impact_coefficient": 0.5,
         "max_participation_pct": 100.0, "commission_usd_per_trade": 0.0}
SPEC = {"book_usd": 500000.0, "capital_usd": 500000.0, "tickers": NAMES,
        "rebalance": {"min_trade_usd": 517.0}}

def hold_targets(lg):
    out = []
    for t, q in lg.held_shares().items():
        out.append(PositionTarget(instrument=t, side=LONG if q > 0 else SHORT, qty=float(q)))
    return out

def record_for(state, day, covered=True):
    rec = ExecutionRecord(source=f"scratch broker_fills.csv {day}", covers=[pd.Timestamp(day)] if covered else [])
    if covered:
        for x in cf.captured_executions(state, day):
            rec.add(Execution(x["instrument"], x["side"], x["qty"], x["price"], x["commission"], x["exec_id"]), date=x["date"])
    return rec

def adv(lg, through, rec, targets):
    lg.execution_record = rec
    try:
        return lg.advance(px, SPEC, COSTS, lambda s, d, p: list(targets), through=pd.Timestamp(through), verbose=True)
    finally:
        lg.execution_record = None

print("=== STEP 1: replay the 2026-09-14 09:50 shadow advance (asof=2026-09-11, record covers nothing)")
st = fresh("step1"); lg = LongOnlySleeveLedger(st)
print("ledger last_date:", lg.last_date.date(), "| orders rows:", len(lg.orders))
# targets that WOULD create orders if the day were processed: the four the adapter actually sent
h = lg.held_shares(); want = dict(h); want["JFR"] += 301; want["PDO"] -= 909; want["PFN"] += 604; want["PHK"] += 1389
tg = [PositionTarget(instrument=t, side=LONG if q > 0 else SHORT, qty=float(q)) for t, q in want.items()]
r = adv(lg, "2026-09-11", record_for(st, "2026-09-11", covered=False), tg)
print("advance returned:", {k: (str(v) if k == 'last_date' else v) for k, v in r.items()})
print("orders rows after:", len(LongOnlySleeveLedger(st).orders))

print("\n=== STEP 2: replay the 2026-09-15 08:39 shadow advance (asof=2026-09-14, record = 4 captured execs)")
try:
    adv(lg, "2026-09-14", record_for(st, "2026-09-14"), hold_targets(lg))
    print("NO RAISE")
except UnbookedExecution as e:
    print("UnbookedExecution reproduced:", str(e)[:150])
print("on-disk nav rows after the raise:", len(pd.read_csv(st / "nav.csv")), "(advance saves only at the end -> nothing persisted)")
