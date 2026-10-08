"""A late send never STARTS a set it cannot finish inside the send window.

WHY THIS EXISTS (release-check #6, 2026-10-08)
----------------------------------------------
In late-market mode the decide phase ignores the clock, so a morning-backstop
decide that hangs until ~15:57:5x still saves a decided plan. The timer firing
queued during it starts a session the moment it exits (measured on the VM,
2026-10-07), and that session goes straight to the send. Gate 4 only checked
15:52 <= now < 15:58. Once STARTED is written, the batch stops at 15:58 (the
per-POST window check in `_transmit`). The result is a partial batch, a FAIL,
and STARTED blocking any retry. The fix refuses, before STARTED and before
any POST, a set whose time left to the window's end is under its budget:

    budget = n_orders x SEND_ALLOWANCE_PER_ORDER_S + SEND_MARGIN_S

The constants' provenance is in `quantt/session/gate.py`, and pinned below.
It must NOT change a set started at 15:52:0x, nor the 15:55 retry, at the live
book's size; both are tested here at that size.
"""
from __future__ import annotations

import datetime as dt
import json
import math

import pytest

from quantt.broker import alpaca
from quantt.session import gate as gt
from quantt.session import run as rn
from quantt.session import verify as vf
from quantt.session.tests import test_run as tr

ET = gt.ET
D = tr.D                                             # Tuesday 2026-09-29, 16:00 close
WIN = gt.late_window_et(D, "16:00", (8, 2))
EARLY = dt.date(2026, 11, 27)                        # a 13:00 close
WIN_EARLY = gt.late_window_et(EARLY, "13:00", (8, 2))
# The live book: one netted order per symbol at most, so the universe size is
# the largest set the runner sends (13 on 2026-09-29, 12 on 2026-10-07).
LIVE_N = len(rn.spec_params(rn.load_spec(rn.BOOKS["cef"].spec_path))["universe"])


def at(h, m, s=0, day=D):
    return dt.datetime.combine(day, dt.time(h, m, s), tzinfo=ET)


# -- the constants and their provenance ---------------------------------------------

def test_the_budget_constants_come_from_the_clients_schedule_and_the_measured_cycle():
    assert gt.SEND_ALLOWANCE_PER_ORDER_S == \
        alpaca.GET_BACKOFF_S[0] + math.ceil(gt.MEASURED_MAX_ORDER_CYCLE_S)
    # release-check #7: one stalled request can take connect + read timeouts
    # plus the first retry backoff, not the read timeout alone.
    assert gt.SEND_MARGIN_S == sum(alpaca.TIMEOUT_S) + alpaca.GET_BACKOFF_S[0]
    assert gt.send_budget_s(13) == 13 * 3 + 42


def test_the_live_book_is_the_size_these_tests_assume():
    assert LIVE_N == 13


# -- the gate, at the live book's size --------------------------------------------------

@pytest.mark.parametrize("now", [at(15, 52, 0), at(15, 52, 5), at(15, 55, 0), at(15, 55, 30)])
def test_a_live_size_set_at_1552_or_the_1555_retry_is_not_refused(now):
    assert gt.gate_late_send_budget(now, WIN, LIVE_N) == []


def test_a_live_size_set_starting_at_155755_is_refused():
    r = gt.gate_late_send_budget(at(15, 57, 55), WIN, LIVE_N)
    assert [x.gate for x in r] == ["clock"] and "SEND BUDGET" in r[0].detail, r


def test_the_boundary_is_exact():
    edge = WIN[1] - dt.timedelta(seconds=gt.send_budget_s(LIVE_N))
    assert gt.gate_late_send_budget(edge, WIN, LIVE_N) == []
    assert gt.gate_late_send_budget(edge + dt.timedelta(seconds=1), WIN, LIVE_N) != []


@pytest.mark.parametrize("now,refused", [(at(12, 52, 5, EARLY), False),
                                         (at(12, 55, 0, EARLY), False),
                                         (at(12, 57, 55, EARLY), True)])
