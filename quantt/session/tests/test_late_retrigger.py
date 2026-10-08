"""A session re-triggered just after the late send idles and submits nothing.

WHY THIS EXISTS
---------------
Measured on the prod VM (2026-10-07, systemd 255.4-1ubuntu8.17): a timer
firing that passes while its service is still running starts the service again
the moment it exits, even with Persistent=false. The 15:52 send polls its
orders until each is final (`_poll_final`). That usually takes seconds, so the
15:55 firing usually lands inside the window and idles on STARTED (covered by
test_run.py::test_late_scheduled_decides_once_then_sends_once). In the worst
case the poll runs to 30 s before the close (15:59:30), and the firing starts
a session just after the window, which is the case pinned here. systemd
has no setting on Ubuntu 24.04 that stops this (DeferReactivation= needs systemd
256 or later), so the runner's own gates are the ONLY guard on that path
(quantt/deploy/install_vm.py, SCHEDULE; docs/RUNBOOK.md section 8.2).

These tests pin the worst case at two moments: 15:59:31, the first second
after the longest poll ends, and 16:00:01, after the close. At these times the
session date has already rolled to the next day, so the date roll alone idles
the session. The STARTED guard proper, a re-trigger INSIDE the window, is
covered by test_run.py::test_late_scheduled_decides_once_then_sends_once. A new file,
so the runner's own test_run.py is left to its owners; the fixtures are
test_run's.
"""
from __future__ import annotations

import datetime as dt

import pytest

from quantt.session import run as rn
from quantt.session.tests import test_run as tr


@pytest.mark.parametrize("hms", [(15, 59, 31), (16, 0, 1)])
def test_a_session_retriggered_after_the_send_idles_and_submits_nothing(tmp_path, hms):
    c, deps, state, seen, out = tr.make(tmp_path, clock_ts=tr.EVE, execution=tr.LATE,
                                        now_utc=tr.utc(tr.EVE))
    (state / "AUTO_ARMED").touch()
    assert rn.run_session(tr.BOOK, tr.SPEC, deps, scheduled=True) == rn.EXIT_PLANNED
    tr.to_send_time(c, deps, tr.SEND)
    assert rn.run_session(tr.BOOK, tr.SPEC, deps, scheduled=True) == rn.EXIT_SENT
    sent = list(c.submits())
    assert sent                                    # the send really happened
    tr.to_send_time(c, deps, dt.datetime(2026, 9, 29, *hms, tzinfo=tr.ET))
    assert rn.run_session(tr.BOOK, tr.SPEC, deps, scheduled=True) == rn.EXIT_IDLE
    assert list(c.submits()) == sent               # nothing more went to Alpaca
