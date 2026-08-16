"""Engine tests: T+1 execution timing, cost arithmetic, vol-target math.

Every expected value below is computed BY HAND in the test (or from an
independent one-line numpy expression), never by calling the function under
test. That is the point of the calibration layer.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest import engine
from src.backtest.tests.conftest import make_panel, write_costs, zero_rf


# ---------------------------------------------------------------------------
# T+1 execution timing — hand-computed 2-day toy
# ---------------------------------------------------------------------------

def test_t_plus_1_two_day_toy_hand_computed(costs_simple):
    """The canonical timing case, worked by hand.

    Two trading days. HYG returns +10% on day 1 and +20% on day 2.
    A single weight row dated DAY 1 says "hold 1.0 HYG".

    Under T+1 that row is decided at day 1's close and earns its first
    return on day 2. So:
        day 1 gross = 0 (flat all day; cash at rf = 0)
        day 2 gross = 1.0 * 0.20 = 0.20
    If the engine were (wrongly) same-day, day 1 would show +0.10 and the
    two-day compound would be 1.10 * 1.20 = 1.32 instead of 1.20.
    """
    rets = make_panel({"HYG": [0.10, 0.20], "BIL": [0.0, 0.0]})
    day1, day2 = rets.index[0], rets.index[1]

    weights = pd.DataFrame({"HYG": [1.0]}, index=[day1])
    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), name="t+1 toy",
                              verbose=False)

    # applied exposure: flat on day 1, fully invested on day 2
    assert res.positions.loc[day1, "HYG"] == 0.0
    assert res.positions.loc[day2, "HYG"] == 1.0

    # gross returns, hand-computed
    assert res.gross.loc[day1] == pytest.approx(0.0)
    assert res.gross.loc[day2] == pytest.approx(0.20)

    # the same-day error would give 1.32; T+1 gives 1.20
    compound = float((1.0 + res.gross).prod())
    assert compound == pytest.approx(1.20)
    assert compound != pytest.approx(1.32)


def test_t_plus_1_never_earns_the_decision_day_return(costs_simple):
    """Generalization of the toy: for every date, the exposure earning that
    day's return is the target set on the PREVIOUS date."""
    rng = np.random.default_rng(0)
    n = 40
    rets = make_panel({"HYG": rng.normal(0, 0.01, n),
                       "BIL": np.zeros(n)})
    targets = pd.DataFrame({"HYG": rng.uniform(0, 1, n)}, index=rets.index)

    res = engine.run_backtest(targets, rets, costs_simple,
                              rf=zero_rf(rets.index), verbose=False)

    applied = res.positions["HYG"]
    assert applied.iloc[0] == 0.0                       # nothing set yesterday
    for i in range(1, n):
        assert applied.iloc[i] == pytest.approx(targets["HYG"].iloc[i - 1])


def test_extra_lag_shifts_one_more_day(costs_simple):
    """extra_lag=1 (used by guard.shift_test) delays exposure one further day."""
    rets = make_panel({"HYG": [0.10, 0.20, 0.30], "BIL": [0.0, 0.0, 0.0]})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])

    base = engine.run_backtest(weights, rets, costs_simple,
                               rf=zero_rf(rets.index), verbose=False)
    lagged = engine.run_backtest(weights, rets, costs_simple, extra_lag=1,
                                 rf=zero_rf(rets.index), verbose=False)

    assert list(base.positions["HYG"]) == [0.0, 1.0, 1.0]
    assert list(lagged.positions["HYG"]) == [0.0, 0.0, 1.0]
    assert lagged.gross.iloc[1] == pytest.approx(0.0)
    assert lagged.gross.iloc[2] == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Cost arithmetic — charged on TURNOVER, not on weight level
# ---------------------------------------------------------------------------

