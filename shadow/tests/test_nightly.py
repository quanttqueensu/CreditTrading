"""The nightly run: the as-of date is the latest CLOSED session, a failed refresh is loud,
marks are fetched only where missing, and a second run changes nothing. Fakes only."""
import datetime as dt
import json

import pandas as pd

from shadow import book as book_mod
from shadow import engine, nightly
from shadow.tests.test_engine import _days, _px, _state

NY = engine.NY


def _at(d, h, m=0):
    return dt.datetime.combine(d, dt.time(h, m), tzinfo=NY)


def test_asof_is_the_latest_closed_session():
    days = _days(5)                                   # Mon..Fri
    assert nightly.asof_session(days, _at(days[2], 18, 45)) == days[2]      # evening: today
    assert nightly.asof_session(days, _at(days[2], 7, 20)) == days[1]       # morning backstop: yesterday
    assert nightly.asof_session(days, _at(days[2], 16, 29)) == days[1]      # one minute before SETTLE
    sat = days[4] + dt.timedelta(days=1)
    assert nightly.asof_session(days, _at(sat, 9)) == days[4]
    assert nightly.asof_session(days, _at(days[0], 9)) is None


class FakeSrc:
    def __init__(self, px, days):
        self.px, self.days, self.calls = px, days, []

    def sessions(self, first, last):
        return [d for d in self.days if first <= d <= last]

    def prints(self, syms, day):
        self.calls.append(day)
        rows = self.px[(self.px["date"].dt.date == day) & self.px["symbol"].isin(syms)]
        return dict(zip(rows["symbol"], rows["close"]))

    def distributions(self, syms, first, last):
        return []


def _check(px):
    return lambda syms, a, b: px[["date", "symbol", "close"]]


def _book(tmp_path, days, refresh):
    f = tmp_path / "books" / "t1.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps({
        "slug": "t1", "card": "none", "signal": "shadow.tests._signals:last_return", "fill": "next_close",
        "panels": {"px": {"path": "px.parquet", "date_col": "date", "required_asof": True}},
        "refresh": refresh, "notional_usd": 1_000_000, "started": days[1].isoformat(), "enabled": True}))
    return book_mod.load(f)


def test_nightly_decides_marks_and_is_safe_to_repeat(tmp_path):
    days = _days(8)
    px = _px(days, seed=11)
    st = _state(tmp_path, px)
    b = _book(tmp_path, days, [])
    src = FakeSrc(px, days)
    for d in days[1:]:
        assert nightly.run(st, [b], src, check=_check(px), now=_at(d, 18, 45)) == 0
    sc = pd.read_csv(st / "t1" / "scores.csv")
    assert (sc["status"] == "SCORED").sum() == len(days) - 3      # first fill, then one row a session
    assert "SIMULATED" in (st / "SCOREBOARD.md").read_text()
    n_calls, marks_before = len(src.calls), (st / "marks.parquet").read_bytes()
    assert nightly.run(st, [b], src, check=_check(px), now=_at(days[-1], 20, 45)) == 0
    assert len(src.calls) == n_calls                              # nothing missing, nothing fetched
    assert (st / "marks.parquet").read_bytes() == marks_before
    assert len(pd.read_csv(st / "t1" / "scores.csv")) == len(sc)


def test_a_failed_refresh_is_reported_and_the_run_exits_nonzero(tmp_path, capsys):
    days = _days(5)
    px = _px(days)
    st = _state(tmp_path, px)
    b = _book(tmp_path, days, [["python3", "-c", "import sys; sys.exit(7)"]])
    rc = nightly.run(st, [b], FakeSrc(px, days), check=_check(px), now=_at(days[3], 18, 45))
    assert rc == 3 and "REFRESH FAILED (7)" in capsys.readouterr().out


def test_a_held_name_with_no_print_is_a_logged_gap_and_an_unmeasured_session(tmp_path):
    days = _days(8)
    px = _px(days, seed=13)
    st = _state(tmp_path, px)
    b = _book(tmp_path, days, [])
    holes = px[~((px["symbol"] == "DDD") & (px["date"].dt.date == days[5]))]
    src = FakeSrc(holes, days)
    rcs = [nightly.run(st, [b], src, check=_check(px), now=_at(d, 18, 45)) for d in days[1:]]
    assert 3 in rcs
    assert "DDD" in (st / "marks_gaps.csv").read_text()
    sc = pd.read_csv(st / "t1" / "scores.csv").set_index("date")
    assert sc.at[str(days[5]), "status"] == "UNMEASURED"
