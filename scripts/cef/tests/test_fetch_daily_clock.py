"""fetch_daily.before_close reads ET, not the machine's zone (review 2026-09-29)."""
import datetime as dt
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "fetch_daily_under_test", Path(__file__).resolve().parents[1] / "fetch_daily.py")
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)


def test_utc_1630_is_1230_et_and_still_before_the_close():
    assert fd.before_close(dt.datetime(2026, 9, 29, 16, 30, tzinfo=dt.timezone.utc))


def test_edges_in_et():
    et = fd.ET
    assert fd.before_close(dt.datetime(2026, 9, 29, 16, 4, tzinfo=et))
    assert not fd.before_close(dt.datetime(2026, 9, 29, 16, 5, tzinfo=et))
    assert not fd.before_close(dt.datetime(2026, 9, 29, 21, 0, tzinfo=et))