def test_cost_is_charged_on_turnover_not_on_holding(costs_simple):
    """Buy once, hold six days: you pay the spread ONCE.

    A holding-level (rather than turnover-level) cost bug would charge
    1bp every single day the position is open. With 1.0bp half-spread and a
    weight of 1.0 held for 5 return days, the correct total cost is 1.0e-4;
    the buggy version would be 5.0e-4.
    """
    n = 6
    rets = make_panel({"HYG": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])

    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), verbose=False)

    # turnover: 0 on the flat first day, 1.0 when the position is put on, 0 after
    assert res.turnover.iloc[0] == pytest.approx(0.0)
    assert res.turnover.iloc[1] == pytest.approx(1.0)
    assert res.turnover.iloc[2:].sum() == pytest.approx(0.0)

    # cost: one entry charge of 1.0bp on a weight of 1.0
    assert res.costs.iloc[1] == pytest.approx(1.0 * 1.0 / 1e4)
    assert res.costs.iloc[2:].sum() == pytest.approx(0.0)
    assert res.costs.sum() == pytest.approx(1.0e-4)
    assert res.costs.sum() != pytest.approx(5.0e-4)


def test_cost_scales_with_size_of_the_trade_not_the_position(costs_simple):
    """Rebalancing 1.0 -> 0.4 is a 0.6 trade and costs 0.6 x half-spread,
    even though the resulting position is 0.4."""
    n = 6
    rets = make_panel({"HYG": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0, 0.4]},
                           index=[rets.index[0], rets.index[3]])

    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), verbose=False)

    entry_day, rebal_day = rets.index[1], rets.index[4]
    assert res.turnover.loc[entry_day] == pytest.approx(1.0)
    assert res.turnover.loc[rebal_day] == pytest.approx(0.6)
    assert res.costs.loc[rebal_day] == pytest.approx(0.6 * 1.0 / 1e4)
    # not the position level (0.4) and not the gross weight (1.0)
    assert res.costs.loc[rebal_day] != pytest.approx(0.4 * 1.0 / 1e4)


def test_turnover_is_one_way_and_sums_across_tickers(costs_simple):
    """A switch out of HYG into JNK is 2.0 of one-way turnover (1.0 sold +
    1.0 bought) and costs both legs' half-spreads."""
    n = 6
    rets = make_panel({"HYG": [0.0] * n, "JNK": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0, 0.0], "JNK": [0.0, 1.0]},
                           index=[rets.index[0], rets.index[3]])

    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), verbose=False)

    switch_day = rets.index[4]
    assert res.turnover.loc[switch_day] == pytest.approx(2.0)
    # 1.0 x 1.0bp (HYG sell) + 1.0 x 1.0bp (JNK buy)
    assert res.costs.loc[switch_day] == pytest.approx(2.0 * 1.0 / 1e4)


def test_costs_come_from_the_config_file_not_hardcoded(tmp_path):
    """Same trade, three different config files, three proportional costs.
    Proves the number is read, not baked in."""
    n = 4
    rets = make_panel({"HYG": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])

    for bp in (1.0, 7.0, 25.0):
        cfg = write_costs(tmp_path, f"c_{bp}.yaml", half_spread_bp=bp)
        res = engine.run_backtest(weights, rets, cfg, rf=zero_rf(rets.index),
                                  verbose=False)
        assert res.costs.sum() == pytest.approx(1.0 * bp / 1e4)


def test_slippage_extra_bp_adds_to_the_half_spread(tmp_path):
    """slippage_extra_bp is a per-side stress knob added on top."""
    n = 4
    rets = make_panel({"HYG": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])

    cfg = write_costs(tmp_path, "slip.yaml", half_spread_bp=1.0,
                      slippage_extra_bp=2.0)
    res = engine.run_backtest(weights, rets, cfg, rf=zero_rf(rets.index),
                              verbose=False)
    assert res.costs.sum() == pytest.approx(1.0 * (1.0 + 2.0) / 1e4)


