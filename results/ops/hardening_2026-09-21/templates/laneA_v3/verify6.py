"""Post-A1 shape: a ledger that holds an OPEN transmitted row decided 09-18 (scratch 'thru17' state), then ONE missed session."""
import sys, datetime as dt
from pathlib import Path
import pandas as pd
PROD = Path("/Users/simonjarvis/prod/QUANTT"); SCR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROD))
from src.deploy.broker.ibkr import IBKRBroker, ShadowLedgerBehind
from src.deploy.exec_ledger import LongOnlySleeveLedger
from ops.decision_age import EXCHANGE_TZ
lg = LongOnlySleeveLedger(SCR/"root_thru17"/"cef_discount")
print("ledger last:", lg.last_date.date(), "| open rows:", lg.orders[lg.orders.status=="open"][["decision_date","ticker","delta_shares"]].to_dict("records"))
class MS:
    def __init__(s, dates): s.prices = pd.DataFrame({"date": list(dates), "ticker": ["PHK"]*len(dates), "close": [4.3]*len(dates)})
b = IBKRBroker.__new__(IBKRBroker); b.ledger = lambda n: lg; b._books_root = str(SCR/"nonexistent")
b.ib = type("IB", (), {"fills": lambda self: []})()
for asof, now, label in [("2026-09-21", dt.datetime(2026,9,22,8,30,tzinfo=EXCHANGE_TZ), "normal next morning (asof 09-21), no capture log in scratch"),
                         ("2026-09-22", dt.datetime(2026,9,23,8,30,tzinfo=EXCHANGE_TZ), "ONE session missed (asof 09-22)")]:
    try:
        b._refuse_if_ledger_is_behind("cef_discount", asof, MS(pd.bdate_range("2026-09-01", asof)), now=now)
        print(label, "-> guard passes")
    except ShadowLedgerBehind as e:
        print(label, "-> ShadowLedgerBehind:", str(e)[:150])
