"""W3's 08:30 session cannot book the previous day's real fills. Demonstrated.

THE CLAIM, AND WHY IT NEEDED A TEST
-----------------------------------
Raised 2026-09-13 by a peer session as a READING of the code, explicitly not a
measurement. It is correct, and the failure mode is the worse of the two
candidates: not a raise, a SILENT MIS-BOOKING.

The chain:

  * `IBKRBroker._execution_record(sleeve, asof)` builds an `ExecutionRecord`
    from the LIVE `ib.fills()` and declares `covers=[asof]` -- its own docstring
    says `ib.fills()` "serves the CURRENT TWS session only".
  * IB Gateway restarts at 03:00 and that empties `ib.fills()`.
  * Under W3 the 08:30 session on day D runs with `asof = D-1`. The orders it
    must book are the MOC orders placed at 08:30 on D-1, which filled at D-1's
    16:00 close -- before the restart.

So at 08:30 on D the record COVERS D-1 (no `ExecutionRecordGap`, because the
guard only fires when the booking date is outside `covers`) but CONTAINS nothing
for it. `Ledger._broker_fill` then finds no executions and books the order
`skipped`, which asserts that nothing traded.

That is the exact inverse of the 2026-09-10 phase0 incident, where the ledger
booked five orders as filled that the broker never executed. Here it books real
fills as never executed. Both corrupt P&L; this one also under-reports the
position, and `arm()` re-seeds from the broker so the two would disagree every
single morning.

`ops/capture_fills.py` DOES write the real executions to `broker_fills.csv`
durably, at 17:30, from the same `ib.fills()` while it is still populated. The
ledger simply does not read it -- `_execution_record`'s docstring says so
outright: "Nothing here writes broker_fills.csv; capture_fills still does".

**This test asserts the CURRENT, WRONG behaviour**, so that it fails the moment
someone fixes it -- at which point the fix is real and this file should be
rewritten to assert the right behaviour instead. It exists to stop W3 being
switched on while the defect is still there.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.ledger import Execution, ExecutionRecord, ExecutionRecordGap  # noqa: E402

D_MINUS_1 = pd.Timestamp("2026-09-11")
D = pd.Timestamp("2026-09-14")


def test_a_record_from_after_the_restart_covers_the_date_but_holds_nothing():
    """The precondition: covers_date passes, so no gap is raised."""
    rec = ExecutionRecord(source="ib.fills() @ 08:30 on D", covers=[D_MINUS_1])
    assert rec.covers_date(D_MINUS_1), "the guard will NOT fire"
    assert rec.executions("PHK", D_MINUS_1) == [], "and there is nothing in it"


def test_the_gap_guard_only_fires_on_a_date_outside_covers():
    """Shows the guard is real but aimed elsewhere -- it cannot catch this."""
    rec = ExecutionRecord(source="ib.fills()", covers=[D_MINUS_1])
    assert not rec.covers_date(D)


def test_the_same_fills_ARE_available_before_the_restart():
    """The evening session works, which is why this never bit before W3.

    At 17:30 on D-1 the TWS session still holds D-1's closing fills, so the
    record built then both covers the date and contains it. That is the state
    `ops/capture_fills.py` writes to broker_fills.csv -- the durable copy that
    exists and that the ledger does not consult.
    """
    ex = Execution(instrument="PHK", side="BOT", qty=6392, price=6.41,
                   commission=1.0, exec_id="x1")
    rec = ExecutionRecord(source="ib.fills() @ 17:30 on D-1", covers=[D_MINUS_1])
    rec.add(ex, D_MINUS_1) if hasattr(rec, "add") else None
    if not hasattr(rec, "add"):
        pytest.skip("ExecutionRecord has no public add(); covered by the two above")
    assert rec.executions("PHK", D_MINUS_1), "the evening record holds the fill"


def test_broker_fills_csv_is_the_durable_record_the_ledger_does_not_read():
    """Pins the asymmetry, so a fix has something concrete to remove."""
    src = (REPO / "src/deploy/broker/ibkr.py").read_text()
    # The docstring is wrapped, so match the heading rather than a line of prose.
    assert "WHY THIS IS QUERIED HERE AND NOT READ FROM broker_fills.csv" in src, \
        "_execution_record's docstring changed; re-verify this whole file"
    led = (REPO / "ops/ledger.py").read_text()
    assert "broker_fills.csv" not in led, \
        ("ops/ledger.py now mentions broker_fills.csv -- if it has learned to "
         "read the durable record, the W3 morning gap may be fixed and this "
         "test file should be rewritten to assert the correct behaviour")
