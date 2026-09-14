"""The transition matrix for the two-session cef schedule.

Every case here is a day the live book will actually have. They are written as
transitions rather than as unit assertions because the failure this guards
against is not a wrong return value -- it is two armed sessions whose beats are
individually correct and which together stack two order sets into one closing
auction. That only shows up across fires, so the tests run across fires.

The heartbeat shape is the real one: ops/halt.py::beat writes
{job: {"status", "at", "date", "session_date", "detail": {...}}} and
launch_job.py puts "armed" and "pair_date" in the detail.

TWO BEAT SHAPES, AND BOTH ARE LIVE. `session_date` was added 2026-09-13; every
beat in ops/heartbeat.json that day predates it and has only the other four
keys. The `beat()` factory below writes the OLD shape and is what the original
cases use; `modern()` and `legacy()`, further down, are the pair that makes the
difference testable. A guard that reads only the new field would refuse the
first fire after the promotion, on beats it could not label.
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


# =========================================================================
# LIMIT C (2026-09-13): the two questions, and the beats that predate the
# `session_date` field.
#
# The incident: a cef session started 17:15 on 2026-09-10, the Mac
# clamshell-slept, and the beat landed 10:38:32 on 2026-09-11 with
# `date` 2026-09-11 and `armed` true -- for a decision about 2026-09-10. Both
# guards used to read `date`, so the pair question could not see yesterday
# evening's fallback at all, and the date question refused the 09-11 session on
# a beat that described 09-10. One power event, two lost sessions
# (ops/decision_age.py).
#
# The fix is NOT to re-key both questions. It is to key them on DIFFERENT
# fields, because they are different questions -- which is what the
# anti-collapse test below exists to keep true.
# =========================================================================

def modern(date, *, armed, session_date=None, pair_date=None):
    """A beat as ops/halt.py::beat writes one since `session_date` existed."""
    return {"status": "ok", "at": f"{date} 10:38:32", "date": date,
            "session_date": session_date,
            "detail": {"armed": armed, "pair_date": pair_date}}


def legacy(date, *, armed, pair_date=None):
    """A beat with NO top-level `session_date` key at all.

    Not hypothetical: on 2026-09-13 every beat in ops/heartbeat.json has
    exactly these four top-level keys. If the pair question read only the new
    field, every one of them would be an armed beat with no recorded pair --
    the fail-closed branch -- and the first fire after the promotion would be
    refused for no reason at all.
    """
    return {"status": "ok", "at": f"{date} 10:38:32", "date": date,
            "detail": {"armed": armed, "pair_date": pair_date}}


# The 2026-09-11 10:38:32 beat, as the heartbeat would record it today.
LIMIT_C = {"cef": {"status": "ok", "at": "2026-09-11 10:38:32",
                   "date": "2026-09-11", "session_date": "2026-09-10",
                   "detail": {"armed": True, "pair_date": "2026-09-10"}}}


def test_the_pair_question_reads_session_date_not_the_filing_date():
    """The 09-10 session filed on 09-11. The pair it decided is 09-10."""
    assert sp.pair_already_decided(LIMIT_C, "2026-09-10") == "cef"
    assert sp.pair_already_decided(LIMIT_C, "2026-09-11") is None


def test_the_today_question_reads_the_filing_date_not_the_pair():
    """And it must keep doing so: that beat's order set went out on 09-11.

    `ops/decision_age.py` already calls the 09-11 refusal CORRECT. Re-keying
    this question on the pair would have let that session transmit a second set
    into an auction one had already gone into.
    """
    assert sp.decided_today(LIMIT_C, "2026-09-11") == "cef"
    assert sp.decided_today(LIMIT_C, "2026-09-10") is None


def test_neither_question_can_answer_the_other():
    """THE ANTI-COLLAPSE TEST. Do not "simplify" the guard back into one.

    One beat, asked about 2026-09-10: the pair question says "cef", the today
    question says None. Point either at the other's key and this flips.
    """
    assert sp.pair_already_decided(LIMIT_C, "2026-09-10") == "cef"
    assert sp.decided_today(LIMIT_C, "2026-09-10") is None


def test_a_beat_that_predates_session_date_falls_back_to_detail_pair_date():
    """The live heartbeat on 2026-09-13 is entirely of this shape."""
    beats = {"cef": legacy("2026-09-11", armed=True, pair_date="2026-09-10")}
    assert "session_date" not in beats["cef"]
    assert sp.pair_already_decided(beats, "2026-09-10") == "cef"
    assert sp.pair_already_decided(beats, "2026-09-11") is None


def test_an_armed_beat_with_session_date_absent_and_no_pair_date_blocks_any_pair():
    """Absent must NOT silently pass. An unlabelled armed set is a live set."""
    beats = {"cef_pm": legacy("2026-09-14", armed=True, pair_date=None)}
    for pair in ("2026-09-11", "2026-09-14", "1999-01-01"):
        assert sp.pair_already_decided(beats, pair) == "cef_pm", pair


def test_an_armed_beat_with_session_date_explicitly_null_blocks_any_pair():
    """Present-and-None is treated exactly like absent, and for one reason.

    Absent means "filed before the field existed"; None means "beat() ran and
    the detail named no decision". Both say the same thing to a guard -- this
    beat does not tell you which decision it was about -- and the only
    defensible answer to that from an ARMED beat is to fail closed.
    """
    beats = {"cef_pm": modern("2026-09-14", armed=True, session_date=None,
                              pair_date=None)}
    assert beats["cef_pm"]["session_date"] is None
    assert sp.pair_already_decided(beats, "2026-09-11") == "cef_pm"


def test_a_stand_down_with_no_session_date_never_blocks_anything():
    """The fail-closed branch is reachable only from an ARMED beat.

    Otherwise a quiet week -- every beat armed=False, session_date None by
    construction -- would lock the book out of every later fire, which fails in
    the direction this desk pays for in uptime rather than in safety.
    """
    beats = {"cef": modern("2026-09-14", armed=False, session_date=None),
             "cef_pm": legacy("2026-09-14", armed=False)}
    assert sp.pair_already_decided(beats, "2026-09-11") is None
    assert sp.decided_today(beats, "2026-09-14") is None


def test_the_top_level_field_wins_over_a_stale_detail_pair_date():
    """Read ORDER is pinned, not incidental: session_date first, then detail."""
    beats = {"cef": modern("2026-09-14", armed=True,
                           session_date="2026-09-11", pair_date="1999-01-01")}
    assert sp.pair_already_decided(beats, "2026-09-11") == "cef"
    assert sp.pair_already_decided(beats, "1999-01-01") is None


def test_a_decision_date_carrying_a_time_still_matches_the_pair():
    """Ten characters on BOTH sides, and neither side may assume the other.

    `ops/halt.py::beat` already truncates what it writes, so the beat side of
    this looks redundant -- it is not. The two writers are in different trees
    and only one is behind ops/promote.sh: `beat()` is in the repo, and the
    detail dict it truncates comes from launch_job.py, which is outside git and
    can be hand-edited live. A guard that silently stops matching because a
    caller passed "2026-09-10 16:00:00" instead of "2026-09-10" fails OPEN --
    it reports no prior decision, which is read as permission to transmit.

    Dropping either `[:10]` breaks this test and nothing else in the suite;
    that was measured 2026-09-13 by mutation, not assumed.
    """
    beats = {"cef": modern("2026-09-11", armed=True,
                           session_date="2026-09-10 16:00:00")}
    assert sp.pair_already_decided(beats, "2026-09-10") == "cef"
    assert sp.pair_already_decided(beats, "2026-09-10 16:00:00") == "cef"
    assert sp.pair_already_decided(beats, "2026-09-11") is None


def test_a_different_pair_on_the_same_day_is_caught_only_by_the_today_question():
    """Two fires, different pairs, both before the 15:50 freeze: ONE auction.

    `plan()` asks only the PAIR question for the morning job, and it passes
    here -- asserted in code rather than described, because that pass is the
    whole reason launch_job.py has to ask the second question immediately
    before the order goes out.
    """
    beats = {"cef": modern("2026-09-15", armed=True,
                           session_date="2026-09-14", pair_date="2026-09-14")}
    p = sp.plan("cef", today="2026-09-15", prev_trading_day="2026-09-11",
                beats=beats, minutes_now=AM)
    assert p.may_arm, "the pair question genuinely does not see this"
    assert sp.decided_today(beats, "2026-09-15") == "cef"
