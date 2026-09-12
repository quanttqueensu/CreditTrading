"""A session still alive long after its own deadline must be reported.

THE INCIDENT THIS ENCODES (2026-09-10/11)
-----------------------------------------
The 2026-09-10 cef session started 17:15, got NAV 0/17 from both yfinance and
CEFConnect all evening, polled past its 23:30 deadline, and was still alive at
10:32 the NEXT DAY — 17h17m, 0% CPU, no log line for 45 minutes. It never armed,
so nothing was transmitted; what it did was hold the CEF book's whole trading day
and block the promotion and the data refresh, while every existing guard read
green.

WHY NOTHING SAW IT, which is what determined where this check had to live:

  * `wait_for_nav` tests completeness BEFORE the deadline, deliberately. A poll
    that sleeps through 23:30 and wakes at 09:46 to find the data returns 0 and
    the session proceeds — ten hours late, on a stale decision. The deadline
    bounds the WAIT, not the session.
  * `check_launchd` reads a pid as "running". That is also what hung looks like.
  * `run_watchdog` compares heartbeat DATES. An unfinished session has written
    no heartbeat, and the arithmetic only trips after two business days: on the
    evening it broke, `missed` was 1 and it said all clear.

So the check asks the one question none of those ask — is a session still
running that cannot still be doing useful work — and it runs in `ops/doctor.py`,
which is out of band and which the watchdog already calls through
`doctor.failures()`.

THE CEILING IS DERIVED, NOT WRITTEN DOWN. cef's is its own NAV deadline:
`cef.env`'s `NAV_DEADLINE` minus the plist's `StartCalendarInterval`, plus an
hour of slack for the trade and capture phases. An unparseable deadline SKIPS
rather than guessing — the whole defect class here is a literal that stopped
matching reality, and a default would rebuild it.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import doctor  # noqa: E402


def _run(monkeypatch, *, running, age, ceiling):
    """Drive check_stuck_sessions with launchctl/ps/ceiling all stubbed."""
    class _P:
        def __init__(self, out):
            self.stdout = out

    monkeypatch.setattr(doctor.subprocess, "run",
                        lambda *a, **k: _P(running))
    monkeypatch.setattr(doctor, "_pid_age_minutes", lambda pid: age)
    monkeypatch.setattr(doctor, "_session_deadline_minutes", lambda job: ceiling)
    r = doctor.Report()
    doctor.check_stuck_sessions(r)
    return r.rows


CEF_RUNNING = "88099\t0\tcom.quantt.cef.daily\n-\t0\tcom.quantt.phase0.daily\n"
NONE_RUNNING = "-\t0\tcom.quantt.cef.daily\n-\t0\tcom.quantt.phase0.daily\n"


def test_the_real_hang_is_a_FAIL(monkeypatch):
    """17h17m against a 7h15m ceiling — the measured incident."""
    rows = _run(monkeypatch, running=CEF_RUNNING, age=17 * 60 + 17, ceiling=435)
    fails = [x for x in rows if x[0] == doctor.FAIL]
    assert len(fails) == 1
    assert fails[0][1] == "stuck:cef"
    assert "17h17m" in fails[0][2] and "7h15m" in fails[0][2]
    assert "launchctl kill" in fails[0][3], "the fix line must say what to do"


def test_a_normal_evening_session_is_a_PASS(monkeypatch):
    """17:15 start, still polling for NAV at 22:00 — four and three quarter
    hours, well inside the ceiling. This must NOT fire, or the check would
    interrupt the book on every ordinary night."""
    rows = _run(monkeypatch, running=CEF_RUNNING, age=4 * 60 + 45, ceiling=435)
    assert [x[0] for x in rows] == [doctor.PASS]


def test_exactly_at_the_ceiling_is_not_yet_stuck(monkeypatch):
    rows = _run(monkeypatch, running=CEF_RUNNING, age=435, ceiling=435)
    assert [x[0] for x in rows] == [doctor.PASS]


def test_nothing_running_reports_nothing(monkeypatch):
    assert _run(monkeypatch, running=NONE_RUNNING, age=999, ceiling=435) == []


def test_an_underivable_ceiling_warns_rather_than_guessing(monkeypatch):
    rows = _run(monkeypatch, running=CEF_RUNNING, age=999, ceiling=None)
    assert [x[0] for x in rows] == [doctor.WARN]
    assert "could not be derived" in rows[0][2]


def test_the_cef_ceiling_comes_from_cef_env_and_the_plist():
    """Derived, not written down: NAV_DEADLINE minus the scheduled start, +1h."""
    start = doctor._plist_start_minutes("cef")
    ceiling = doctor._session_deadline_minutes("cef")
    if start is None or ceiling is None:
        import pytest
        pytest.skip("cef plist or cef.env not present on this machine")
    env = (REPO / "ops/schedule/cef.env").read_text()
    raw = [l.split("=", 1)[1].strip() for l in env.splitlines()
           if l.startswith("NAV_DEADLINE=")][-1]
    hh, mm = (int(x) for x in raw.split(":"))
    assert ceiling == (hh * 60 + mm) - start + 60


def test_it_is_wired_into_the_watchdog_path():
    """`failures()` is what run_watchdog calls; a guard outside it is invisible."""
    import inspect
    src = inspect.getsource(doctor.failures)
    assert "check_stuck_sessions" in src


# -- the two-session split (2026-09-11) -----------------------------------
#
# The ceiling used to assume "cef is the job that waits for NAV". When cef
# moved to 08:30 that assumption computed 23:30 - 08:30 + 1h = 16 HOURS for a
# session that does not wait at all -- generous enough that the 17h17m hang
# this whole check exists for would have passed it. These pin the replacement,
# which reads the installed plist instead of assuming, so that it is right
# before the schedule changes, after it changes, and if it is rolled back.

def _ceiling(monkeypatch, starts):
    monkeypatch.setattr(doctor, "_plist_start_minutes",
                        lambda job: starts.get(job))
    return {job: doctor._session_deadline_minutes(job) for job in starts}


def test_a_pre_close_fire_gets_the_ordinary_ceiling_not_the_nav_deadline(monkeypatch):
    """08:30 cannot be waiting for a NAV that has not been struck yet.

    cef.env still carries NAV_DEADLINE=23:30 and must -- promote.sh derives its
    session window from that line. So the ceiling cannot key on the line's mere
    presence; it keys on the fire being after the close.
    """
    assert _ceiling(monkeypatch, {"cef": 8 * 60 + 30})["cef"] == 120


def test_the_evening_fire_still_gets_its_nav_deadline(monkeypatch):
    """cef_pm at 17:30 against a 23:30 deadline: 6h + 1h of slack."""
    got = _ceiling(monkeypatch, {"cef_pm": 17 * 60 + 30})["cef_pm"]
    assert got == (23 * 60 + 30) - (17 * 60 + 30) + 60 == 420


def test_the_ceiling_is_correct_before_the_split_is_installed(monkeypatch):
    """Rolled back, or simply not installed yet: 17:15 -> 23:30 is 7h15m.

    The dev tree changes before the plists do, so there is always a window
    where the code is new and the schedule is old. It has to be right there
    too, or promoting this change alone would false-alarm on every legitimate
    evening session.
    """
    assert _ceiling(monkeypatch, {"cef": 17 * 60 + 15})["cef"] == 435


def test_a_post_close_job_with_no_nav_deadline_is_not_skipped(monkeypatch):
    """benchmarks fires at 17:25 and never waits; it must get a real ceiling.

    Returning None here would SKIP the stuck check for it entirely, which is
    how a guard quietly stops covering a job.
    """
    assert _ceiling(monkeypatch, {"benchmarks": 17 * 60 + 25})["benchmarks"] == 120


def test_cef_pm_is_in_the_doctor_job_list():
    """A job absent from JOBS is unchecked by plists, launchd and stuck-session."""
    assert "cef_pm" in doctor.JOBS
