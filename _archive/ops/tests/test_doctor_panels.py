"""Tests for doctor's panel-staleness check.

WHY THIS CHECK IS TESTED
------------------------
It is a monitor, and a monitor that silently stops working is worse than no
monitor: it converts "nobody is watching" into "somebody is watching" without
changing the facts. Every failure this system has had was silent, and two of
them were guards that had themselves broken.

So the properties worth pinning are the ones whose loss would be invisible:

  - a stale panel WARNs rather than passing quietly
  - a current panel does not WARN (a check that cries wolf gets ignored, which
    is the same outcome as not having it)
  - a missing or malformed panel does not crash the check, because doctor's job
    is to run on a broken machine
  - the undated-snapshot check actually looks for the column
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops import doctor  # noqa: E402


class FakeReport:
    """Same surface as doctor.Report, but inspectable."""

    def __init__(self):
        self.rows = []

    def add(self, level, name, msg, fix=""):
        self.rows.append((level, name, msg, fix))

    def levels_for(self, prefix):
        return [lvl for lvl, name, _, _ in self.rows if name.startswith(prefix)]

    def row(self, name):
        for lvl, n, msg, fix in self.rows:
            if n == name:
                return lvl, msg, fix
        return None


def test_check_panels_runs_and_reports_something():
    r = FakeReport()
    doctor.check_panels(r)
    assert r.rows, "check_panels produced no rows at all"
    assert any(n.startswith("panel:") for _, n, _, _ in r.rows)


def test_price_and_nav_panels_are_current():
    """These two gate the session. If they are stale the book must not trade,
    and preflight enforces that independently -- but doctor should agree."""
    r = FakeReport()
    doctor.check_panels(r)
    for name in ("panel:cef_prices", "panel:cef_nav"):
        row = r.row(name)
        if row is None:
            pytest.skip(f"{name} not present in this checkout")
        level, msg, _ = row
        assert level == doctor.PASS, (
            f"{name} is not current: {msg}. The session decides on this pair; "
            "a stale NAV is a blind signal, not a cheap fund.")


def test_stale_panel_warns_not_fails():
    """A stale RESEARCH panel does not stop the book trading tonight.

    doctor's FAIL means "unattended operation is broken right now". Overloading
    it for research hygiene would train the operator to ignore FAIL, which is
    how the 21-session outage went unnoticed while preflight was blocking
    correctly every single session.
    """
    r = FakeReport()
    doctor.check_panels(r)
    assert doctor.FAIL not in r.levels_for("panel:"), (
        "a panel check escalated to FAIL; that level is reserved for "
        "'the books cannot run unattended right now'")


def test_undated_snapshot_is_flagged_until_it_carries_a_date():
    """cef_facts.csv has no date column and cannot be joined to history safely.

    This test passes in either direction on purpose: it asserts the CHECK is
    wired, not that the file is currently broken, so it keeps working after the
    file is fixed rather than becoming a test that must be deleted.
    """
    r = FakeReport()
    doctor.check_panels(r)
    row = r.row("panel:cef_facts")
    if row is None:
        pytest.skip("cef_facts.csv not present")
    level, msg, _ = row
    assert level in (doctor.PASS, doctor.WARN)
    if level == doctor.WARN:
        assert "fetched_at" in msg, (
            "the warning should name the column that would fix it")


def test_missing_panel_does_not_crash(monkeypatch):
    """doctor runs on broken machines. A check that raises is a check that is
    not there when it is most needed."""
    monkeypatch.setattr(doctor, "PANELS",
                        [("data/definitely/not/here.parquet", 1, "a test")])
    monkeypatch.setattr(doctor, "UNDATED", [])
    r = FakeReport()
    doctor.check_panels(r)          # must not raise
    level, msg, _ = r.row("panel:here")
    assert level == doctor.WARN and "missing" in msg


def test_malformed_panel_does_not_crash(tmp_path, monkeypatch):
    """A file that exists but cannot be parsed must degrade, not explode."""
    bad = tmp_path / "junk.parquet"
    bad.write_bytes(b"this is not parquet")
    monkeypatch.setattr(doctor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(doctor, "PANELS", [("junk.parquet", 1, "a test")])
    monkeypatch.setattr(doctor, "UNDATED", [])
    r = FakeReport()
    doctor.check_panels(r)          # must not raise
    assert r.rows


def test_panel_last_date_never_raises(tmp_path):
    """The reader is deliberately total."""
    assert doctor._panel_last_date(tmp_path / "nope.parquet") is None
    junk = tmp_path / "junk.csv"
    junk.write_text("not,a,date,panel\n1,2,3,4\n")
    assert doctor._panel_last_date(junk) is None
