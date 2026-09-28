"""Run prod's _refuse_if_ledger_is_behind against the REAL prod ledgers (read-only load of a COPY). No broker: IBKRBroker.__new__."""
import sys, shutil, datetime as dt
from pathlib import Path
import pandas as pd
PROD = Path("/Users/simonjarvis/prod/QUANTT"); SCR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROD))
from src.deploy.broker.ibkr import IBKRBroker, ShadowLedgerBehind
from src.deploy.exec_ledger import LongOnlySleeveLedger
from ops.decision_age import EXCHANGE_TZ
class MS:
    def __init__(s, dates, t): s.prices = pd.DataFrame({"date": list(dates), "ticker": [t]*len(dates), "close": [1.0]*len(dates)})
def check(label, src, asof, now, ticker):
    dst = SCR/("g_"+label); 
    if dst.exists(): shutil.rmtree(dst)
    shutil.copytree(src, dst); lg = LongOnlySleeveLedger(dst)
    b = IBKRBroker.__new__(IBKRBroker); b.ledger = lambda n: lg
    try:
        b._refuse_if_ledger_is_behind(label, asof, MS(pd.bdate_range("2026-09-01", asof), ticker), now=now)
        print(f"{label}: guard PASSES (last={lg.last_date.date()}, open={int((lg.orders.status=='open').sum()) if len(lg.orders) else 0}, asof={asof}) -> would proceed to transmit")
    except ShadowLedgerBehind as e:
        print(f"{label}: ShadowLedgerBehind BEFORE transmit -> {str(e)[:170]}")
check("null_trader", PROD/"ops/books/phase0_live/_ibkr_shadow/null_trader", "2026-09-21",
      dt.datetime(2026, 9, 21, 9, 43, tzinfo=EXCHANGE_TZ), "HYG")
check("cef_discount", PROD/"ops/books/cef_live/_ibkr_shadow/cef_discount", "2026-09-18",
      dt.datetime(2026, 9, 21, 8, 30, tzinfo=EXCHANGE_TZ), "JFR")
check("bench_b3_agg", PROD/"ops/books/benchmarks_live/_ibkr_shadow/bench_b3_agg", "2026-09-21",
      dt.datetime(2026, 9, 21, 17, 25, tzinfo=EXCHANGE_TZ), "AGG")
