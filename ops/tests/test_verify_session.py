"""The post-close verifier must call each real failure shape a failure.

WHY THIS FILE EXISTS
--------------------
`ops/verify_session.py` is the one check in this repo that is not about a
cause. Its value is entirely in whether it says FAIL on the days the book broke
and PASS on the days it did not -- so each test below is a day, or the shape of
a day, this book actually had:

  fills never captured        09-09 / 09-10 closes: positions moved, records did not
  ledger booked a phantom     09-10: null_trader JAAA -1503, broker none
  a stacked order set         07-31: 79 MOC orders stacked in one auction
  nothing visible any more    any run after IB's nightly gateway restart

SYNTHETIC INPUTS, AND WHY THAT IS ALLOWED HERE. CLAUDE.md permits synthetic
data for testing whether a METHOD behaves. Every conclusion below is about this
comparison's code, not about the market. Share counts reuse the real order-map
and ledger rows where one exists so a failure reads as the day it describes.

NO BROKER, NO NETWORK. `evaluate()` is pure; `_finish()` is driven with a stub
halt module writing into tmp_path.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import verify_session as vs  # noqa: E402

ET = dt.timezone(dt.timedelta(hours=-4))
D = dt.date(2026, 9, 11)
L = dt.date(2026, 9, 10)

UNIVERSE = {"cef_discount": {"NAD", "NEA", "JFR", "MHD"}}


def _row(inst, action, qty, recorded_utc="2026-09-11T14:38:31.702971+00:00",
         sleeve="cef_discount"):
    return {"recorded_utc": recorded_utc, "instrument": inst, "action": action,
            "qty": str(qty), "sleeve": sleeve}


def _ex(inst, side, shares, when=dt.datetime(2026, 9, 11, 16, 0, 1, tzinfo=ET)):
    return {"instrument": inst, "side": side, "shares": float(shares),
            "time_et": when}


def _eval(**kw):
    base = dict(auction=D, universe=UNIVERSE, contested=set(),
                broker_positions={"NAD": -5237.0, "NEA": -11683.0},
                open_trades=[], executions=[_ex("NAD", "BOT", 1313)],
                order_map_rows=[_row("NAD", "BUY", 1313.0)],
                ledger={"cef_discount": (L, {"NAD": -6550.0, "NEA": -11683.0})})
    base.update(kw)
    return {c.name: c for c in vs.evaluate(**base)}


def test_a_day_that_worked_passes():
    """Real rows: order map NAD BUY 1313 at 10:38 ET 09-11; ledger NAD -6550 @
    09-10. Broker -5237 = -6550 + 1313."""
    c = _eval()
    assert c["fills"].status == vs.PASS
    assert c["positions"].status == vs.PASS
    assert c["resting"].status == vs.PASS
    assert vs.overall(list(c.values())) == vs.PASS


def test_an_order_that_did_not_fill_fails_on_both_fills_and_positions():
    c = _eval(executions=[_ex("NEA", "BOT", 5)],          # something else traded
              broker_positions={"NAD": -6550.0, "NEA": -11683.0})
    assert c["fills"].status == vs.FAIL and "NOT FILLED" in c["fills"].message
    assert c["positions"].status == vs.FAIL


def test_a_stacked_order_set_is_called_overfilled():
    """07-31's shape: the same order twice in one auction."""
    c = _eval(executions=[_ex("NAD", "BOT", 1313), _ex("NAD", "BOT", 1313)],
              broker_positions={"NAD": -3924.0, "NEA": -11683.0})
    assert c["fills"].status == vs.FAIL
    assert "OVERFILLED" in c["fills"].message
    assert c["positions"].status == vs.FAIL


def test_an_execution_nobody_sent_fails():
    c = _eval(executions=[_ex("NAD", "BOT", 1313), _ex("MHD", "SLD", 200)],
              broker_positions={"NAD": -5237.0, "NEA": -11683.0, "MHD": -200.0})
    assert c["fills"].status == vs.FAIL
    assert "UNEXPLAINED" in c["fills"].message


def test_after_the_gateway_restart_fills_are_unverified_not_passed():
    """No execution dated D on ANY symbol. The verifier must not read that as
    'nothing to check' -- it cannot tell a non-fill from a wiped session."""
    c = _eval(executions=[])
    assert c["fills"].status == vs.UNVERIFIED
    assert c["positions"].status == vs.PASS              # positions still decide
    assert vs.overall(list(c.values())) == vs.UNVERIFIED


