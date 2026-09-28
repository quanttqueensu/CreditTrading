"""A session that outlives its window must refuse to act, and the arithmetic
that decides it must be the SAME arithmetic the stuck-session guard uses.

THE INCIDENT, READ OFF THE LOG AND NOT RECALLED
-----------------------------------------------
Every timestamp below comes from
`~/prod/QUANTT/ops/schedule/logs/cef_2026-09-11.log`:

    [2026-09-11 17:15:05] launchd start (job=cef)
    [2026-09-11 22:00:52] today's NAV is published (yfinance) at 22:00
    [2026-09-12 07:09:11] panel scripts/cef/fetch_borrow_rates.py FAILED rc=1
    [2026-09-12 07:09:13] SAME-DAY GUARD: cef already ran ARMED today ...
    [2026-09-12 07:09:15] done status=ok_already_traded

The fire won its NAV race at 22:00:52 and the log's next timestamp is
07:09:11 the NEXT MORNING -- 13h54m into a window the installed plist and
`cef.env` say is 7h15m. The sleep is bounded by those two stamps and no
further: everything between them is the refresh's and the panel's own unstamped
output, so WHICH phase was running when the box went down is not established by
the log, and this guard does not need it to be. The session then ran preflight,
run_book and capture as though nothing had happened. It transmitted
nothing only because the same-day guard, which exists to answer an entirely
different question, happened to say no. Nothing in the session asked what time
it was.

WHY THE SUBPROCESS BUDGET CANNOT COVER THIS, which is why there are two halves
and not one: `subprocess.call(timeout=...)` is measured on a MONOTONIC clock,
and on Darwin that is mach_absolute_time(), which does not advance across
system sleep. Measured on this machine 2026-09-13: 3617h of wall clock since
boot against 1232h of monotonic, a 2385h gap. The budget bounds a hung child.
Only the wall clock can see a burned window.

WHAT THESE TESTS PIN. Not the wiring -- `ops/tests/test_patch_launch_job.py`
greps the built output for that. These test the NUMBER: that the ceiling
`ops/doctor.py::_session_deadline_minutes` derives is one the 09-11 timeline
actually exceeds, and that it stays that way on both sides of the 08:30/17:30
split, in either direction. A guard that is correct only under the schedule
installed on the afternoon it was written is the defect class this whole file
exists to stop.

Nothing here touches LaunchAgents, the broker, launchd or any file outside
tmp_path. `_ceiling` writes a real plist and a real .env and points doctor's two
module constants at them, so the plist parsing and the NAV_DEADLINE parsing are
exercised rather than stubbed.
"""
from __future__ import annotations

import datetime as dt
import plistlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import doctor  # noqa: E402

# The 2026-09-11 cef log, to the second.
STARTED = dt.datetime(2026, 9, 11, 17, 15, 5)
NAV_WON = dt.datetime(2026, 9, 11, 22, 0, 52)
RESUMED = dt.datetime(2026, 9, 12, 7, 9, 11)


def elapsed_from(start: dt.datetime, now: dt.datetime) -> float:
    """The patched launch_job's `session_elapsed_min`, in one line.

    Duplicated here on purpose: importing it would mean importing launch_job.py,
    which lives outside the repo, outside git and is the file that places
    orders. The property under test is arithmetic, and the arithmetic is one
    subtraction.
    """
    return (now - start).total_seconds() / 60.0


def elapsed(now: dt.datetime) -> float:
    return elapsed_from(STARTED, now)


def _ceiling(tmp_path, monkeypatch, job="cef", *, hour=None, minute=0,
             nav_deadline="23:30"):
    """`doctor._session_deadline_minutes(job)` against a plist we control.

    `hour=None` writes NO plist at all, which is the `cef_pm` case today: the
    job exists in JOBS and in launch_job.py's table but render_cef_plists.py has
    not run, so there is nothing to derive a ceiling from.
    """
    agents = tmp_path / "LaunchAgents"
    agents.mkdir(exist_ok=True)
    repo = tmp_path / "repo"
    (repo / "ops" / "schedule").mkdir(parents=True, exist_ok=True)
    if nav_deadline is not None:
        (repo / "ops" / "schedule" / f"{job}.env").write_text(
            f"# written by the test, mirroring ops/schedule/{job}.env\n"
            f"NAV_DEADLINE={nav_deadline}\n")
    if hour is not None:
        with open(agents / f"com.quantt.{job}.daily.plist", "wb") as fh:
            plistlib.dump({"Label": f"com.quantt.{job}.daily",
                           "StartCalendarInterval": [
                               {"Hour": hour, "Minute": minute, "Weekday": w}
                               for w in range(1, 6)]}, fh)
    monkeypatch.setattr(doctor, "AGENTS", agents)
    monkeypatch.setattr(doctor, "REPO_ROOT", repo)
    return doctor._session_deadline_minutes(job)