def test_commission_is_per_ticker_traded_and_scales_with_book(tmp_path):
    """Commission is a dollar amount per ticker traded, divided by book size —
    so a smaller book pays a bigger return drag for the same trade."""
    n = 4
    rets = make_panel({"HYG": [0.0] * n, "JNK": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [0.5], "JNK": [0.5]}, index=[rets.index[0]])

    cfg = write_costs(tmp_path, "comm.yaml", half_spread_bp=0.0,
                      commission_usd_per_trade=5.0, book_usd_default=10000)

    res = engine.run_backtest(weights, rets, cfg, rf=zero_rf(rets.index),
                              verbose=False)
    # two tickers traded x $5 / $10,000 book
    assert res.costs.sum() == pytest.approx(2 * 5.0 / 10000)

    # same trade on a $50,000 book is 5x cheaper in return terms
    res_big = engine.run_backtest(weights, rets, cfg, book_usd=50000,
                                  rf=zero_rf(rets.index), verbose=False)
    assert res_big.costs.sum() == pytest.approx(2 * 5.0 / 50000)


def test_net_equals_gross_minus_costs(costs_simple):
    rng = np.random.default_rng(7)
    n = 30
    rets = make_panel({"HYG": rng.normal(0, 0.01, n), "BIL": np.zeros(n)})
    weights = pd.DataFrame({"HYG": rng.choice([0.0, 1.0], n)}, index=rets.index)

    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), verbose=False)
    pd.testing.assert_series_equal(res.net, res.gross - res.costs,
                                   check_names=False)


# ---------------------------------------------------------------------------
# Cash / risk-free handling
# ---------------------------------------------------------------------------

def test_residual_weight_earns_the_risk_free_rate(costs_simple):
    """Half invested, half in cash: the cash half earns rf."""
    n = 3
    rets = make_panel({"HYG": [0.0, 0.10, 0.10], "BIL": [0.001] * n})
    rf = pd.Series(0.001, index=rets.index)
    weights = pd.DataFrame({"HYG": [0.5]}, index=[rets.index[0]])

    res = engine.run_backtest(weights, rets, costs_simple, rf=rf, verbose=False)

    # day 2: 0.5 * 0.10 (HYG) + 0.5 * 0.001 (cash) = 0.0505
    assert res.gross.iloc[1] == pytest.approx(0.5 * 0.10 + 0.5 * 0.001)
    # day 1 is fully in cash
    assert res.gross.iloc[0] == pytest.approx(0.001)


def test_bil_is_the_default_risk_free_proxy(costs_simple, capsys):
    """With no rf passed and BIL in the panel, BIL ret_total is used and the
    substitution is announced (data/README.md documents BIL as the proxy)."""
    n = 3
    rets = make_panel({"HYG": [0.0] * n, "BIL": [0.002] * n})
    weights = pd.DataFrame({"HYG": [0.0]}, index=[rets.index[0]])

    res = engine.run_backtest(weights, rets, costs_simple, verbose=True)
    out = capsys.readouterr().out
    assert "BIL" in out
    assert res.gross.iloc[0] == pytest.approx(0.002)   # 100% cash at BIL


def test_run_prints_sample_dates_and_n(costs_simple, capsys):
    """Standing rule: every run prints sample start/end and N."""
    n = 5
    rets = make_panel({"HYG": [0.0] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])

    engine.run_backtest(weights, rets, costs_simple, rf=zero_rf(rets.index),
                        name="printer", verbose=True)
    out = capsys.readouterr().out
    assert str(rets.index[0].date()) in out
    assert str(rets.index[-1].date()) in out
    assert f"N={n}" in out


# ---------------------------------------------------------------------------
# Vol-target math
# ---------------------------------------------------------------------------

def test_realized_vol_uses_only_the_trailing_window(costs_simple):
    """realized_vol at t = sample std of the last `window` returns through t,
    annualized by sqrt(252). No future data, no centering trickery."""
    vals = [0.01, -0.01, 0.02, 0.00, 0.015, -0.005]
    s = pd.Series(vals, index=pd.bdate_range("2020-01-02", periods=len(vals)))

    rv = engine.realized_vol(s, window=3)

    assert rv.iloc[:2].isna().all()          # warm-up
    for i in range(2, len(vals)):
        expected = np.std(vals[i - 2:i + 1], ddof=1) * np.sqrt(252)
        assert rv.iloc[i] == pytest.approx(expected)


