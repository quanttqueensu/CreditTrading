"""Rule 2 at IBKR (guard.py), on the incident shapes of the archived pending_orders tests.

  2026-07-31  four armed runs stacked 79 MOC orders that `openTrades()` did not show
  2026-09-10  a date-keyed guard refused the legitimate next session
Timestamps follow the archive's real rows where it had one (NAD BUY 1313, 2026-09-11 10:38 ET)."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from quantt.session import records as rec
from quantt.twin import guard
from quantt.twin.tests.fakes import et


def _log(state, day, rows):
    d = rec.day_dir(state, day)
    for r in rows:
        rec.append_jsonl(d / "orders.jsonl", r)


def intent(sym, close, side="buy", qty=100):
    return {"event": "intent", "order_ref": f"twin-x-{sym}", "symbol": sym, "side": side, "qty": qty,
            "session_date": close.date().isoformat(), "close_et": close.isoformat()}


def test_the_log_refuses_even_when_the_broker_is_blind(tmp_path):
    """The 07-31 shape: nothing shows at the broker, the twin's own log says a set went."""
    close = et(2026, 9, 11, 16, 0)
    _log(tmp_path, close.date(), [intent("NAD", close, qty=1313)])
    pend = guard.pending_in_logs(tmp_path, et(2026, 9, 11, 15, 40))
    out = guard.refusals(started=False, open_orders=[], open_orders_error=None, pending=pend,
                         executions=[], executions_error=None)
    text = " ".join(d for _, d in out)
    assert "1 order(s)" in text and "DISAGREE" in text


def test_the_next_session_is_not_refused_by_an_old_set(tmp_path):
    """The 09-10 shape, the other way round: after the close the set is no longer pending."""
    close = et(2026, 9, 11, 16, 0)
    _log(tmp_path, close.date(), [intent("NAD", close)])
    assert guard.pending_in_logs(tmp_path, et(2026, 9, 11, 16, 1)) == []
    assert guard.pending_in_logs(tmp_path, et(2026, 9, 14, 15, 30)) == []


def test_an_early_close_ends_pending_at_its_own_close(tmp_path):
    close = et(2026, 11, 27, 13, 0)
    _log(tmp_path, close.date(), [intent("PDI", close)])
    assert guard.pending_in_logs(tmp_path, et(2026, 11, 27, 12, 40))
    assert guard.pending_in_logs(tmp_path, et(2026, 11, 27, 13, 0, 1)) == []


def test_any_open_order_on_the_account_refuses_whatever_its_symbol():
    oo = [{"symbol": "ZZZ", "action": "SELL", "qty": 5.0, "order_type": "LMT", "status": "Submitted", "client_id": 0}]
    out = guard.refusals(started=False, open_orders=oo, open_orders_error=None, pending=[], executions=[],
                         executions_error=None)
    assert any("1 open order(s)" in d for _, d in out)


def test_started_alone_refuses():
    out = guard.refusals(started=True, open_orders=[], open_orders_error=None, pending=[], executions=[],
                         executions_error=None)
    assert [g for g, _ in out] == ["no_set_in_auction"]


def test_not_knowing_refuses():
    out = guard.refusals(started=False, open_orders=None, open_orders_error="timeout", pending=[], executions=None,
                         executions_error="timeout")
    assert len(out) == 2


def test_an_execution_today_before_the_send_refuses():
    out = guard.refusals(started=False, open_orders=[], open_orders_error=None, pending=[],
                         executions=[{"symbol": "PDI"}], executions_error=None)
    assert any("execution" in d for _, d in out)


def test_nothing_anywhere_is_clear():
    assert guard.refusals(started=False, open_orders=[], open_orders_error=None, pending=[], executions=[],
                          executions_error=None) == []


@pytest.mark.parametrize("bad", ["not json", json.dumps({"event": "intent", "symbol": "NVG"}),
                                 json.dumps({"event": "intent", "symbol": "NVG", "close_et": "2026-09-11T16:00:00"})])
def test_an_unreadable_log_line_refuses(tmp_path, bad):
    d = rec.day_dir(tmp_path, dt.date(2026, 9, 11))
    (d / "orders.jsonl").write_text(bad + "\n")
    with pytest.raises(guard.GuardUnknown):
        guard.pending_in_logs(tmp_path, et(2026, 9, 11, 15, 30))


def test_two_processes_cannot_both_hold_the_lock(tmp_path):
    with guard.transmit_lock(tmp_path):
        with pytest.raises(guard.AlreadyTransmitting):
            with guard.transmit_lock(tmp_path):
                pass
    with guard.transmit_lock(tmp_path):
        pass
