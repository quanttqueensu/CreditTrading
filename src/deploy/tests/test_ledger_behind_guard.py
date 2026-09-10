"""The book must refuse BEFORE transmitting when its ledger cannot book today.

WHY THIS FILE EXISTS
--------------------
`_execution_record` covers exactly `asof`, because `ib.fills()` serves the
current TWS session and cannot reach back past its daily restart. A ledger that
still holds orders it will book on an EARLIER date therefore hits
`ExecutionRecordGap` inside the shadow advance -- which runs AFTER the orders
have gone to the exchange. For the CEF book those are MOC orders, and NYSE will
not cancel an MOC after 15:50 "even to correct a legitimate error".

Measured 2026-09-10: `cef_live`'s ledger ends 2026-09-09 and holds three orders
decided that day still open (JFR -4,727, MQY +169, NEA -4,565). The next armed
session on any date after 2026-09-10 is the live case.

THE MONDAY TEST IS THE POINT OF THE FILE. The first version of this guard asked
"is asof exactly one day after last_date", which is true Tuesday to Friday and
false every Monday and after every holiday -- so it would have halted the book
weekly. `advance` steps over the PRICE PANEL's index, so the guard must too.
That is the same shape as every incident in this repo: a guard that shares a
broken assumption with the thing it guards is not a guard.

NO BROKER, NO NETWORK. `IBKRBroker` is built with `__new__` and only the
attributes the guard reads are set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.deploy.broker.ibkr import IBKRBroker, ShadowLedgerBehind  # noqa: E402

# Sept 2026: 10th Thu, 11th Fri, 14th Mon. A weekday-only panel, as the store is.
PANEL = pd.bdate_range("2026-09-01", "2026-09-18")


class _MarketState:
    def __init__(self, dates):
        self.prices = pd.DataFrame({
            "date": list(dates) * 1,
            "ticker": ["JFR"] * len(dates),
            "close": [7.67] * len(dates)})


class _Ledger:
    def __init__(self, last_date, open_tickers, decision_date):
        self.last_date = pd.Timestamp(last_date) if last_date else None
        self.orders = pd.DataFrame([
            {"decision_date": pd.Timestamp(decision_date), "ticker": t,
             "status": "open", "fill_date": pd.NaT}
            for t in open_tickers])


def _broker(ledger):
    b = IBKRBroker.__new__(IBKRBroker)
    b.ledger = lambda _name: ledger
    return b


def _check(last_date, asof, open_tickers=("JFR", "MQY", "NEA"),
           decision_date="2026-09-09", dates=PANEL):
    _broker(_Ledger(last_date, open_tickers, decision_date)) \
        ._refuse_if_ledger_is_behind("cef_discount", asof, _MarketState(dates))


def test_ordinary_next_day_advance_is_allowed():
    """Thu -> Fri. Today's execution record covers the day being booked."""
    _check("2026-09-10", "2026-09-11")


def test_friday_to_monday_is_allowed():
    """THE REGRESSION. Three calendar days, ONE trading bar.

    A calendar-day guard refuses here, which would stop the book every Monday.
    """
    _check("2026-09-11", "2026-09-14")


def test_skipped_session_refuses():
    """Ledger ends Wed, session runs Fri: Thu's orders can never be covered."""
    with pytest.raises(ShadowLedgerBehind, match="cannot be cancelled after 15:50"):
        _check("2026-09-09", "2026-09-11")


def test_the_live_cef_case_refuses():
    """cef_live as measured 2026-09-10: ends 09-09, three orders open."""
    with pytest.raises(ShadowLedgerBehind) as e:
        _check("2026-09-09", "2026-09-14")
    for t in ("JFR", "MQY", "NEA"):
        assert t in str(e.value)


def test_no_open_orders_never_refuses():
    """A ledger with nothing pending has nothing it could mis-book."""
    _check("2026-09-09", "2026-09-14", open_tickers=())


def test_ledger_already_current_never_refuses():
    _check("2026-09-14", "2026-09-14")


def test_empty_panel_does_not_refuse():
    """Unit stubs supply no prices and the shadow advance is skipped too."""
    _check("2026-09-09", "2026-09-14", dates=[])
