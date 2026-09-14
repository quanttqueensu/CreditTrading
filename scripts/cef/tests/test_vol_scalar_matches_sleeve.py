"""The scalar reproduction must equal the sleeve's own, and must not look ahead.

WHY THESE TWO AND NOT A GOLDEN NUMBER
-------------------------------------
`vol_scalar_history.py` re-runs the sleeve's sizing block over history. That is
a copy, and a copy of live sizing code is a liability the day the original
changes. So the first test does not assert 1.58 -- it asks the REAL
`CEFDiscountSleeve` for its targets and compares against the reproduction. If
anyone edits `cef_discount.py:198`, this fails rather than the report quietly
drifting away from the book.

The second test guards the defect the reproduction is uniquely exposed to. The
sleeve always sees a panel truncated at `asof`; the script loads the panel once
and slices. Forget a slice and the trailing-vol window silently becomes the last
63 days OF THE FILE -- a clean, plausible, entirely wrong number, computed from
the future. The test builds a panel whose tail is deliberately violent and
checks that an early decision date does not feel it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.cef import vol_scalar_history as M  # noqa: E402

VOLSCAL = re.compile(r"volscal=([0-9.]+)")


def _panel_or_skip(sleeve):
    panel = sleeve._panel(pd.Timestamp.today())
    if panel is None:
        pytest.skip("no CEF panel on this machine")
    return panel


def test_reproduction_equals_the_live_sleeve():
    """The sleeve's own printed volscal, against the script's, on the same date."""
    sleeve = M.load_sleeve()
    panel = _panel_or_skip(sleeve)
    asof = panel[0].index[-1]

    # The band refuses to size without a sleeve NAV -- correctly, since sizing a
    # band off a guessed denominator moves real money on an invented number. So
    # the stub supplies one and NO holdings, which puts every name outside the
    # band and makes the sleeve print the scalar we are here to compare.
    class _MS:
        extras = {"sleeve_nav": sleeve.capital_usd}
        holdings: dict = {}

    printed = {float(m.group(1))
               for t in sleeve.target_positions(asof, _MS())
               if (m := VOLSCAL.search(t.reason or ""))}
    if not printed:
        pytest.skip("every name sat inside the band; no volscal was printed")
    assert len(printed) == 1, f"the sleeve printed more than one scalar: {printed}"

    df = M.scalar_series(sleeve, panel)
    assert round(float(df.loc[asof, "scal"]), 2) == printed.pop()


def test_the_trailing_window_cannot_see_the_future():
    """A violent tail must not change a decision taken long before it.

    Built as a real regression: remove the `.loc[:d]` from `ret` in
    `scalar_series` and this fails, because the last 63 rows of the FILE -- all
    of them after the decision -- become the volatility estimate.
    """
    sleeve = M.load_sleeve()
    panel = _panel_or_skip(sleeve)
    px, nav, vol = panel
    base_df = M.scalar_series(sleeve, panel)
    # A date the sleeve actually decides on -- NOT the midpoint of the price
    # index, which lands in the pre-2013 stretch where fewer than `min_names`
    # clear the ADV filter (CLAUDE.md landmine 6) and no scalar is produced.
    early = base_df.index[len(base_df) // 2]
    assert early < px.index[-63], "pick a date before the shocked tail"

    base = base_df.loc[early, "scal"]

    rng = np.random.default_rng(0)
    px2 = px.copy()
    tail = px2.index[-63:]
    shock = pd.DataFrame(rng.normal(1.0, 0.15, (len(tail), px2.shape[1])),
                         index=tail, columns=px2.columns)
    px2.loc[tail] = px2.loc[tail] * shock
    nav2 = nav.copy()
    nav2.loc[tail] = nav2.loc[tail] * shock

    after = M.scalar_series(sleeve, (px2, nav2, vol)).loc[early, "scal"]
    assert base == pytest.approx(after), (
        f"a shock 63 days AFTER {early.date()} moved its scalar "
        f"{base:.4f} -> {after:.4f}: the trailing window is reading the future")