def test_the_evening_schedule_would_have_caught_2026_09_11(tmp_path, monkeypatch):
    """The schedule that was actually installed when it happened.

    17:15 start, NAV_DEADLINE=23:30, plus an hour of slack for trade and
    capture: 7h15m. The session was at 4h46m when it won its NAV race -- well
    inside, so the guard is not trigger-happy and would not have interrupted a
    normal night -- and at 13h54m when it resumed the next morning, which is the
    first boundary it would have stood down at.
    """
    c = _ceiling(tmp_path, monkeypatch, hour=17, minute=15)
    assert c == 435
    assert elapsed(NAV_WON) <= c
    assert elapsed(RESUMED) > c
    assert int(elapsed(RESUMED)) == 13 * 60 + 54


def test_the_morning_schedule_would_have_caught_it_too(tmp_path, monkeypatch):
    """The guard must survive the 08:30/17:30 render, in either direction.

    A pre-close fire cannot be waiting on a NAV that has not been struck yet, so
    it gets the ordinary two-hour ceiling rather than the NAV deadline -- and
    the same sleep, measured from 08:30, is 22h39m. A guard that only works
    under one of the two schedules is a guard that goes quiet on the day the
    schedule changes, which is the failure this repo keeps paying for.
    """
    c = _ceiling(tmp_path, monkeypatch, hour=8, minute=30)
    assert c == 120
    assert elapsed_from(dt.datetime(2026, 9, 11, 8, 30), RESUMED) > c


def test_the_evening_fallback_schedule_is_bounded(tmp_path, monkeypatch):
    """cef_pm at 17:30 against a 23:30 deadline: 6h + 1h of slack.

    The evening fallback is the fire that can legitimately sit on a NAV poll for
    hours, so it is the one most likely to be mistaken for unbounded. It is not.
    """
    assert _ceiling(tmp_path, monkeypatch, job="cef_pm",
                    hour=17, minute=30) == 420


def test_no_plist_means_no_deadline_rather_than_a_guessed_one(tmp_path,
                                                              monkeypatch):
    """NO SILENT FALLBACKS, in the direction that matters.

    A guessed ceiling would stand down healthy sessions -- the worst possible
    outcome for a guard whose only power is to refuse. So an underivable ceiling
    leaves the deadline INERT, and the session says so in its log
    ("NO SESSION CEILING", pinned in test_patch_launch_job.py) rather than going
    quiet about it. This is `cef_pm`'s state today: it is in doctor.JOBS and in
    launch_job.py's table, but render_cef_plists.py has not run.
    """
    assert _ceiling(tmp_path, monkeypatch, job="cef_pm", hour=None) is None


def test_an_unparseable_nav_deadline_is_not_rounded_into_a_number(tmp_path,
                                                                  monkeypatch):
    """A post-close job that DOES wait and cannot say until when gets None.

    The tempting fallback is the 120-minute default, which would stand down
    every evening session two hours in -- a guard that silently starts refusing
    the book's only trading fire. Refuse to answer instead.
    """
    assert _ceiling(tmp_path, monkeypatch, hour=17, minute=15,
                    nav_deadline="half past eleven") is None


def test_the_schedule_installed_on_this_machine_is_exceeded_by_that_timeline():
    """An INVARIANT, not a count.

    Whatever schedule is installed right now -- 17:15 today, 08:30 after the W3
    render, something else after a rollback -- a session that starts at its
    scheduled time and is still going at 07:09 the following morning is late.
    Asserting the ceiling's VALUE here would make this test a copy of the
    installed plist and it would go stale the day the plist is rendered; the
    same idiom test_session_uptime.py uses for the live trees.
    """
    c = doctor._session_deadline_minutes("cef")
    if c is None:
        pytest.skip("no cef plist installed on this machine")
    start = doctor._plist_start_minutes("cef")
    scheduled = dt.datetime(2026, 9, 11) + dt.timedelta(minutes=start)
    assert elapsed_from(scheduled, RESUMED) > c


def test_the_ceiling_is_the_one_the_stuck_session_guard_uses():
    """One derivation, judged from inside and outside with the same number.

    `check_stuck_sessions` compares `ps -o etime=` -- wall clock -- against
    `_session_deadline_minutes`. The patched launch_job calls the same function,
    so a session standing itself down and doctor calling it stuck can never
    disagree. Two derivations drift; this is the test that says there is one.
    """
    import inspect
    src = inspect.getsource(doctor.check_stuck_sessions)
    assert "_session_deadline_minutes(job)" in src
