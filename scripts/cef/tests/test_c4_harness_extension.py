"""The harness arguments trial C4 added to `band_frontier.py` (DG-C4-2, DG-C4-5).

WHY THIS FILE EXISTS
--------------------
C4 (`results/cef/PREREG_C4_FAMILIES_2026-10-13.md`) runs the LIVE signal on
another panel. Rather than a second copy of the z-score, the canonical harness
grew four optional arguments, each defaulting to the old behaviour:

    build_panel / build_targets(source=...)   read another panel in the live schema
    build_panel / build_targets(mask=...)     a fund-day with no discount
    build_targets(min_adv=...)                the WIDE set (floor 0), C4's DG-C4-5
    total_returns(R, actions=..., prices=...) a yfinance actions file

Each could rot in a way nothing else would notice:

  * a mask that also blanked the PRICE would silently drop a masked day's
    return from the P&L and its volume from ADV (PREREG_C4 §4.3: the price
    stays in the panel);
  * a mask that blanked z but left the discount in the rolling window would
    still count the masked day toward the 120-observation history;
  * a mask aimed at a ticker the panel does not hold would mask nothing;
  * `min_adv` could stop meaning "this call only" and leak into the module;
  * yfinance codes "no split" as 0.0, and a factor of 0 multiplied into a
    return is a -100% day.

The byte-for-byte no-op of the defaults on the live panels is proved by hash
(`build_panel`'s docstring), not here: the live panel changes daily, so a
pinned hash would fail every morning. The tests use synthetic panels; they are
claims about the code, never about the market.

Every test was run against the code before these arguments existed and failed
(TypeError on the new keyword) before it was kept.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.cef import band_frontier as BF  # noqa: E402


def _panel(tmp_path, n_names=7, n_days=420, volume=1_000_000, seed=3):
    """Write a synthetic price and NAV panel in the live schema; return paths and tickers."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2005-01-03", periods=n_days)
    tick = [f"T{i}" for i in range(n_names)]
    rows_p, rows_n = [], []
    for t in tick:
        nav = 20 * np.exp(np.cumsum(rng.normal(0, 0.006, n_days)))
        disc = np.cumsum(rng.normal(0, 0.004, n_days)) * 0.3 - 0.05
        px = nav * (1 + disc)
        for d, p, v in zip(idx, px, nav):
            rows_p.append(dict(date=d, open=p, high=p, low=p, close=p, volume=volume, ticker=t, grp="x"))
            rows_n.append(dict(date=d, nav=v, ticker=t))
    pp, npth = tmp_path / "prices.parquet", tmp_path / "nav.parquet"
    pd.DataFrame(rows_p).to_parquet(pp, index=False)
    pd.DataFrame(rows_n).to_parquet(npth, index=False)
    return (pp, npth), tick, idx


def test_source_reads_the_given_panel_not_the_live_one(tmp_path):
    src, tick, idx = _panel(tmp_path)
    p = BF.build_panel(universe=tick, source=src)
    raw = pd.read_parquet(src[0]).pivot_table(index="date", columns="ticker", values="close")
    assert list(p["px"].columns) == tick
    pd.testing.assert_frame_equal(p["px"], raw[tick], check_names=False, check_freq=False)


def test_mask_removes_the_discount_and_its_history_but_not_the_price(tmp_path):
    src, tick, idx = _panel(tmp_path)
    base = BF.build_panel(universe=tick, source=src)
    m = pd.DataFrame(False, index=base["disc"].index, columns=tick)
    day = base["disc"].index[300]
    m.loc[day, "T0"] = True
    # T1: mask all but 100 of its first 260 sessions -> fewer than MIN_PERIODS (120) in any
    # window ending at session 260, so mu/sd must be NaN there although 260 prices exist
    m.iloc[:160, 1] = True
    p = BF.build_panel(universe=tick, source=src, mask=m)
    assert np.isnan(p["disc"].loc[day, "T0"]) and np.isnan(p["z"].loc[day, "T0"])
    assert not np.isnan(base["z"].loc[day, "T0"])
    for k in ("px", "nav", "ret", "adv", "vol"):           # price, return and ADV untouched
        pd.testing.assert_frame_equal(p[k], base[k])
    assert BF.MIN_PERIODS == 120
    assert np.isnan(p["mu"].iloc[260, 1]) and not np.isnan(base["mu"].iloc[260, 1])
    # unmasked names are unchanged everywhere
    pd.testing.assert_series_equal(p["z"]["T3"], base["z"]["T3"])