def test_vol_target_scale_value_and_cap():
    """scale_t = min(cap, target_vol / realized_vol_t)."""
    vals = [0.01, -0.01, 0.02, 0.00, 0.015]
    s = pd.Series(vals, index=pd.bdate_range("2020-01-02", periods=len(vals)))

    scale = engine.vol_target_scale(s, target_vol=0.06, window=3, cap=1.5)

    # uncapped cell, computed independently
    vol2 = np.std(vals[0:3], ddof=1) * np.sqrt(252)
    assert scale.iloc[2] == pytest.approx(0.06 / vol2)
    assert scale.iloc[2] < 1.5                     # this cell is not capped
    assert scale.iloc[:2].isna().all()             # warm-up


def test_vol_target_scale_binds_at_the_cap():
    """Very calm returns imply a huge scale; the cap must bind."""
    vals = [0.000, 0.001, 0.002]                   # daily std = 0.001
    s = pd.Series(vals, index=pd.bdate_range("2020-01-02", periods=3))

    scale = engine.vol_target_scale(s, target_vol=0.06, window=3, cap=1.5)

    uncapped = 0.06 / (0.001 * np.sqrt(252))       # ~3.78
    assert uncapped > 1.5
    assert scale.iloc[2] == pytest.approx(1.5)


def test_vol_target_scale_is_inversely_proportional_to_vol():
    """Doubling realized vol halves the target weight."""
    calm = pd.Series([0.000, 0.001, 0.002],
                     index=pd.bdate_range("2020-01-02", periods=3))
    wild = calm * 2.0

    s_calm = engine.vol_target_scale(calm, target_vol=0.06, window=3, cap=100)
    s_wild = engine.vol_target_scale(wild, target_vol=0.06, window=3, cap=100)

    assert s_wild.iloc[2] == pytest.approx(s_calm.iloc[2] / 2.0)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_rejects_nan_weights(costs_simple):
    rets = make_panel({"HYG": [0.0] * 3, "BIL": [0.0] * 3})
    weights = pd.DataFrame({"HYG": [np.nan]}, index=[rets.index[0]])
    with pytest.raises(ValueError, match="NaN"):
        engine.run_backtest(weights, rets, costs_simple,
                            rf=zero_rf(rets.index), verbose=False)


def test_rejects_weights_outside_bounds(costs_simple):
    rets = make_panel({"HYG": [0.0] * 3, "BIL": [0.0] * 3})
    weights = pd.DataFrame({"HYG": [2.5]}, index=[rets.index[0]])
    with pytest.raises(ValueError, match="outside"):
        engine.run_backtest(weights, rets, costs_simple,
                            rf=zero_rf(rets.index), verbose=False)


def test_rejects_exposure_to_a_not_yet_trading_ticker(costs_simple):
    """A nonzero weight on a NaN return (pre-inception) is a hard error, not
    a silent zero — this is how a fund's inception gap would corrupt a run."""
    rets = make_panel({"HYG": [np.nan, np.nan, 0.01], "BIL": [0.0] * 3})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])
    with pytest.raises(ValueError, match="NaN return"):
        engine.run_backtest(weights, rets, costs_simple,
                            rf=zero_rf(rets.index), verbose=False)


def test_rejects_ticker_with_no_cost_entry(costs_simple):
    rets = make_panel({"TLT": [0.0] * 3, "BIL": [0.0] * 3})
    weights = pd.DataFrame({"TLT": [1.0]}, index=[rets.index[0]])
    with pytest.raises(ValueError, match="no cost entry"):
        engine.run_backtest(weights, rets, costs_simple,
                            rf=zero_rf(rets.index), verbose=False)


def test_rejects_rf_with_gaps_in_the_sim_window(costs_simple):
    rets = make_panel({"HYG": [0.0] * 4, "BIL": [0.0] * 4})
    rf = zero_rf(rets.index)
    rf.iloc[2] = np.nan
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])
    with pytest.raises(ValueError, match="risk-free"):
        engine.run_backtest(weights, rets, costs_simple, rf=rf, verbose=False)
