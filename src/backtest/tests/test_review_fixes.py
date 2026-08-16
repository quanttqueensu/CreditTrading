"""Regression tests for the four defects the Phase 2 adversarial review found.

Each was a silent-wrong-answer bug: the backtest returned a number rather than
an error, so nothing downstream could tell the result was meaningless.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest import engine, walkforward as wf
from src.backtest.tests.conftest import make_panel, zero_rf


# --- M3: unsorted / duplicated returns index -------------------------------

def test_unsorted_returns_index_is_rejected(costs_simple):
    """A scrambled panel used to misalign T+1 silently, with no warning."""
    rets = make_panel({"HYG": [0.01] * 6, "BIL": [0.0] * 6})
    scrambled = rets.iloc[[0, 2, 1, 3, 5, 4]]
    weights = pd.DataFrame({"HYG": [1.0] * 6}, index=rets.index)

    with pytest.raises(ValueError, match="not sorted ascending"):
        engine.run_backtest(weights, scrambled, costs_simple,
                            rf=zero_rf(rets.index), verbose=False)


def test_duplicate_returns_dates_are_rejected(costs_simple):
    rets = make_panel({"HYG": [0.01] * 5, "BIL": [0.0] * 5})
    dupe = pd.concat([rets, rets.iloc[[2]]]).sort_index()
    weights = pd.DataFrame({"HYG": [1.0] * 5}, index=rets.index)

    with pytest.raises(ValueError, match="duplicate dates"):
        engine.run_backtest(weights, dupe, costs_simple,
                            rf=zero_rf(rets.index), verbose=False)


# --- M1: unbounded forward-fill of a truncated weight frame -----------------

def test_stale_weights_past_the_limit_are_rejected(costs_simple):
    """10 weight rows against a 100-day panel must not hold exposure silently."""
    n = 100
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0] * 10}, index=rets.index[:10])

    with pytest.raises(ValueError, match="stale weight"):
        engine.run_backtest(weights, rets, costs_simple,
                            rf=zero_rf(rets.index), verbose=False)


def test_a_normal_monthly_gap_still_runs(costs_simple):
    """The guard must not fire on a monthly strategy's final partial month."""
    n = 100
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0, 1.0]},
                           index=[rets.index[0], rets.index[n - 20]])

    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), verbose=False)
    assert res.n_days == n


def test_the_limit_can_be_disabled_deliberately(costs_simple):
    n = 100
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0]}, index=rets.index[:1])

    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), max_ffill_days=None,
                              verbose=False)
    assert res.positions["HYG"].iloc[-1] == pytest.approx(1.0)


# --- M2: leverage financed at the risk-free rate ---------------------------

def test_borrowed_cash_pays_the_financing_spread(costs_simple):
    """Levering to 1.5x must cost rf + spread on the borrowed half, not rf."""
    n = 10
    rets = make_panel({"HYG": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.5] * n}, index=rets.index)

    costs_free = dict(engine.load_costs(costs_simple), financing_spread_bp=0.0)
    costs_paid = dict(engine.load_costs(costs_simple), financing_spread_bp=150.0)

    free = engine.run_backtest(weights, rets, costs_free, rf=zero_rf(rets.index),
                               name="unfinanced", verbose=False)
    paid = engine.run_backtest(weights, rets, costs_paid, rf=zero_rf(rets.index),
                               name="financed", verbose=False)

    # Borrowing 0.5 of book at 150bp for one day, after the T+1 warm-up row.
    expected = 0.5 * (150.0 / 1e4) / engine.TRADING_DAYS
    diff = (free.gross - paid.gross).iloc[1:]
    assert diff.mean() == pytest.approx(expected, rel=1e-9)
    assert paid.gross.iloc[1:].lt(free.gross.iloc[1:]).all()


