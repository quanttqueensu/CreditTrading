"""A session must not arm on a decision that is no longer the one scored.

WHY THIS FILE EXISTS
--------------------
2026-09-10: the cef session started 17:15, the Mac clamshell-slept at 19:51 on
battery, and `wait_for_nav.py` returned 0 -- the SUCCESS path -- at 09:46 the
next morning, because it tests completeness before it tests the deadline. The
book armed at 10:38:30 on 2026-09-11, 17h23m after its own launch. Nothing
downstream ever re-asked whether the decision was still actionable.

THE TRAP THIS FILE EXISTS TO PIN. That session still reached the RIGHT auction:
next_trading_day(2026-09-10) is 2026-09-11, and 10:38 is before the entry
freeze. So a guard built only on auction identity PASSES the very timeline it
was written for. It cost nothing by luck, not by design -- and it cost the next
session anyway, because the beat it filed on 09-11 made the same-day guard
refuse the 09-11 session. Both conditions, always: see ops/decision_age.py.

NO BROKER, NO NETWORK. `IBKRBroker` is built with `__new__` and `ib` is a stub
that raises if touched, which is itself the assertion that the refusal happens
before any broker round-trip.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.decision_age import DecisionAgeUnknown, refusal  # noqa: E402
from src.deploy.broker.ibkr import (  # noqa: E402
    DecisionTooOld, IBKRBroker, NotArmed,
)

ET = ZoneInfo("America/New_York")


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


# The real incident, to the minute, from
# ~/prod/QUANTT/ops/schedule/logs/cef_2026-09-10.log:1 and :39.
NINE_TEN_START = at(2026, 9, 10, 17, 15)
NINE_TEN_ARM = at(2026, 9, 11, 10, 38)


# --------------------------------------------------------------- the predicate

def test_the_2026_09_10_timeline_refuses():
    """THE ACCEPTANCE TEST. 17h23m late must not arm."""
    why = refusal("cef", "2026-09-10", now=NINE_TEN_ARM)
    assert why is not None
    assert "17h23m" in why, why


def test_that_same_timeline_reaches_the_correct_auction():
    """Proof the acceptance test needs the SESSION WINDOW, not auction identity.

    If this ever starts failing because the auction test began rejecting it,
    the guard has changed shape and the file above must be re-reasoned.
    """
    from ops.decision_age import reachable_auction
    import sys as _s
    _s.path.insert(0, str(REPO / "ops" / "schedule"))
    import nyse_calendar as cal

    assert reachable_auction(NINE_TEN_ARM) == dt.date(2026, 9, 11)
    assert cal.next_trading_day(dt.date(2026, 9, 10)) == dt.date(2026, 9, 11)


def test_a_normal_evening_session_arms():
    """yfinance published ~22:43-22:45 on the sessions that worked."""
    assert refusal("cef", "2026-09-10", now=at(2026, 9, 10, 22, 46)) is None


def test_the_nav_deadline_itself_is_inside_the_window():
    """23:30 is NAV_DEADLINE; a session that wins the race at the buzzer arms."""
    assert refusal("cef", "2026-09-10", now=at(2026, 9, 10, 23, 30)) is None


@pytest.mark.parametrize("hh,mm,expect_refusal", [(0, 29, False), (0, 31, True)])
def test_the_midnight_crossing_is_pinned_to_the_ceiling(hh, mm, expect_refusal):
    """Crossing midnight is allowed INSIDE the derived ceiling and not outside.

    cef: (23:30 NAV_DEADLINE - 17:15 plist start) + 1h slack = 435 min, so the
    boundary is 00:30. Derived at run time from ops/schedule/cef.env and the
    installed plist -- never written here, which is why this test asserts the
    BEHAVIOUR at the boundary rather than the number.
    """
    got = refusal("cef", "2026-09-10", now=at(2026, 9, 11, hh, mm))
    assert (got is not None) is expect_refusal, got


def test_friday_to_monday_is_one_session_not_three():
    """The regression test_ledger_behind_guard.py exists for, in this guard.

    A decision on Friday fills at MONDAY's close. "Tomorrow" is false every
    weekend and after every holiday.
    """
    assert refusal("cef", "2026-09-11", now=at(2026, 9, 11, 23, 0)) is None


def test_the_2026_09_11_session_refuses_at_its_real_wake_time():
    """The second incident: that session reached its book phase 07:09 Saturday."""
    assert refusal("cef", "2026-09-11", now=at(2026, 9, 12, 7, 9)) is not None


# ------------------------------------------------------- no silent fallbacks

def test_an_unknown_job_raises_rather_than_guessing_a_window():
    with pytest.raises(DecisionAgeUnknown) as e:
        refusal("no_such_job", "2026-09-10", now=at(2026, 9, 10, 22, 0))
    assert "no_such_job" in str(e.value)


def test_a_missing_decision_date_raises():
    with pytest.raises(DecisionAgeUnknown):
        refusal("cef", None, now=at(2026, 9, 10, 22, 0))


def test_a_naive_now_raises_rather_than_assuming_a_zone():
    """This machine is America/Toronto; a freeze time is an exchange fact."""
    with pytest.raises(DecisionAgeUnknown):
        refusal("cef", "2026-09-10", now=dt.datetime(2026, 9, 10, 22, 0))


# ------------------------------------------------------------------ via arm()

class _ExplodingIB:
    """Any attribute access is a broker round-trip that must not happen."""

    def __getattr__(self, name):
        raise AssertionError(
            f"arm() touched the broker (ib.{name}) before refusing a stale "
            f"decision; the refusal must precede sync_positions()")


def _broker():
    b = IBKRBroker.__new__(IBKRBroker)
    b.ib = _ExplodingIB()
    b._armed = True          # so we can prove the refusal clears it
    return b


def test_arm_refuses_the_09_10_timeline_without_touching_the_broker():
    b = _broker()
    with pytest.raises(DecisionTooOld):
        b.arm(decision_date=dt.date(2026, 9, 10), job="cef", now=NINE_TEN_ARM)
    assert b._armed is False


def test_decision_too_old_is_a_not_armed():
    """Existing `except NotArmed` call sites must already handle it."""
    assert issubclass(DecisionTooOld, NotArmed)


def test_arm_without_a_decision_date_still_works():
    """ops/rebuild_ledger.py is a recovery tool with no decision and no job.

    It must still arm -- and it proves the check is opt-in, which is why
    test_arm_called_once.py holds the LIVE call site to passing both.
    """
    b = _broker()
    with pytest.raises(AssertionError, match="touched the broker"):
        b.arm()          # reached sync_positions, i.e. was not refused early
