"""W3's 08:30 session books the previous day's real fills, or refuses loudly.

HISTORY OF THIS FILE
--------------------
Written 2026-09-13 by a peer session as a TRIPWIRE: it asserted the wrong
behaviour on purpose, so that it would fail the moment someone fixed the defect
and force this rewrite. The defect, in its words:

  `IBKRBroker._execution_record(sleeve, asof)` built its record from the LIVE
  `ib.fills()` and declared `covers=[asof]`. IB Gateway restarts at 03:00 and
  empties `ib.fills()`. Under W3 the 08:30 session on D runs with asof = D-1,
  so the record COVERED D-1 while HOLDING nothing -- no ExecutionRecordGap, and
  `Ledger._broker_fill` booked every order `skipped`. Real fills recorded as
  never executed, silently: the exact inverse of the 2026-09-10 phase0 phantom.

The fix (same day) makes coverage EARNED when the query runs on a later
exchange day than `asof`: either the live session still holds executions dated
`asof`, or a capture completed after `asof`'s close and broker_fills.csv -- the
durable record `ops/capture_fills.py` writes -- is booked. Otherwise the record
covers nothing and the ledger raises. A same-day query is unchanged.

Each test below drives the real `_execution_record` (or the real `capture()`),
with a stub broker and files in tmp_path. Share counts and the commission are
real rows from cef_live's broker_fills.csv (PHK BUY 697, 2026-09-08).

NO BROKER, NO NETWORK, NO LIVE LEDGERS.
"""
from __future__ import annotations

import datetime as dt
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import capture_fills as cf  # noqa: E402
from ops.ledger import ExecutionRecord  # noqa: E402
from src.deploy.broker.ibkr import IBKRBroker  # noqa: E402
from src.deploy.lib.odd_lot import record_broker_fill  # noqa: E402

ET = dt.timezone(dt.timedelta(hours=-4))
D_MINUS_1 = pd.Timestamp("2026-09-11")
MORNING_D = dt.datetime(2026, 9, 14, 8, 30, tzinfo=ET)       # Monday 08:30
EVENING_D_MINUS_1 = dt.datetime(2026, 9, 11, 17, 30, tzinfo=ET)
SLEEVE = "cef_discount"


# -- stubs ------------------------------------------------------------------

def _fill(sym, exec_id, when_utc, side="BOT", shares=697.0, price=6.41,
          commission=3.49):
    ex = types.SimpleNamespace(execId=exec_id, time=when_utc, side=side,
                               shares=shares, price=price, permId=0, orderId=1,
                               orderRef="")
    rep = types.SimpleNamespace(execId=exec_id, commission=commission)
    return types.SimpleNamespace(execution=ex, contract=types.SimpleNamespace(
        symbol=sym), commissionReport=rep)


class _IB:
    def __init__(self, fills=()):
        self._fills = list(fills)

    def fills(self):
        return list(self._fills)


def _broker(tmp_path, fills=()):
    b = IBKRBroker.__new__(IBKRBroker)
    b.ib = _IB(fills)
    b._books_root = str(tmp_path)
    b._sleeves = {SLEEVE: {"instruments": ["PHK", "NAD", "NEA"]}}
    b._foreign_book_claims = lambda: set()
    b._order_map_by_id = lambda: {}
    b.verbose = False
    return b


def _capture_row(tmp_path, when):
    path = cf._capture_log_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a") as fh:
        if new:
            fh.write(",".join(cf.CAPTURE_LOG_COLUMNS) + "\n")
        fh.write(f"{when.isoformat()},95,17,2026-09-11,1,0\n")


def _durable_phk(tmp_path, exec_id="00012ec5.6b4341f1.01.01"):
    record_broker_fill(tmp_path / "_ibkr_shadow" / SLEEVE, instrument="PHK",
                       side="BUY", qty=697.0, price=6.41, fill_date="2026-09-11",
                       note=f"execId={exec_id} orderRef='' commission=3.49 "
                            f"time=2026-09-11 19:59:40+00:00")


# -- the defect, fixed --------------------------------------------------------

def test_the_morning_books_yesterdays_fills_from_the_durable_record(tmp_path):
    """The W3 case. Live session empty (post-restart); a capture ran at 17:30
    on D-1; broker_fills.csv holds PHK BUY 697. The record must cover D-1 AND
    hold the fill, with its real commission."""
    _capture_row(tmp_path, EVENING_D_MINUS_1)
    _durable_phk(tmp_path)
    rec = _broker(tmp_path)._execution_record(SLEEVE, D_MINUS_1, now=MORNING_D)
    assert rec.covers_date(D_MINUS_1)
    [ex] = rec.executions("PHK", D_MINUS_1)
    assert (ex.side, ex.qty, ex.price, ex.commission) == ("BUY", 697.0, 6.41, 3.49)


def test_with_no_capture_the_morning_refuses_instead_of_calling_fills_skipped(tmp_path):
    """The silent mis-booking becomes a loud stop. covers is empty, so
    Ledger._broker_fill raises ExecutionRecordGap for any D-1 order."""
    _durable_phk(tmp_path)            # rows exist, but no capture vouches for them
    rec = _broker(tmp_path)._execution_record(SLEEVE, D_MINUS_1, now=MORNING_D)
    assert not rec.covers_date(D_MINUS_1)
    assert len(rec) == 0


