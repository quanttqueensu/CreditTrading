"""The transition matrix for the two-session cef schedule.

Every case here is a day the live book will actually have. They are written as
transitions rather than as unit assertions because the failure this guards
against is not a wrong return value -- it is two armed sessions whose beats are
individually correct and which together stack two order sets into one closing
auction. That only shows up across fires, so the tests run across fires.

The heartbeat shape is the real one: ops/halt.py::beat writes
{job: {"status", "at", "date", "detail": {...}}} and launch_job.py puts
"armed" and "pair_date" in the detail.
"""
import pytest

from ops import session_plan as sp


def beat(date, *, armed, pair_date=None, status="ok"):
    return {"status": status, "at": f"{date} 08:30:00", "date": date,
            "detail": {"armed": armed, "pair_date": pair_date}}


AM = 8 * 60 + 30      # 08:30
NOON = 12 * 60        # 12:00
LATE = 16 * 60 + 5    # 16:05, past the MOC cutoff


# -- the ordinary day ----------------------------------------------------

def test_morning_decides_the_previous_trading_day_not_today():
    """The asof IS the previous trading day.

    W3's "Do not" list opens with this one: leaving asof at today and letting
    the sleeve fall back to the last complete pair dates the ledger's fill
    tomorrow while the broker fills today.
    """
    p = sp.plan("cef", today="2026-09-14", prev_trading_day="2026-09-11",
                beats={}, minutes_now=AM)
    assert p.mode == sp.MORNING
    assert p.asof == "2026-09-11"
    assert p.may_arm and p.decides
    assert p.wait is False          # the pair published last night; no race left


def test_evening_is_capture_only_after_the_morning_armed():
    """The TODAY guard. Both pairs are legitimate; taking both is not.

    Morning of D decided pair D-1 for D's close. If the evening then decided
    pair D for D+1's close, the book would trade into two consecutive auctions
    at double the intended turnover -- and the PAIR guard cannot see it, because
    D-1 and D are different pairs.
    """
    beats = {"cef": beat("2026-09-14", armed=True, pair_date="2026-09-11")}
    p = sp.plan("cef_pm", today="2026-09-14", prev_trading_day="2026-09-11",
                beats=beats, minutes_now=17 * 60 + 30)
    assert p.mode == sp.CAPTURE_ONLY
    assert not p.may_arm and not p.decides
    assert "already decided today" in p.refusal


# -- the day the morning fails -------------------------------------------

def test_noon_retry_may_arm_after_a_failed_morning():
    """A stand-down is not a decision. 12:00 is the second chance, inside 15:50."""
    beats = {"cef": beat("2026-09-14", armed=False, pair_date="2026-09-11")}
    p = sp.plan("cef", today="2026-09-14", prev_trading_day="2026-09-11",
                beats=beats, minutes_now=NOON)
    assert p.may_arm, "a beat that never armed must not block the retry"


def test_noon_retry_is_refused_after_the_morning_armed():
    """The PAIR guard catches the retry on the same pair."""
    beats = {"cef": beat("2026-09-14", armed=True, pair_date="2026-09-11")}
    p = sp.plan("cef", today="2026-09-14", prev_trading_day="2026-09-11",
                beats=beats, minutes_now=NOON)
    assert not p.may_arm
    assert "2026-09-11" in p.refusal


def test_evening_falls_back_when_nothing_armed_today():
    """The 2026-09-08 behaviour, now the exception rather than the rule."""
    beats = {"cef": beat("2026-09-14", armed=False, pair_date=None)}
    p = sp.plan("cef_pm", today="2026-09-14", prev_trading_day="2026-09-11",
                beats=beats, minutes_now=17 * 60 + 30)
    assert p.mode == sp.EVENING
    assert p.asof == "2026-09-14", "the evening decides on TODAY's pair"
    assert p.wait is True and p.may_arm


def test_next_morning_is_refused_by_yesterdays_evening_fallback():
    """The transition the same-day guard structurally cannot make.

    cef_pm armed on the evening of D for pair D. The morning of D+1 wants pair
    D. Different calendar days, so `date == today` sees nothing; only the pair
    guard refuses it.
    """
    beats = {"cef": beat("2026-09-14", armed=False, pair_date=None),
             "cef_pm": beat("2026-09-14", armed=True, pair_date="2026-09-14")}
    p = sp.plan("cef", today="2026-09-15", prev_trading_day="2026-09-14",
                beats=beats, minutes_now=AM)
    assert not p.may_arm
    assert "cef_pm" in p.refusal and "2026-09-14" in p.refusal