def test_a_ledger_phantom_fails_even_where_the_broker_reports_no_row():
    """2026-09-10, null_trader: ledger JAAA -1503, broker has no JAAA row at all
    (IBKR emits none for a flat position). Absent must compare as zero."""
    c = _eval(universe={"null_trader": {"JAAA", "LQD"}},
              order_map_rows=[], executions=[],
              broker_positions={"LQD": -907.0},
              ledger={"null_trader": (L, {"JAAA": -1503.0, "LQD": -907.0})})
    assert c["positions"].status == vs.FAIL
    gap = next(r for r in c["positions"].rows if r["instrument"] == "JAAA")
    assert (gap["expected"], gap["broker"]) == (-1503.0, 0.0)


def test_orders_sent_after_the_ledgers_date_are_added_before_comparing():
    """The ledger lags by design when capture has not run; the verifier must not
    call that lag a divergence. Two auctions since the ledger's date."""
    rows = [_row("JFR", "SELL", 4630, "2026-09-10T01:46:28+00:00"),   # -> 09-10
            _row("NAD", "BUY", 1313)]                                  # -> 09-11
    c = _eval(order_map_rows=rows,
              executions=[_ex("NAD", "BOT", 1313)],
              broker_positions={"JFR": -10467.0, "NAD": -5237.0},
              ledger={"cef_discount": (dt.date(2026, 9, 9),
                                       {"JFR": -5837.0, "NAD": -6550.0})})
    assert c["positions"].status == vs.PASS, c["positions"].message


def test_a_resting_order_nobody_sent_to_a_later_auction_fails():
    t = {"instrument": "NAD", "action": "BUY", "qty": 1313.0,
         "order_type": "MOC", "status": "PreSubmitted"}
    assert _eval(open_trades=[t])["resting"].status == vs.FAIL


def test_a_resting_order_recorded_for_the_next_auction_passes():
    t = {"instrument": "NEA", "action": "SELL", "qty": 100.0,
         "order_type": "MOC", "status": "PreSubmitted"}
    rows = [_row("NAD", "BUY", 1313.0),
            _row("NEA", "SELL", 100, "2026-09-11T22:00:00+00:00")]    # -> 09-14
    c = _eval(open_trades=[t], order_map_rows=rows)
    assert c["resting"].status == vs.PASS


def test_contested_symbols_are_not_compared_on_the_account_net():
    c = _eval(contested={"NAD"}, executions=[_ex("NAD", "BOT", 99999)],
              broker_positions={"NAD": 1.0, "NEA": -11683.0})
    assert c["fills"].status == vs.PASS
    assert c["positions"].status == vs.PASS


def test_an_unparseable_timestamp_raises_rather_than_being_skipped():
    with pytest.raises(vs.VerifyInputError):
        _eval(order_map_rows=[_row("NAD", "BUY", 1, "last tuesday")])


@pytest.mark.parametrize("now, want", [
    (dt.datetime(2026, 9, 13, 21, 0, tzinfo=ET), dt.date(2026, 9, 11)),  # Sun
    (dt.datetime(2026, 9, 14, 15, 59, tzinfo=ET), dt.date(2026, 9, 11)),  # Mon pre-close
    (dt.datetime(2026, 9, 14, 16, 20, tzinfo=ET), dt.date(2026, 9, 14)),  # Mon post-close
    (dt.datetime(2026, 9, 8, 9, 0, tzinfo=ET), dt.date(2026, 9, 4)),      # after Labor Day
])
def test_the_default_auction_is_the_last_close_that_happened(now, want):
    assert vs.default_auction(now) == want


# -- the report must say when nobody was told --------------------------------

class _Halt:
    def __init__(self, email):
        self.email, self.beats, self.alerts = email, [], []

    def alert(self, subject, body="", speak=""):
        self.alerts.append(subject)
        return {"notification": True, "email": self.email}

    def beat(self, job, status, detail=None):
        self.beats.append((job, status, detail))


def test_every_day_sends_a_message_pass_or_fail(tmp_path, capsys):
    """Silence must never mean success: a PASS day still alerts."""
    h = _Halt(email=True)
    rc = vs._finish(h, "verify_cef", "cef", D,
                    [vs.Check("fills", vs.PASS, "ok")], tmp_path, "t", True, {})
    assert rc == 0 and h.alerts and "OK" in h.alerts[0]


