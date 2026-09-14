"""`beat()` records the decision a beat was about, alongside the day it was filed.

WHY THIS FILE EXISTS
--------------------
`date` is the day the beat was FILED. On 2026-09-10 a cef session started at
17:15, the Mac clamshell-slept, and the beat landed at 10:38:32 the next morning
with `date` 2026-09-11 and `armed` true -- for a decision about 2026-09-10. The
same-day guard compared that `date` against its own `today` and refused the
09-11 session. One power event, two sessions (ops/decision_age.py).

`session_date` is the other half, and the two must never collapse into one:
`date` answers "is this system alive right now", which preflight's staleness
check needs, and `session_date` answers "which decision did this describe",
which ops/session_plan.py's pair guard needs. Collapsing them in either
direction rebuilds the defect with the opposite sign.

These tests change nothing in ops/halt.py. They pin what it already does, which
until 2026-09-13 nothing did -- `beat()` is read by both guards, the dashboard
and preflight's staleness check, and had no test file at all.
"""
import json

import pytest

from ops import halt


@pytest.fixture()
def hb(tmp_path, monkeypatch):
    """A heartbeat in tmp_path. NEVER the real one.

    `ops/heartbeat.json` is live operational state that preflight and the
    stuck-session guard read; a test that wrote to it would hand the next
    session a fabricated beat. monkeypatch, not a copy, so a mistake here is a
    missing file rather than a corrupted one.
    """
    p = tmp_path / "heartbeat.json"
    monkeypatch.setattr(halt, "HEARTBEAT_PATH", p)
    return p


def read(p, job="cef"):
    return json.loads(p.read_text())[job]


def test_session_date_comes_from_pair_date(hb):
    halt.beat("cef", "ok", {"armed": True, "pair_date": "2026-09-10"})
    assert read(hb)["session_date"] == "2026-09-10"


def test_session_date_falls_back_to_asof(hb):
    """A writer that names the decision `asof` must still be readable.

    launch_job.py writes `pair_date`; nothing forces a future writer to. The
    fallback is what lets `session_plan._session_date` read one field instead
    of learning every writer's vocabulary.
    """
    halt.beat("cef", "ok", {"armed": True, "asof": "2026-09-10"})
    assert read(hb)["session_date"] == "2026-09-10"


def test_pair_date_wins_over_asof(hb):
    """Read order is pinned. They differ on exactly the day that matters: the
    morning session's `asof` IS its pair, but a writer that recorded both would
    most plausibly put the calendar date in one of them."""
    halt.beat("cef", "ok", {"armed": True, "pair_date": "2026-09-10",
                            "asof": "2026-09-11"})
    assert read(hb)["session_date"] == "2026-09-10"


def test_the_key_is_always_present_even_when_there_is_no_decision(hb):
    """Present-and-None is how a reader tells "beat() ran" from "old beat".

    Nothing in either guard may depend on that distinction -- an ARMED beat
    fails closed on both -- but the field must exist, or a future reader cannot
    tell a beat written today from one written before 2026-09-13, and the
    migration becomes unrecoverable rather than merely awkward.
    """
    halt.beat("phase0", "ok_not_armed", {"armed": False})
    rec = read(hb, "phase0")
    assert "session_date" in rec and rec["session_date"] is None


def test_session_date_is_recorded_alongside_date_never_instead_of_it(hb):
    """Both keys, always. Dropping `date` would blind preflight's staleness
    check, which is the only thing that notices a job that never fired."""
    halt.beat("cef", "ok", {"armed": True, "pair_date": "2026-09-10"})
    rec = read(hb)
    assert {"date", "session_date", "at", "status", "detail"} <= set(rec)


def test_the_filing_date_is_todays_wall_clock_not_the_decision(hb):
    """The 2026-09-10 shape, asserted rather than described."""
    from datetime import datetime
    halt.beat("cef", "ok", {"armed": True, "pair_date": "2026-09-10"})
    rec = read(hb)
    assert rec["date"] == f"{datetime.now():%Y-%m-%d}"
    assert rec["session_date"] == "2026-09-10"


def test_a_beat_with_no_detail_at_all_still_files(hb):
    """`detail` is optional and one LIVE caller omits it.

    launch_job.py:231 calls `halt_mod.beat(job, "skipped_non_trading_day")` with
    two arguments on every weekend and holiday. `dict(detail or {})` is what
    absorbs that; `dict(detail)` would raise TypeError and take out the beat on
    exactly the days nobody is watching -- and preflight's staleness check reads
    a missing beat as a job that never fired.

    Written after a mutation run on 2026-09-13 found that the test this replaced
    ("detail is copied, not aliased") failed under NO mutation of beat(): the
    function never writes into `d`, so aliasing is unobservable today. A test
    that cannot fail is not evidence.
    """
    halt.beat("cef", "skipped_non_trading_day")
    rec = read(hb)
    assert rec["detail"] == {} and rec["session_date"] is None
    assert rec["status"] == "skipped_non_trading_day"


def test_a_ten_character_date_survives_a_longer_timestamp(hb):
    """The guards compare ten characters. A timestamp here would never match."""
    halt.beat("cef", "ok", {"armed": True, "pair_date": "2026-09-10 16:00:00"})
    assert read(hb)["session_date"] == "2026-09-10"


def test_an_existing_beat_for_another_job_is_not_disturbed(hb):
    """One file, several books. The cef family's two fires share it, and so do
    phase0 and benchmarks; a writer that replaced the file rather than the row
    would silently delete the beat the other guard reads."""
    halt.beat("cef", "ok", {"armed": True, "pair_date": "2026-09-10"})
    halt.beat("phase0", "ok_not_armed", {"armed": False})
    both = json.loads(hb.read_text())
    assert set(both) == {"cef", "phase0"}
    assert both["cef"]["session_date"] == "2026-09-10"