def test_a_capture_before_the_close_does_not_vouch_for_the_day(tmp_path):
    _capture_row(tmp_path, dt.datetime(2026, 9, 11, 15, 0, tzinfo=ET))
    _durable_phk(tmp_path)
    rec = _broker(tmp_path)._execution_record(SLEEVE, D_MINUS_1, now=MORNING_D)
    assert not rec.covers_date(D_MINUS_1)


def test_a_capture_on_a_later_day_does_not_vouch_for_the_day(tmp_path):
    """09-12 07:09 is after IB's restart: it saw nothing of 09-11. This is the
    capture the 2026-09-11 session actually ran (cef_2026-09-11.log)."""
    _capture_row(tmp_path, dt.datetime(2026, 9, 12, 7, 9, tzinfo=ET))
    rec = _broker(tmp_path)._execution_record(SLEEVE, D_MINUS_1, now=MORNING_D)
    assert not rec.covers_date(D_MINUS_1)


def test_a_live_session_that_still_spans_the_day_covers_it_without_double_counting(tmp_path):
    """No restart happened (or it was skipped): the live session still holds
    D-1, and the same execution is also on disk. Booked once."""
    eid = "00012ec5.6b4341f1.01.01"
    live = [_fill("PHK", eid, dt.datetime(2026, 9, 11, 19, 59, 40,
                                          tzinfo=dt.timezone.utc))]
    _capture_row(tmp_path, EVENING_D_MINUS_1)
    _durable_phk(tmp_path, exec_id=eid)
    rec = _broker(tmp_path, live)._execution_record(SLEEVE, D_MINUS_1,
                                                    now=MORNING_D)
    assert rec.covers_date(D_MINUS_1)
    assert len(rec.executions("PHK", D_MINUS_1)) == 1


def test_a_same_day_query_is_unchanged(tmp_path):
    """Every session that runs today queries on asof's own day. That branch
    must not read broker_fills.csv at all -- even a row it would otherwise
    book is ignored -- and still covers asof from the live session alone."""
    _capture_row(tmp_path, EVENING_D_MINUS_1)
    _durable_phk(tmp_path)
    rec = _broker(tmp_path)._execution_record(
        SLEEVE, D_MINUS_1, now=dt.datetime(2026, 9, 11, 21, 46, tzinfo=ET))
    assert rec.covers_date(D_MINUS_1)
    assert rec.executions("PHK", D_MINUS_1) == []


def test_a_durable_row_without_an_exec_id_raises(tmp_path):
    _capture_row(tmp_path, EVENING_D_MINUS_1)
    record_broker_fill(tmp_path / "_ibkr_shadow" / SLEEVE, instrument="PHK",
                       side="BUY", qty=697.0, price=6.41,
                       fill_date="2026-09-11", note="hand-typed")
    with pytest.raises(ValueError, match="no execId"):
        _broker(tmp_path)._execution_record(SLEEVE, D_MINUS_1, now=MORNING_D)


# -- the writer: a capture that found nothing still leaves its trace -----------

def _run_capture(tmp_path, monkeypatch, fills):
    stub = types.ModuleType("ib_async")

    class IB:
        def connect(self, *a, **k):
            pass

        def fills(self):
            return list(fills)

        def disconnect(self):
            pass

    stub.IB = IB
    monkeypatch.setitem(sys.modules, "ib_async", stub)
    monkeypatch.setattr(cf, "sleeve_universes",
                        lambda book: {SLEEVE: {"PHK", "NAD", "NEA"}})
    return cf.capture("unused_book.json", str(tmp_path), client_id=95,
                      verbose=False)


def test_capture_logs_a_completed_run_even_with_zero_executions(tmp_path, monkeypatch):
    """Without this row, 'captured, nothing traded' and 'never captured' are
    the same empty file."""
    _run_capture(tmp_path, monkeypatch, fills=[])
    log = pd.read_csv(cf._capture_log_path(tmp_path))
    assert len(log) == 1 and int(log.iloc[0]["n_executions"]) == 0


def test_capture_records_a_commission_only_when_its_report_arrived(tmp_path, monkeypatch):
    """ib_async's default CommissionReport has execId '' and commission 0.0.
    That must be recorded as None, never as a real zero."""
    arrived = _fill("PHK", "e1", dt.datetime(2026, 9, 11, 19, 59, 40,
                                             tzinfo=dt.timezone.utc))
    in_flight = _fill("NAD", "e2", dt.datetime(2026, 9, 11, 19, 59, 41,
                                               tzinfo=dt.timezone.utc),
                      commission=0.0)
    in_flight.commissionReport.execId = ""
    _run_capture(tmp_path, monkeypatch, fills=[arrived, in_flight])
    rows = {r["instrument"]: r["commission"] for r in
            cf.captured_executions(tmp_path / "_ibkr_shadow" / SLEEVE,
                                   "2026-09-11")}
    assert rows == {"PHK": 3.49, "NAD": None}


def test_the_ledger_gap_guard_is_what_turns_empty_covers_into_a_stop():
    """Unchanged ledger behaviour the fix relies on."""
    rec = ExecutionRecord(source="nothing", covers=[])
    assert not rec.covers_date(D_MINUS_1)