# -- failing closed -------------------------------------------------------

def test_an_armed_beat_with_no_pair_date_blocks_any_pair():
    """Fail closed on an unlabelled decision.

    Beats written before pair_date existed, or by a crashed session, say armed
    with no pair. Letting those through would be resolving an ambiguity in the
    direction of transmitting, which this module may never do.
    """
    beats = {"cef_pm": beat("2026-09-14", armed=True, pair_date=None)}
    p = sp.plan("cef", today="2026-09-15", prev_trading_day="2026-09-14",
                beats=beats, minutes_now=AM)
    assert not p.may_arm


def test_dry_run_and_standdown_beats_never_block():
    """Otherwise a quiet week of stand-downs would lock the book out entirely."""
    beats = {"cef": beat("2026-09-14", armed=False, pair_date="2026-09-11"),
             "cef_pm": beat("2026-09-14", armed=False, pair_date="2026-09-14")}
    p = sp.plan("cef", today="2026-09-15", prev_trading_day="2026-09-14",
                beats=beats, minutes_now=AM)
    assert p.may_arm


def test_morning_refuses_past_the_moc_cutoff():
    """15:50 ET is an exchange rule: after it an MOC cannot be pulled at all."""
    p = sp.plan("cef", today="2026-09-14", prev_trading_day="2026-09-11",
                beats={}, minutes_now=LATE)
    assert not p.may_arm
    assert "15:50" in p.refusal


def test_force_trade_bypasses_the_pair_guard_but_never_the_cutoff():
    """A human may override a guard. Nobody can un-send an MOC."""
    beats = {"cef": beat("2026-09-14", armed=True, pair_date="2026-09-11")}
    assert sp.plan("cef", today="2026-09-14", prev_trading_day="2026-09-11",
                   beats=beats, minutes_now=NOON, force=True).may_arm
    late = sp.plan("cef", today="2026-09-14", prev_trading_day="2026-09-11",
                   beats=beats, minutes_now=LATE, force=True)
    assert not late.may_arm and "15:50" in late.refusal


def test_an_unknown_cef_job_raises_rather_than_defaulting_open():
    """A decision-making job absent from CEF_JOBS is invisible to both guards."""
    with pytest.raises(ValueError, match="CEF_JOBS"):
        sp.plan("cef_extra", today="2026-09-14", prev_trading_day="2026-09-11",
                beats={}, minutes_now=AM)


def test_every_decision_making_job_is_in_CEF_JOBS():
    """The registry the guards read must cover every job plan() will decide for.

    This is the assertion that keeps the blind spot from being reintroduced by
    someone adding a third fire.
    """
    for job in sp.CEF_JOBS:
        p = sp.plan(job, today="2026-09-14", prev_trading_day="2026-09-11",
                    beats={}, minutes_now=AM)
        assert p.job == job


def test_capture_only_still_refreshes_but_does_not_demand_the_pair():
    """The evening panel write is what tomorrow morning's decision reads.

    Easy to get backwards in both directions. Skipping the refresh entirely
    would leave the 08:30 session fetching a NAV nobody had written; demanding
    --require-asof would stand the evening down on a pair that normally
    completes at ~21:45, four hours after this job runs, and alert every night.
    """
    beats = {"cef": beat("2026-09-14", armed=True, pair_date="2026-09-11")}
    p = sp.plan("cef_pm", today="2026-09-14", prev_trading_day="2026-09-11",
                beats=beats, minutes_now=17 * 60 + 30)
    assert p.mode == sp.CAPTURE_ONLY
    assert p.require_asof is False


def test_every_deciding_plan_demands_its_pair():
    """A session that decides must prove the pair it decided on was complete."""
    morning = sp.plan("cef", today="2026-09-14", prev_trading_day="2026-09-11",
                      beats={}, minutes_now=AM)
    evening = sp.plan("cef_pm", today="2026-09-14", prev_trading_day="2026-09-11",
                      beats={}, minutes_now=17 * 60 + 30)
    for p in (morning, evening):
        assert p.decides and p.require_asof, p
