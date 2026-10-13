"""C4 feasibility: the declared pool, the two masks and the eligibility count.

Synthetic frames only. These test the CODE that turns the pre-registration's
declarations into counts; they make no claim about any fund (CLAUDE.md:
synthetic data tests a method, never the world). No panel is read and no
network is touched.
"""
import math

import numpy as np
import pandas as pd
import pytest

from scripts.cef import c4_feasibility as c4


def _names(rows):
    cols = ["ticker", "family", "nav_rows", "disc_All_pre2023_class", "disc_1Y_class",
            "split_basis_mismatch_before"]
    return pd.DataFrame(rows, columns=cols)


def test_pool_leaves_out_global_navless_and_flagged_with_reasons():
    names = _names([
        ("AAA", "equity_sector", 500, "clean", "clean", None),
        ("BBB", "equity_global", 500, "clean", "clean", None),           # family excluded
        ("CCC", "preferred", 0, None, None, None),                       # no NAV
        ("DDD", "multi_asset", 500, "SYSTEMATIC", "clean", None),        # flagged discount
        ("EEE", "equity_domestic", 500, "unchecked", "clean", "2025-10-23"),  # split basis
        ("FFF", "equity_covered_call", 500, "episodic", "clean", None),  # episodic stays in
    ])
    pool, out = c4.declare_pool(names)
    assert pool == ["AAA", "FFF"]
    why = out.set_index("ticker")["reason"]
    assert "asynchronous" in why["BBB"]
    assert "no usable daily NAV" in why["CCC"]
    assert "flagged" in why["DDD"] and "flagged" in why["EEE"]


def test_pool_refuses_a_family_it_does_not_know():
    with pytest.raises(ValueError, match="neither the pool nor the exclusions"):
        c4.declare_pool(_names([("ZZZ", "commodity", 500, "clean", "clean", None)]))


def test_repeat_mask_is_per_fund_and_exact():
    nav = pd.DataFrame({
        "ticker": ["A", "A", "A", "B", "B"],
        "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-02", "2020-01-03"]),
        "nav": [10.00, 10.00, 10.01, 10.01, 10.02],   # B's first row equals A's last: not a repeat
    })
    assert c4.repeat_mask(nav).tolist() == [False, True, False, False, False]


def _panel(n=40, repeat_on=(), zero_vol_on=(), vol=1_000_000.0):
    dates = pd.bdate_range("2021-01-04", periods=n)
    px = pd.DataFrame({"ticker": "A", "date": dates, "close": 10.0, "volume": vol})
    px.loc[list(zero_vol_on), "volume"] = 0.0
    nav = pd.DataFrame({"ticker": "A", "date": dates, "nav": 10.0 + 0.01 * np.arange(n)})
    nav["repeat"] = False
    nav.loc[list(repeat_on), "repeat"] = True
    return px, nav, dates


def test_masks_remove_the_discount_not_the_price_and_shrink_the_history():
    px, nav, dates = _panel(repeat_on=(30,), zero_vol_on=(31,))
    E = c4.eligibility(px, nav, floor=1.0, z_window=10, min_periods=5)
    el = E["elig"]["A"]
    assert not el.loc[dates[30]] and not el.loc[dates[31]]          # masked days are not eligible
    assert el.loc[dates[29]] and el.loc[dates[32]]
    assert E["paired"]["A"].loc[dates[30]]                          # the price stays in the panel
    # ADV is the unmasked joined panel's: day 31's zero volume enters later ADVs
    E0 = c4.eligibility(px, nav, floor=1.0, z_window=10, min_periods=5,
                        mask_repeat=False, mask_zero_volume=False)
    assert E0["elig"]["A"].loc[dates[30]] and E0["elig"]["A"].loc[dates[31]]


def test_history_count_and_adv_are_shifted_one_session():
    """No lookahead (H7): the first eligible day needs min_periods observations
    BEFORE it, and ADV through the day before (the sleeve's shift(1))."""
    px, nav, dates = _panel(n=30)
    E = c4.eligibility(px, nav, floor=1.0, z_window=10, min_periods=5)
    first = E["elig"]["A"].idxmax()
    assert first == dates[21]       # ADV needs 21 sessions, shifted one -> index 21
    E2 = c4.eligibility(px, nav, floor=1.0, z_window=50, min_periods=25)
    assert E2["elig"]["A"].idxmax() == dates[25]   # 25 prior observations -> index 25


def test_adv_floor_binds():
    px, nav, _ = _panel(vol=10.0)                  # $100/day
    E = c4.eligibility(px, nav, floor=1_000.0, z_window=10, min_periods=5)
    assert not E["elig"].values.any()


def test_corr_kill_probability_is_one_half_at_the_threshold_and_monotone():
    assert c4.corr_kill_prob(0.5, 114) == pytest.approx(0.5, abs=1e-12)
    ps = [c4.corr_kill_prob(r, 114) for r in (0.2, 0.3, 0.4, 0.6)]
    assert ps == sorted(ps)
    assert c4.corr_kill_prob(0.3, 1000) < c4.corr_kill_prob(0.3, 50)


def test_era_rows_count_active_sessions_against_min_names():
    idx = pd.bdate_range("2010-01-04", periods=10)
    elig = pd.DataFrame(False, index=idx, columns=list("ABCDEFG"))
    elig.iloc[:5, :6] = True                       # 6 eligible on the first five sessions
    r = [x for x in c4.era_rows(elig, 6, "t") if x["era"] == "2010-14"][0]
    assert (r["sessions"], r["active_sessions"]) == (10, 5)
    assert math.isclose(r["active_share"], 0.5)
