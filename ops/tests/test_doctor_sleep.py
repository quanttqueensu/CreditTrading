"""The sleep check must MEASURE the machine, and must never refuse a promotion.

WHAT WENT WRONG, 2026-09-10
---------------------------
The cef session started 17:15:05 and polled for the day's NAV. At 19:51:36 the
machine entered clamshell sleep on battery at 20%, and the next poll landed at
09:46:26 the following morning — it armed at 10:38 for asof=2026-09-10, 17
hours late and during market hours. Four MOC orders had already filled at the
09-10 close; TWS had restarted by the time capture ran, so `ib.fills()` returned
0 and the execution record for those four fills is gone for good.

Doctor was at WARN on `sleep` throughout, and its message was a fixed sentence:
it read only `pmset -g sched` and said the same words on a plugged-in machine
with the lid open as on this one. These tests pin the three things that changed.

1. IT NEVER RETURNS FAIL. `ops/promote.sh` rolls back on any non-zero
   `ops.doctor`, and power source, lid angle and wake schedule are machine state
   a `git checkout` cannot change — so a FAIL would refuse every promotion for
   as long as the lid was shut, including the promotion carrying the fix. This
   is the deadlock `test_doctor_backup_job.py` pins for `backup`, in a second
   place.

2. A SCHEDULED WAKE DOES NOT BUY A PASS. At 21:26:57 that night an unrelated
   rtc timer did wake the machine; it polled once at 21:27:24 and was asleep
   again at 21:28:54. 117 seconds. `sudo pmset repeat wakeorpoweron` is the
   remedy everyone reaches for first, and last night measured what it is worth
   on its own.

3. THE AWAKE WINDOW IS COMPUTED, NOT WRITTEN DOWN. The sentence this replaced
   said "09:00-20:00" while com.quantt.awake had always run `-t 54000` — 15
   hours, so 09:00-00:00. Prose goes stale; the plist cannot.
"""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import doctor  # noqa: E402

STATES = [(b, l, d, w)
          for b in (True, False, None)
          for l in (True, False, None)
          for d in (True, False)
          for w in (True, False)]


def _run(monkeypatch, batt, lid, disabled, wake, held=True, causes=True):
    # `causes` is macOS's own AppleClamshellCausesSleep. It defaults to True so
    # every pre-existing case keeps testing the dangerous configuration; the
    # clamshell-mode case passes causes=False explicitly.
    monkeypatch.setattr(doctor, "on_battery", lambda: batt)
    monkeypatch.setattr(doctor, "lid_closed", lambda: lid)
    monkeypatch.setattr(doctor, "clamshell_causes_sleep", lambda: causes)
    monkeypatch.setattr(doctor, "sleep_disabled", lambda: disabled)
    monkeypatch.setattr(doctor, "awake_window", lambda: ("09:00", "00:00"))
    monkeypatch.setattr(doctor, "_cmd", lambda argv: (
        "wakeorpoweron at ..." if argv[:3] == ["pmset", "-g", "sched"] and wake
        else "" if argv[:3] == ["pmset", "-g", "sched"]
        else "com.quantt.awake" if held else ""))
    r = doctor.Report()
    doctor.check_sleep(r)
    assert len(r.rows) == 1
    return r.rows[0]


def test_never_fails_in_any_machine_state(monkeypatch):
    """A FAIL here refuses the promotion that would fix it. See module docstring."""
    for batt, lid, disabled, wake in STATES:
        level, _, msg, _ = _run(monkeypatch, batt, lid, disabled, wake)
        assert level != doctor.FAIL, (
            f"batt={batt} lid={lid} disablesleep={disabled} wake={wake} "
            f"returned FAIL, which would roll back every promotion: {msg}")


def test_battery_is_reported_because_it_voids_caffeinate(monkeypatch):
    """`caffeinate -s` is valid only on AC (man caffeinate), so on battery the
    com.quantt.awake job is holding nothing. That is the 19:51:36 state."""
    level, _, msg, _ = _run(monkeypatch, batt=True, lid=False,
                            disabled=False, wake=False)
    assert level == doctor.WARN
    assert "BATTERY" in msg


def test_closed_lid_is_reported_even_on_ac(monkeypatch):
    """Clamshell sleep beat a caffeinate PreventSystemSleep assertion that had
    been held 10h54m, on AC at 100%, at 2026-09-10 00:46:31.

    AC alone does not make a shut lid safe -- clamshell MODE also needs an
    external display attached, and macOS reports the combined verdict in
    AppleClamshellCausesSleep. That night it said Yes.
    """
    level, _, msg, _ = _run(monkeypatch, batt=False, lid=True,
                            disabled=False, wake=False, causes=True)
    assert level == doctor.WARN
    assert "CLOSED" in msg


def test_clamshell_mode_is_not_an_alarm(monkeypatch):
    """THE FALSE POSITIVE, found 2026-09-11 by the team lead asking "what lid?".

    This desk runs a MacBook Air (Mac14,2) lid-shut on AC with an external
    display -- ordinary clamshell mode. macOS reports:

        "AppleClamshellCausesSleep" = No
        "AppleClamshellState"       = Yes

    The first version read only the second line and announced "THE EVENING
    SESSION IS UNPROTECTED" in the configuration the desk runs in every day.
    That is exactly the defect the rewrite existed to remove -- the old check
    "said the same words on a plugged-in machine with the lid open" -- rebuilt
    one IOKit key over. A guard that cries wolf in the normal case gets read
    past, and is then worth less than nothing.
    """
    level, _, msg, _ = _run(monkeypatch, batt=False, lid=True,
                            disabled=False, wake=False, causes=False)
    assert level == doctor.PASS, f"clamshell mode must not alarm: {msg}"
    assert "will not sleep" in msg
    assert "Losing AC flips that" in msg, (
        "a PASS on a shut lid must still name the thing that would change it")


