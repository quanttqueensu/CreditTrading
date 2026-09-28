"""`backup` must be VISIBLE to doctor, and must never roll back a promotion.

TWO FAILURES ARE PINNED HERE, AND THE SECOND IS THE SUBTLE ONE.

1. `backup` was absent from `doctor.JOBS` entirely. The job whose whole purpose
   is to replace git history as the ledgers' off-machine copy — and which the
   untracking is explicitly gated on — had been reporting `last exit 1` since it
   was scheduled, with nothing anywhere to say so.

2. Adding it plainly would have rebuilt the promotion deadlock in a new place.
   `promote.sh` rolls back on ANY non-zero `ops.doctor`, and `doctor` reads
   `launchctl list`, which reports MACHINE state — a checkout cannot change it.
   So a FAIL on `backup` would refuse every promotion, including the promotion
   that ships the fixed backup script. That is exactly the shape of the layer-3
   deadlock that rolled back the 11:36 promotion on 2026-09-10, and it is why
   `backup` is WARN and never FAIL: a failed archive does not stop the book
   trading, it stops it being recoverable, and those are different severities.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import doctor  # noqa: E402


def test_backup_is_in_the_jobs_list():
    assert "backup" in doctor.JOBS, (
        "the job the ledger untracking is gated on must be checked")


def test_backup_never_escalates_to_fail():
    """`promote.sh` rolls back on any non-zero doctor, and last-exit is machine
    state a checkout cannot change. A FAIL here refuses its own fix."""
    assert "backup" in doctor.JOB_NEVER_FAILS


def test_every_other_job_still_fails_on_a_bad_exit():
    """The exemption is for `backup` alone; a trading job that exits non-zero is
    still a FAIL, because that one does stop the book."""
    for job in ("cef", "phase0", "benchmarks", "watchdog"):
        assert job not in doctor.JOB_NEVER_FAILS, (
            f"{job} is on the trading path; a bad exit there must FAIL")


def test_the_two_backup_codes_say_different_things():
    """1 and 2 are not the same event, and `.1`'s script collapsed both to 1.

    2 = the archive exists and the LEDGERS are in it, something under data/ is
    not. 1 = there is no archive. Only the second means the ledgers are
    unbacked, which is what the untracking gate actually turns on.
    """
    one = doctor.JOB_CODE_MEANING[("backup", "1")]
    two = doctor.JOB_CODE_MEANING[("backup", "2")]
    assert one != two
    assert "NO archive" in one
    assert "INCOMPLETE" in two and "ledgers are in it" in two


def test_the_backup_plist_template_is_well_formed_xml():
    """A doubled hyphen is illegal inside an XML comment, and this file had
    three. Apple's parser accepted it, so launchd loaded the plist and
    `plutil -p` printed it, while `ops/doctor.py` reported it unreadable."""
    import re
    import xml.dom.minidom as minidom
    t = (REPO / "ops/schedule/com.quantt.backup.daily.plist.template").read_text()
    minidom.parseString(re.sub(r"@@[A-Z_]+@@", "0", t))
