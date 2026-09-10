"""A panel write must never leave a reader a half-written file.

WHY THIS MATTERS HERE MORE THAN IN MOST REPOS
---------------------------------------------
`data/` in prod is a SYMLINK back into the dev tree, so a research script
writing a panel writes what the live sleeve prices from. And the panels are ON
the live path, not beside it: `cef_prices.parquet` and `cef_nav.parquet` are
what the sleeve marks and sizes against, and `cef_distributions.parquet`
supplies the cash distribution on every ex-date — `src/deploy/run_book.py`
records that dropping it "would understate the book's return by roughly its
entire expected alpha".

Every one of those fetchers used a bare `to_parquet`, which truncates the target
and then streams into it. The CEF session runs in the evening and polls for NAV
until 23:30, so the window in which a reader can catch a truncated file is about
seven hours of every trading day.

ATOMICITY IS NOT THE WHOLE FIX and the docstring says so: a rename still changes
what the sleeve prices from between two reads. Do not refresh a live-path panel
while a session is running. This removes the corruption mode only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from ops.common import atomic_write  # noqa: E402

PANEL = pd.DataFrame({"date": pd.to_datetime(["2026-09-09", "2026-09-10"]),
                      "ticker": ["NAD", "NAD"], "close": [11.15, 11.16]})


@pytest.mark.parametrize("name", ["p.parquet", "c.csv"])
def test_round_trips_and_leaves_no_temp(tmp_path, name):
    out = tmp_path / name
    atomic_write(PANEL, out)
    back = pd.read_parquet(out) if name.endswith("parquet") else pd.read_csv(
        out, parse_dates=["date"])
    pd.testing.assert_frame_equal(back, PANEL)
    assert not (tmp_path / f"{name}.tmp").exists()


def test_a_failed_write_leaves_the_PREVIOUS_file_intact(tmp_path):
    """The property that matters. A crash mid-write must not destroy the panel
    that was already there — that panel is what tonight's session prices from.
    """
    out = tmp_path / "cef_prices.parquet"
    atomic_write(PANEL, out)

    class _Explodes(pd.DataFrame):
        @property
        def _constructor(self):
            return _Explodes

        def to_parquet(self, *a, **k):
            raise OSError("disk full")

    with pytest.raises(OSError):
        atomic_write(_Explodes(PANEL), out)

    pd.testing.assert_frame_equal(pd.read_parquet(out), PANEL), "previous panel survived"


def test_the_rename_is_what_publishes_it(tmp_path):
    """Nothing partial is ever visible AT the target path: the temp file carries
    the write and `os.replace` publishes it in one step."""
    out = tmp_path / "p.parquet"
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        # at this instant the target must still be absent (first write)
        seen.append(Path(dst).exists())
        return real_replace(src, dst)

    os.replace = spy
    try:
        atomic_write(PANEL, out)
    finally:
        os.replace = real_replace
    assert seen == [False], "the target appeared before the rename"
    assert out.exists()


def test_every_live_path_fetcher_uses_it():
    """A bare to_parquet/to_csv in one of these is the defect coming back."""
    fetchers = [
        "scripts/cef/fetch_daily.py",          # cef_prices, cef_nav
        "scripts/cef/stage_cef.py",            # cef_prices, cef_nav, universe
        "scripts/cef/fetch_borrow_rates.py",   # cef_borrow
        "scripts/cef/fetch_borrow_history.py",  # cef_borrow_history
        "scripts/fetch_cef_distributions.py",  # cef_distributions  <- live path
    ]
    offenders = []
    for rel in fetchers:
        for i, line in enumerate((REPO / rel).read_text().splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or "atomic_write" in s or ".tmp" in s:
                continue
            if 'mode="a"' in s or "mode='a'" in s:
                continue          # append-only log, not a panel replace
            if ".to_parquet(" in s or ".to_csv(" in s:
                offenders.append(f"{rel}:{i}: {s}")
    assert not offenders, (
        "these write a live-path panel non-atomically:\n  " + "\n  ".join(offenders))