def test_undelivered_email_is_printed_and_recorded(tmp_path, capsys):
    h = _Halt(email="not configured — add ALERT_SMTP_USER")
    rc = vs._finish(h, "verify_cef", "cef", D,
                    [vs.Check("positions", vs.FAIL, "gap")], tmp_path, "t",
                    True, {"x": 1})
    assert rc == 1
    assert "NOBODY AWAY FROM THIS MAC WAS TOLD" in capsys.readouterr().out
    assert h.beats[-1][1] == "failed"
    assert h.beats[-1][2]["email_delivered"] is False
    verdict = json.loads((tmp_path / "verdict_t.json").read_text())
    assert verdict["status"] == vs.FAIL
    assert (tmp_path / "broker_t.json").exists()


def test_exit_codes():
    assert vs.overall([vs.Check("a", vs.PASS, ""),
                       vs.Check("b", vs.UNVERIFIED, "")]) == vs.UNVERIFIED
    assert vs.overall([vs.Check("a", vs.UNVERIFIED, ""),
                       vs.Check("b", vs.FAIL, "")]) == vs.FAIL


def test_the_verifier_cannot_transmit():
    """Read from source, the way test_arm_called_once reads run_book."""
    src = (REPO / "ops" / "verify_session.py").read_text()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]                      # skip the docstring
    for forbidden in ("placeOrder(", "cancelOrder(", "reqGlobalCancel("):
        assert forbidden not in body
    assert "readonly=True" in body


# -- a book that silently stood down must not read as a band hold -------------

# The prod heartbeat's cef entry as read 2026-09-13 21:50, verbatim in shape.
BEAT_2026_09_12 = {"status": "ok_already_traded", "at": "2026-09-12 07:09:15",
                   "date": "2026-09-12",
                   "detail": {"armed": True, "rc": 0, "blockers": [],
                              "nav_via": "yfinance", "nav_ready_at": "22:00",
                              "pair_date": "2026-09-11"}}


def test_the_same_day_guards_armed_flag_is_not_a_decision():
    """launch_job files ok_already_traded with armed=True and pair 09-11 for a
    pair that was never traded. Read naively, Monday's close looks decided."""
    c = vs.decision_check(dt.date(2026, 9, 14), dt.date(2026, 9, 11),
                          {"cef": BEAT_2026_09_12}, ("cef", "cef_pm"), 0)
    assert c.status == vs.FAIL
    assert "NO session decided pair 2026-09-11" in c.message


def test_a_refused_fire_fails_even_with_nothing_else_wrong():
    """The 2026-09-14 configuration: W3 scheduler, old 17:15 plist, every fire
    refused past the cutoff. Zero orders, nothing resting -- still a FAIL."""
    beat = {"status": "ok_not_armed", "at": "2026-09-14 17:15:07",
            "session_date": "2026-09-11",
            "detail": {"armed": False, "rc": 0,
                       "blockers": ["past the 15:50 ET MOC entry cutoff"]}}
    c = vs.decision_check(dt.date(2026, 9, 15), dt.date(2026, 9, 14),
                          {"cef": beat}, ("cef", "cef_pm"), 0)
    assert c.status == vs.FAIL and "cutoff" in c.message


def test_an_armed_decision_with_no_orders_is_a_band_hold():
    beat = {"status": "ok", "at": "2026-09-09 21:46:40", "date": "2026-09-09",
            "detail": {"armed": True, "rc": 0, "pair_date": "2026-09-09"}}
    c = vs.decision_check(dt.date(2026, 9, 10), dt.date(2026, 9, 9),
                          {"cef": beat}, ("cef", "cef_pm"), 0)
    assert c.status == vs.PASS and "band hold" in c.message


def test_the_evening_fallback_counts_under_its_own_job_name():
    beat = {"status": "ok", "at": "2026-09-14 21:50:00",
            "session_date": "2026-09-14", "detail": {"armed": True}}
    c = vs.decision_check(dt.date(2026, 9, 15), dt.date(2026, 9, 14),
                          {"cef_pm": beat}, ("cef", "cef_pm"), 4)
    assert c.status == vs.PASS