def test_the_early_close_window_is_budgeted_the_same_way(now, refused):
    assert bool(gt.gate_late_send_budget(now, WIN_EARLY, LIVE_N)) is refused


def test_an_empty_set_needs_no_budget():
    assert gt.gate_late_send_budget(at(15, 57, 55), WIN, 0) == []


# -- through the runner ------------------------------------------------------------------

def decided_and_armed(tmp_path):
    c, deps, state, plan = tr.decided(tmp_path)
    (state / "AUTO_ARMED").touch()
    return c, deps, state, plan


@pytest.mark.parametrize("now", [at(15, 52, 5), at(15, 55, 0)])
def test_the_runner_still_sends_at_1552_and_at_the_1555_retry(tmp_path, now):
    c, deps, state, plan = decided_and_armed(tmp_path)
    tr.to_send_time(c, deps, now)
    assert rn.run_session(tr.BOOK, tr.SPEC, deps) == rn.EXIT_SENT
    assert c.submits()


@pytest.mark.parametrize("scheduled", [False, True])
def test_the_runner_refuses_a_set_at_155755_and_writes_no_started(tmp_path, scheduled):
    c, deps, state, plan = decided_and_armed(tmp_path)
    tr.to_send_time(c, deps, at(15, 57, 55))
    assert rn.run_session(tr.BOOK, tr.SPEC, deps, scheduled=scheduled) == rn.EXIT_REFUSED
    day = state / D.isoformat()
    assert not (day / "STARTED").exists()
    assert c.submits() == []
    send = json.loads((day / "send.json").read_text())
    assert "SEND BUDGET" in send["budget_short"]
    assert any("SEND BUDGET" in r["detail"] for r in send["refusals"])


# -- and the day FAILs, naming why ---------------------------------------------------------

def test_verify_fails_a_day_whose_send_was_refused_for_time():
    """Other send refusals (a halt, a dry run) explain a no-trade day. This one
    does not: the book should have traded and could not, so the day is a FAIL."""
    detail = "SEND BUDGET: 5s left in the send window for 13 order(s); the set needs 81s"
    plan = {"status": "decided", "orders": [{"client_order_id": "cef-20260929-AAA-1"}],
            "send_window": [str(WIN[0]), str(WIN[1])]}
    send = {"exit": "REFUSED", "refusals": [{"gate": "clock", "detail": detail}],
            "budget_short": detail}
    why, problem = vf.late_no_trade_reason(plan, send, D, "cef")
    assert why is None and "SEND BUDGET" in problem, (why, problem)


def test_verify_still_explains_an_ordinary_refusal():
    plan = {"status": "decided", "orders": [{"client_order_id": "x"}]}
    send = {"exit": "REFUSED", "refusals": [{"gate": "halt", "detail": "halt active"}]}
    why, problem = vf.late_no_trade_reason(plan, send, D, "cef")
    assert problem is None and "halt active" in why


def test_verify_explains_a_halted_or_dry_day_even_when_it_was_also_short_of_time():
    """release-check #7: a send refused by a halt, a dry run or the arming gate is
    an explained no-trade even if the budget refusal fired too. The budget FAIL
    is for a day whose only obstacle was the clock."""
    detail = "SEND BUDGET: 5s left in the send window for 13 order(s); the set needs 81s"
    plan = {"status": "decided", "orders": [{"client_order_id": "cef-20260929-AAA-1"}],
            "send_window": [str(WIN[0]), str(WIN[1])]}
    for gate, why_text in [("halt", "halt active"), ("dry_run", "DRY_RUN=1"),
                           ("arming", "not armed")]:
        send = {"exit": "REFUSED", "budget_short": detail,
                "refusals": [{"gate": gate, "detail": why_text},
                             {"gate": "clock", "detail": detail}]}
        why, problem = vf.late_no_trade_reason(plan, send, D, "cef")
        assert problem is None, (gate, problem)
        assert why_text in why and "SEND BUDGET" in why, (gate, why)
