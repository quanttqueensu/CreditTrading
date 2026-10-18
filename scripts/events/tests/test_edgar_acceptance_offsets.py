"""The timestamp arithmetic behind the EDGAR acceptance-time check.

WHY THESE TESTS
---------------
The finding is "the JSON is late by exactly the date's UTC offset", so the
conversion must get daylight saving right, or a 5-hour winter offset would be
misread as a 4-hour bug plus an hour of noise (or the reverse):

  * `header_utc` reads EDGAR's 14-digit Eastern stamp with America/New_York's
    rules: 17:31:47 on 2026-09-17 (EDT) is 21:31:47Z; 16:00 on 2026-01-15 (EST)
    is 21:00Z. Checked to fail against a fixed UTC-4 conversion.
  * `offset_hours` is 0 for the HYT Form 3 that REFERENCES §12j used, and +4 for
    the PDI Form 4 of 2026-10-08 (header 16:05:06 ET, JSON 00:05:06Z next day),
    both read on 2026-10-15.
  * Malformed stamps and a JSON value without "Z" raise; they are never coerced.

No network: only the pure functions are imported and called.
"""
import datetime as dt

import pytest

from scripts.events import edgar_acceptance_offsets as m


def test_header_utc_handles_edt_and_est():
    assert m.header_utc("20260917173147") == dt.datetime(2026, 9, 17, 21, 31, 47, tzinfo=dt.timezone.utc)
    assert m.header_utc("20260115160000") == dt.datetime(2026, 1, 15, 21, 0, 0, tzinfo=dt.timezone.utc)


def test_offsets_on_the_two_read_cases():
    assert m.offset_hours("2026-09-17T21:31:47.000Z", "20260917173147") == 0.0
    assert m.offset_hours("2026-10-09T00:05:06.000Z", "20261008160506") == 4.0


def test_malformed_inputs_raise():
    with pytest.raises(ValueError):
        m.header_utc("2026-09-17 17:31:47")
    with pytest.raises(ValueError):
        m.json_utc("2026-09-17T21:31:47")