def test_unlevered_runs_are_untouched_by_the_spread(costs_simple):
    """Long/cash strategies must be numerically identical either way."""
    n = 10
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0, 0.0] * (n // 2)}, index=rets.index)

    base = engine.load_costs(costs_simple)
    free = engine.run_backtest(weights, rets, dict(base, financing_spread_bp=0.0),
                               rf=zero_rf(rets.index), verbose=False)
    paid = engine.run_backtest(weights, rets, dict(base, financing_spread_bp=150.0),
                               rf=zero_rf(rets.index), verbose=False)

    pd.testing.assert_series_equal(free.net, paid.net)


# --- M4: walk-forward swallowing NaN weights from apply() ------------------

def test_walkforward_rejects_nan_weights_from_apply(costs_simple):
    """A rolling warm-up NaN must surface, not become a flat position."""
    n = 300
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})

    def fit(_train_panel, _window):
        return {"level": 1.0}

    def apply(params, panel, window):
        w = pd.DataFrame({"HYG": params["level"]}, index=panel.index)
        # NaN on the window's first RETAINED row (rows before fit_end are
        # discarded by the runner, so a NaN there would never reach the stitch).
        w.loc[window.fit_end] = np.nan
        return w

    with pytest.raises(ValueError, match="apply\\(\\) returned NaN"):
        wf.run_walkforward(rets, fit, apply, costs_simple,
                           min_train=100, step=50,
                           rf=zero_rf(rets.index), verbose=False)


# --- liquidity: book size must actually bind --------------------------------

def test_impact_makes_book_size_matter(costs_simple):
    """Without impact, $25k and $100k are byte-identical — infinite liquidity."""
    n = 40
    # Impact scales with volatility under the square-root law, so a constant
    # return series would correctly price impact at exactly zero.
    wobble = [0.004, -0.003] * (n // 2)
    rets = make_panel({"HYG": wobble, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0, 0.0] * (n // 2)}, index=rets.index)
    dv = pd.DataFrame({"HYG": [500_000.0] * n, "BIL": [1e12] * n},
                      index=rets.index)
    costs = dict(engine.load_costs(costs_simple),
                 impact_coefficient=1.0, max_participation_pct=100.0)

    small = engine.run_backtest(weights, rets, costs, book_usd=25_000,
                                dollar_volume=dv, rf=zero_rf(rets.index),
                                verbose=False)
    large = engine.run_backtest(weights, rets, costs, book_usd=100_000,
                                dollar_volume=dv, rf=zero_rf(rets.index),
                                verbose=False)

    assert large.costs.sum() > small.costs.sum()
    # Square-root law: 4x the book is 2x the impact per unit traded.
    ratio = large.meta["impact_cost"].sum() / small.meta["impact_cost"].sum()
    assert ratio == pytest.approx(2.0, rel=1e-6)


def test_thin_volume_is_flagged_as_infeasible(costs_simple):
    """Trading most of a day's volume must be reported, not silently priced."""
    n = 20
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0, 0.0] * (n // 2)}, index=rets.index)
    dv = pd.DataFrame({"HYG": [50_000.0] * n, "BIL": [1e12] * n},
                      index=rets.index)
    costs = dict(engine.load_costs(costs_simple),
                 impact_coefficient=1.0, max_participation_pct=10.0)

    res = engine.run_backtest(weights, rets, costs, book_usd=60_000,
                              dollar_volume=dv, rf=zero_rf(rets.index),
                              verbose=False)
    liq = res.meta["liquidity"]
    assert liq is not None
    assert liq["n_infeasible_trades"] > 0
    assert liq["worst_participation"] > 1.0        # more than a full day


def test_no_volume_panel_means_no_impact(costs_simple):
    """Backward compatible: omitting volume leaves results untouched."""
    n = 20
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0, 0.0] * (n // 2)}, index=rets.index)
    costs = dict(engine.load_costs(costs_simple), impact_coefficient=1.0)

    res = engine.run_backtest(weights, rets, costs, book_usd=60_000,
                              rf=zero_rf(rets.index), verbose=False)
    assert float(res.meta["impact_cost"].sum()) == 0.0
    assert res.meta["liquidity"] is None