def test_an_unreadable_clamshell_verdict_stays_conservative(monkeypatch):
    """Unknown is treated as dangerous: a false alarm costs a line in a report,
    a false all-clear costs a session."""
    level, _, msg, _ = _run(monkeypatch, batt=False, lid=True,
                            disabled=False, wake=False, causes=None)
    assert level == doctor.WARN
    assert "could not be read" in msg


def test_disablesleep_clears_the_closed_lid(monkeypatch):
    """`pmset disablesleep 1` is the only setting that defeats clamshell."""
    level, _, _, _ = _run(monkeypatch, batt=False, lid=True,
                          disabled=True, wake=False)
    assert level == doctor.PASS


def test_a_scheduled_wake_does_not_rescue_a_sleeping_machine(monkeypatch):
    """2026-09-10 21:26:57: a wake fired, one poll got through, asleep again at
    21:28:54. A wake without a holding assertion is worth 117 seconds."""
    level, _, msg, _ = _run(monkeypatch, batt=True, lid=True,
                            disabled=False, wake=True)
    assert level == doctor.WARN, "a scheduled wake must not upgrade this to PASS"
    assert "117 seconds" in msg


def test_unreadable_power_or_lid_is_not_treated_as_healthy(monkeypatch):
    """NO SILENT FALLBACKS: a probe that cannot run is unknown, never fine."""
    for batt, lid in ((None, False), (False, None)):
        level, _, msg, _ = _run(monkeypatch, batt=batt, lid=lid,
                                disabled=False, wake=False)
        assert level == doctor.WARN
        assert "could not read" in msg


def test_healthy_machine_passes(monkeypatch):
    level, _, _, _ = _run(monkeypatch, batt=False, lid=False,
                          disabled=False, wake=True)
    assert level == doctor.PASS


def test_awake_window_is_derived_from_the_plist(monkeypatch, tmp_path):
    """The old prose said 09:00-20:00 against a job that ran -t 54000 (15h).
    Change the plist and the reported window must change with it."""
    (tmp_path / "com.quantt.awake.plist").write_bytes(plistlib.dumps({
        "ProgramArguments": ["/usr/bin/caffeinate", "-s", "-t", "54000"],
        "StartCalendarInterval": [{"Hour": 9, "Minute": 0, "Weekday": 1}],
    }))
    monkeypatch.setattr(doctor, "AGENTS", tmp_path)
    assert doctor.awake_window() == ("09:00", "00:00")

    (tmp_path / "com.quantt.awake.plist").write_bytes(plistlib.dumps({
        "ProgramArguments": ["/usr/bin/caffeinate", "-s", "-t", "3600"],
        "StartCalendarInterval": {"Hour": 7, "Minute": 30},
    }))
    assert doctor.awake_window() == ("07:30", "08:30")


def test_awake_window_is_none_when_the_plist_is_unparseable(monkeypatch, tmp_path):
    """No -t means no window to compute; report nothing rather than guess."""
    (tmp_path / "com.quantt.awake.plist").write_bytes(plistlib.dumps({
        "ProgramArguments": ["/usr/bin/caffeinate", "-s"],
        "StartCalendarInterval": [{"Hour": 9}],
    }))
    monkeypatch.setattr(doctor, "AGENTS", tmp_path)
    assert doctor.awake_window() is None


def test_sleep_check_is_registered_with_the_watchdog():
    """It runs via doctor.failures(); if it were dropped from that list the
    watchdog would stop seeing it at all."""
    import inspect
    assert "check_sleep" in inspect.getsource(doctor.failures)


def test_an_unreadable_plist_is_reported_not_silently_blank(monkeypatch, tmp_path):
    """NO SILENT FALLBACKS, demonstrated on this very check while writing it.

    A comment containing `--` is illegal inside an XML comment. `plutil -lint`
    accepts it; plistlib (expat) does not. Adding one to the awake plist made
    `awake_window()` return None, and the message then read exactly as it would
    for a machine with no awake job configured at all. The two must not look
    the same: one is "nothing is holding this box awake", the other is "the
    thing holding it awake has a broken config file".
    """
    (tmp_path / "com.quantt.awake.plist").write_text("<not a plist>")
    monkeypatch.setattr(doctor, "AGENTS", tmp_path)
    monkeypatch.setattr(doctor, "on_battery", lambda: False)
    monkeypatch.setattr(doctor, "lid_closed", lambda: False)
    monkeypatch.setattr(doctor, "sleep_disabled", lambda: False)
    monkeypatch.setattr(doctor, "_cmd", lambda argv: (
        "wakeorpoweron" if argv[:3] == ["pmset", "-g", "sched"]
        else "com.quantt.awake"))
    r = doctor.Report()
    doctor.check_sleep(r)
    assert "UNREADABLE" in r.rows[0][2]