def test_a_mask_aimed_at_a_ticker_the_panel_lacks_raises(tmp_path):
    src, tick, idx = _panel(tmp_path)
    m = pd.DataFrame(False, index=idx, columns=tick + ["NOT_THERE"])
    with pytest.raises(ValueError, match="does not hold"):
        BF.build_panel(universe=tick, source=src, mask=m)


def test_a_mask_with_a_nan_cell_raises_rather_than_masking(tmp_path):
    src, tick, idx = _panel(tmp_path)
    m = pd.DataFrame(False, index=idx, columns=tick).astype(object)
    m.iloc[5, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        BF.build_panel(universe=tick, source=src, mask=m)


def test_min_adv_zero_builds_the_wide_set_for_this_call_only(tmp_path):
    # $10 x 1,000 shares = ~$20k a day: far under the spec floor
    src, tick, idx = _panel(tmp_path, volume=1_000)
    assert BF.MIN_ADV > 1e5
    T_dep, _ = BF.build_targets(universe=tick, source=src)
    T_wide, _ = BF.build_targets(universe=tick, source=src, min_adv=0.0)
    assert (T_dep.abs().sum(axis=1) == 0).all()             # nothing clears the floor
    assert (T_wide.abs().sum(axis=1) > 0).any()             # WIDE trades
    assert BF.MIN_ADV > 1e5                                 # the module floor is untouched
    T_again, _ = BF.build_targets(universe=tick, source=src)
    pd.testing.assert_frame_equal(T_again, T_dep)


def test_total_returns_reads_a_yfinance_actions_file(tmp_path):
    idx = pd.bdate_range("2025-01-02", periods=6)
    px = pd.DataFrame({"A": [10.0, 10.0, 10.2, 10.1, 5.05, 5.0]}, index=idx)
    prices = pd.DataFrame([dict(date=d, open=v, high=v, low=v, close=v, volume=1, ticker="A", grp="x")
                           for d, v in px["A"].items()])
    pp = tmp_path / "p.parquet"
    prices.to_parquet(pp, index=False)
    acts = pd.DataFrame([
        dict(date=idx[2], ticker="A", dividends=0.10, stock_splits=0.0),   # a distribution
        dict(date=idx[4], ticker="A", dividends=0.0, stock_splits=2.0),    # 2-for-1
        dict(date=idx[5], ticker="A", dividends=0.0, stock_splits=0.0),    # yfinance's "nothing"
    ])
    ap = tmp_path / "a.parquet"
    acts.to_parquet(ap, index=False)
    R = px.pct_change(fill_method=None)
    tr = BF.total_returns(R, actions=ap, prices=pp)
    assert tr.loc[idx[2], "A"] == pytest.approx(10.2 / 10.0 - 1 + 0.10 / 10.0)
    assert tr.loc[idx[4], "A"] == pytest.approx((5.05 / 10.1) * 2.0 - 1)
    assert tr.loc[idx[5], "A"] == pytest.approx(5.0 / 5.05 - 1)       # 0.0 is not a factor
    with pytest.raises(ValueError, match="together"):
        BF.total_returns(R, actions=ap)


def test_a_negative_action_is_a_defect_not_a_convention(tmp_path):
    ap = tmp_path / "a.parquet"
    pd.DataFrame([dict(date=pd.Timestamp("2025-01-02"), ticker="A", dividends=-0.1,
                       stock_splits=0.0)]).to_parquet(ap, index=False)
    with pytest.raises(ValueError, match="negative"):
        BF.load_families_actions(ap)
