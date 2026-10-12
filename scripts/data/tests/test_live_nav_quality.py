"""The pure methods behind results/cef/LIVE_NAV_QUALITY_2026-10-12.md (scripts/data/live_nav_quality.py).

WHY THESE TESTS
---------------
The note's figures rest on four small functions, each of which could be
quietly wrong without raising: the row classifier (a stale copy must be named
as one, and a float32-stored 10.979999542 must still equal a quoted 10.98);
the implied-NAV inversion that says which NAV a live session used from the z it
printed; the tie-break regression that says which source is right on a stale
copy; and the write guard that keeps the cache out of the live `data/cef/`.

Synthetic frames only: these test the code, not the market. No network (the
root conftest blocks it). Each test marked "Broken variant checked" was run
against that variant on 2026-10-12 and failed, before it was kept.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.data import live_nav_quality as L


def _daily(values, start="2024-01-01", tk="AAA"):
    d = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({"ticker": tk, "date": d, "nav": np.asarray(values, dtype=float)})


def test_classify_names_a_stale_copy_and_its_lagged_subset():
    # Broken variant checked: dropping the `repeat` rung labels both rows OTHER / SHIFT_NEXT.
    a = _daily([10.00, 10.10, 10.10, 10.30, 10.30, 10.40])        # rows 2 and 4 repeat their previous row
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [10.00, 10.10, 10.20, 10.30, 10.35, 10.40]       # cc moved on both repeat days
    m = L.classify(a, "nav", b, "nav_cc").set_index("date")["category"]
    assert list(m.values) == ["AGREE", "AGREE", "STALE_COPY", "AGREE", "STALE_COPY", "AGREE"]
    lag = L.classify(a, "nav", b, "nav_cc").set_index("date")["lagged"]
    assert not lag.iloc[2] and not lag.iloc[4]                     # 10.20 / 10.35 never appear in a


def test_classify_lagged_when_cc_equals_the_next_yfinance_row():
    a = _daily([10.0, 10.1, 10.1, 10.2])
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [10.0, 10.1, 10.2, 10.2]                         # yfinance one day late on row 2
    m = L.classify(a, "nav", b, "nav_cc")
    assert m["category"].iloc[2] == "STALE_COPY" and bool(m["lagged"].iloc[2])


def test_classify_float32_noise_is_agreement_not_a_defect():
    # Broken variant checked: FLOAT_EPS = 0 makes the 0.0050000x row a disagreement.
    a = _daily([12.5600004196167, 15.955, 10.0])
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [12.56, 15.96, 10.0]
    assert (L.classify(a, "nav", b, "nav_cc")["category"] == "AGREE").all()


def test_classify_shift_prev_and_next_and_basis():
    a = _daily([10.0, 10.1, 10.2, 10.3, 10.4])
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = [10.0, 10.0, 10.3, 10.3, 10.4]                   # row1 = a.prev (SHIFT_PREV); row2 = a.next
    m = L.classify(a, "nav", b, "nav_cc")["category"].tolist()
    assert m[1] == "SHIFT_PREV" and m[2] == "SHIFT_NEXT"
    # one source on another share basis for a whole name-year: every row 3% apart
    a2 = _daily(np.linspace(10, 11, 30), tk="BBB")
    b2 = a2[["ticker", "date"]].copy()
    b2["nav_cc"] = a2["nav"] / 1.03
    assert (L.classify(a2, "nav", b2, "nav_cc")["category"] == "BASIS").all()


def test_implied_nav_brackets_the_true_nav_and_refuses_a_clipped_z():
    # Broken variant checked: inverting with disc = 100 (nav - px) / px misses the true NAV.
    px, nav, mu, sd = 10.71, 10.97, 4.57, 2.96
    disc = 100 * (px - nav) / nav
    z = round((disc - mu) / sd, 2)
    mid, lo, hi = L.implied_nav(px, z, mu, sd)
    assert lo <= nav <= hi and hi - lo < 0.01
    with pytest.raises(L.LiveNavQualityError):
        L.implied_nav(px, -4.0, mu, sd)


def test_tiebreak_slope_is_one_when_cc_holds_the_skipped_move():
    # Broken variant checked: measuring the catch from the NEXT row (not the next CHANGE)
    # gives slope 0 on two-day repeats.
    rng = np.random.default_rng(0)
    true = 10 + np.cumsum(rng.normal(0, 0.03, 400)).round(2)
    yf = true.copy()
    skip = np.arange(5, 395, 7)
    yf[skip] = yf[skip - 1]                                        # yfinance repeats for two days,
    yf[skip + 1] = yf[skip - 1]                                    # then catches up
    a = _daily(yf)
    b = a[["ticker", "date"]].copy()
    b["nav_cc"] = true
    m = L.classify(a, "nav", b, "nav_cc")
    tb = L.tiebreak(m, a, "nav", "nav_cc")
    # the variant still finds the move on the SECOND repeat day, so the slope alone separates
    # weakly (0.75 vs 1.14 on this seed); the sign agreement does not (0.41 vs 0.78)
    assert tb["n"] > 20 and abs(tb["slope"] - 1) < 0.2 and tb["sign_agree"] > 0.6


def test_cache_refuses_the_live_panel_directory(tmp_path, monkeypatch):
    # Broken variant checked: comparing unresolved paths lets a symlinked base through.
    live = tmp_path / "real" / "cef"
    live.mkdir(parents=True)
    (tmp_path / "data").symlink_to(tmp_path / "real")
    monkeypatch.setattr(L, "LIVE_DIR", tmp_path / "data" / "cef")
    monkeypatch.setattr(L, "CACHE", tmp_path / "real")
    with pytest.raises(L.LiveNavQualityError):
        L._cache("cef/x.json")
    monkeypatch.setattr(L, "CACHE", tmp_path / "elsewhere")
    assert L._cache("x.json").parent == tmp_path / "elsewhere"
