"""The decision-age guard must not be able to fail open silently.

`arm(decision_date=..., job=...)` are keyword-only and default to None, so
ops/rebuild_ledger.py -- a recovery tool with neither a decision nor a schedule
-- still arms. That default is a deliberate hole with two halves:

  * the IN-REPO half is held shut structurally by
    src/deploy/tests/test_arm_called_once.py;
  * the SCHEDULER half cannot be. `launch_job.py` lives outside the repo, is
    not in git, and is not gated by ops/promote.sh, so a green suite says
    nothing about whether the INSTALLED copy passes `--job`.

This file covers the check that closes the second half by making the inert
state visible. Each test was confirmed to fail against the pre-change
behaviour before being kept.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import doctor  # noqa: E402

PATCHER = REPO / "ops" / "schedule" / "patch_launch_job_w3am.py"


def _row(tmp_path, src: str):
    f = tmp_path / "launch_job.py"
    f.write_text(src)
    orig, doctor.LAUNCH_JOB = doctor.LAUNCH_JOB, f
    try:
        r = doctor.Report()
        doctor.check_decision_age_wiring(r)
        return r.rows
    finally:
        doctor.LAUNCH_JOB = orig


def _patcher():
    spec = importlib.util.spec_from_file_location("patch_w3am", PATCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_an_unwired_scheduler_is_reported_not_silent(tmp_path):
    rows = _row(tmp_path, 'args = [PY_BIN, "-m", "src.deploy.run_book", "--asof", today]\n')
    assert len(rows) == 1
    level, name, msg, _fix = rows[0]
    assert level == doctor.WARN and name == "decision-age"
    assert "INERT" in msg


def test_a_wired_scheduler_passes(tmp_path):
    rows = _row(tmp_path, 'args = [PY_BIN, "-m", "src.deploy.run_book", "--job", job]\n')
    assert rows[0][0] == doctor.PASS


def test_the_real_patcher_produces_a_wired_file(tmp_path):
    """End to end: applying the patch must flip the check to PASS.

    This is the test that would have caught a patch that edits the right file
    in the wrong place -- the guard and the thing that wires it, checked
    against each other rather than each against its own assumption.
    """
    p = _patcher()
    if not p.TARGET.exists():
        pytest.skip(f"launch_job.py not on this machine ({p.TARGET})")
    assert _row(tmp_path, p.build(p.TARGET.read_text()))[0][0] == doctor.PASS


def test_a_file_that_does_not_run_the_book_says_so_rather_than_passing(tmp_path):
    """NO SILENT FALLBACKS: 'cannot tell' must never render as 'fine'."""
    level, _n, msg, _f = _row(tmp_path, "print('not the scheduler')\n")[0]
    assert level == doctor.WARN and "cannot tell" in msg


def test_both_doctor_sequences_run_the_check():
    """doctor keeps TWO check lists -- failures() and main() -- and they drift.

    check_decision_age_wiring was added to failures() first and did not appear
    in main() at all; only running the tool caught it. A check registered in
    one list and not the other is a guard that exists in exactly half the
    places that matter.
    """
    src = (REPO / "ops" / "doctor.py").read_text()
    assert src.count("check_decision_age_wiring") >= 3, (
        "expected the definition plus a registration in BOTH failures() and "
        "main(); one of them is missing")
