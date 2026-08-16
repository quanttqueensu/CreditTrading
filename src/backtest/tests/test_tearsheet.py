"""Tearsheet tests — synthetic series with closed-form answers.

Each expected value is derived in the docstring and written as an explicit
formula, so the test fails if the metric definition drifts (e.g. someone
switches to ddof=0, or to arithmetic annualization).
"""

import types

import numpy as np
import pandas as pd
import pytest

from src.backtest import engine, tearsheet as ts
from src.backtest.tests.conftest import make_panel, zero_rf


def _fake_result(net, gross=None, rf=None, turnover=None, costs=None,
                 name="synthetic"):
    """Minimal duck-typed stand-in for BacktestResult."""
    net = pd.Series(net)
    gross = pd.Series(gross) if gross is not None else net.copy()
    return types.SimpleNamespace(
        name=name, net=net, gross=gross,
        rf=rf if rf is not None else pd.Series(0.0, index=net.index),
        turnover=(turnover if turnover is not None
                  else pd.Series(0.0, index=net.index)),
        costs=costs if costs is not None else pd.Series(0.0, index=net.index),
        start=net.index[0], end=net.index[-1], n_days=len(net),
    )


def _const_series(r, n, start="2020-01-02"):
    return pd.Series(r, index=pd.bdate_range(start, periods=n))


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------

def test_cagr_on_a_constant_return_series():
    """252 days at exactly +4bp/day compounds to (1.0004)^252 - 1, and since
    the sample IS one year the CAGR equals that number exactly."""
    s = _const_series(0.0004, 252)
    expected = 1.0004 ** 252 - 1.0          # = 10.6033%
    assert ts.cagr(s) == pytest.approx(expected)
    assert ts.cagr(s) == pytest.approx(0.106033, abs=1e-6)


def test_cagr_annualizes_a_half_year_correctly():
    """126 days at +4bp/day is half a year; annualizing must SQUARE the
    period growth, not double the return."""
    s = _const_series(0.0004, 126)
    period_growth = 1.0004 ** 126
    assert ts.cagr(s) == pytest.approx(period_growth ** 2 - 1.0)


def test_cagr_is_geometric_not_arithmetic():
    """+50% then -50% leaves 0.75 of the book: the CAGR must be negative,
    even though the arithmetic mean return is zero."""
    s = pd.Series([0.5, -0.5], index=pd.bdate_range("2020-01-02", periods=2))
    assert float(s.mean()) == pytest.approx(0.0)
    assert ts.cagr(s) < 0
    assert ts.cagr(s) == pytest.approx(0.75 ** (252 / 2) - 1.0)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def test_ann_vol_of_a_constant_series_is_zero():
    assert ts.ann_vol(_const_series(0.0004, 252)) == pytest.approx(0.0)


def test_ann_vol_scales_by_sqrt_252():
    """Alternating +/-1% has a daily sample std of 0.01 * sqrt(n/(n-1))."""
    n = 252
    vals = np.tile([0.01, -0.01], n // 2)
    s = pd.Series(vals, index=pd.bdate_range("2020-01-02", periods=n))

    daily_sd = 0.01 * np.sqrt(n / (n - 1))
    assert ts.ann_vol(s) == pytest.approx(daily_sd * np.sqrt(252))


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------

def test_sharpe_closed_form_on_an_alternating_series():
    """Returns alternate a=+20bp and b=-10bp over n=252 days, rf=0.

    mean m           = (a+b)/2                = 5bp
    deviations       = +/-(a-b)/2             = +/-15bp
    sample std       = |a-b|/2 * sqrt(n/(n-1))
    Sharpe           = m/std * sqrt(252)
                     = (m / ((a-b)/2)) * sqrt(n-1)
                     = (1/3) * sqrt(251)      = 5.28099
    """
    a, b, n = 0.002, -0.001, 252
    vals = np.tile([a, b], n // 2)
    s = pd.Series(vals, index=pd.bdate_range("2020-01-02", periods=n))

    expected = (((a + b) / 2) / ((a - b) / 2)) * np.sqrt(n - 1)
    assert ts.sharpe_ratio(s) == pytest.approx(expected)
    assert ts.sharpe_ratio(s) == pytest.approx(5.28099, abs=1e-5)


def test_sharpe_is_excess_of_the_risk_free_series():
    """A strategy returning exactly the risk-free rate has zero excess
    return; a flat 2bp/day above it is pure riskless carry."""
    n = 252
    rf = _const_series(0.0002, n)

    same = _const_series(0.0002, n)
    assert np.isnan(ts.sharpe_ratio(same, rf))      # zero excess, zero vol

    # constant excess -> zero variance -> NaN, not infinity
    carry = _const_series(0.0004, n)
    assert np.isnan(ts.sharpe_ratio(carry, rf))


def test_sharpe_subtracting_rf_lowers_the_ratio():
    """The same return path scores worse once a positive rf is netted off."""
    rng = np.random.default_rng(5)
    n = 500
    s = pd.Series(rng.normal(0.0006, 0.01, n),
                  index=pd.bdate_range("2020-01-02", periods=n))
    rf = _const_series(0.0002, n)

    assert ts.sharpe_ratio(s, rf) < ts.sharpe_ratio(s, None)
    # scalar rf and constant Series rf must agree
    assert ts.sharpe_ratio(s, 0.0002) == pytest.approx(ts.sharpe_ratio(s, rf))


def test_sharpe_rejects_an_rf_that_does_not_cover_the_sample():
    """A short rf must not be silently treated as zero on the missing days."""
    n = 100
    s = _const_series(0.001, n)
    short_rf = _const_series(0.0002, n)[:50]
    with pytest.raises(ValueError, match="does not cover"):
        ts.sharpe_ratio(s, short_rf)


def test_sharpe_of_a_constant_series_is_nan_not_inf():
    """Zero-variance paths return NaN so they cannot poison a median."""
    result = ts.sharpe_ratio(_const_series(0.001, 100))
    assert np.isnan(result)
    assert not np.isinf(result)


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

def test_max_drawdown_hand_computed():
    """+10%, -50%, +10% -> equity 1.10, 0.55, 0.605.
    Peak 1.10 at day 1, trough 0.55 at day 2 -> maxDD = 0.55/1.10 - 1 = -50%."""
    idx = pd.bdate_range("2020-01-02", periods=3)
    s = pd.Series([0.10, -0.50, 0.10], index=idx)

    mdd, peak, trough = ts.max_drawdown(s)
    assert mdd == pytest.approx(-0.50)
    assert peak == idx[0]
    assert trough == idx[1]


def test_max_drawdown_of_a_monotonic_series_is_zero():
    mdd, peak, trough = ts.max_drawdown(_const_series(0.001, 50))
    assert mdd == pytest.approx(0.0)
    assert peak is None and trough is None


def test_max_drawdown_measures_from_the_running_peak_not_the_start():
    """Up 100%, then down 30%: the drawdown is -30% from the new peak, not
    a gain measured against the starting equity."""
    idx = pd.bdate_range("2020-01-02", periods=3)
    s = pd.Series([1.0, -0.30, 0.0], index=idx)

    mdd, peak, trough = ts.max_drawdown(s)
    assert mdd == pytest.approx(-0.30)
    assert peak == idx[0]


# ---------------------------------------------------------------------------
# Worst calendar month
# ---------------------------------------------------------------------------

def test_worst_calendar_month_hand_computed():
    """Jan compounds to +5%, Feb to -10%, Mar to 0%. Worst = Feb, -10%."""
    idx = pd.bdate_range("2020-01-01", "2020-03-31")
    s = pd.Series(0.0, index=idx)
    s.loc["2020-01-15"] = 0.05
    s.loc["2020-02-20"] = -0.10

    worst, label = ts.worst_month(s)
    assert worst == pytest.approx(-0.10)
    assert label == "2020-02"

    monthly = ts.monthly_returns(s)
    assert monthly.loc["2020-01-31"] == pytest.approx(0.05)
    assert monthly.loc["2020-03-31"] == pytest.approx(0.0)


def test_worst_month_compounds_within_the_month():
    """Two -10% days in one month compound to -19%, not -20%."""
    idx = pd.bdate_range("2020-01-01", "2020-02-28")
    s = pd.Series(0.0, index=idx)
    s.loc["2020-02-10"] = -0.10
    s.loc["2020-02-20"] = -0.10

    worst, label = ts.worst_month(s)
    assert worst == pytest.approx(0.9 * 0.9 - 1.0)      # -19%
    assert label == "2020-02"


def test_worst_month_is_calendar_not_rolling():
    """A -15% fall split across a month boundary is never reported as one
    month: each calendar month shows only its own part."""
    idx = pd.bdate_range("2020-01-01", "2020-02-28")
    s = pd.Series(0.0, index=idx)
    s.loc["2020-01-31"] = -0.08
    s.loc["2020-02-03"] = -0.08

    worst, _ = ts.worst_month(s)
    assert worst == pytest.approx(-0.08)


# ---------------------------------------------------------------------------
# Turnover
# ---------------------------------------------------------------------------

def test_avg_annual_turnover_hand_computed():
    """6.0 of one-way turnover over 504 days (= 2 years) is 3.0x per year."""
    n = 504
    turnover = pd.Series(0.0, index=pd.bdate_range("2020-01-02", periods=n))
    turnover.iloc[:6] = 1.0
    assert ts.avg_annual_turnover(turnover, n) == pytest.approx(3.0)


def test_avg_annual_turnover_matches_the_engine(costs_simple):
    """The tearsheet figure must equal what the engine prints for the same run."""
    n = 252
    rets = make_panel({"HYG": [0.0] * n, "JNK": [0.0] * n, "BIL": [0.0] * n})
    # switch HYG <-> JNK twice: 1.0 entry + 2.0 + 2.0 = 5.0 one-way
    weights = pd.DataFrame(
        {"HYG": [1.0, 0.0, 1.0], "JNK": [0.0, 1.0, 0.0]},
        index=[rets.index[0], rets.index[50], rets.index[100]])

    # The last switch is held to the end of the year on purpose, so the stale
    # weight guard is opted out of deliberately (see run_backtest docstring).
    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), max_ffill_days=None,
                              verbose=False)
    m = ts.tearsheet(res, verbose=False)

    assert res.turnover.sum() == pytest.approx(5.0)
    assert m["avg_annual_turnover"] == pytest.approx(5.0 / (n / 252))


# ---------------------------------------------------------------------------
# The tearsheet as a whole
# ---------------------------------------------------------------------------

def test_tearsheet_on_a_known_synthetic_result():
    """Constant +4bp/day for exactly one year, no costs, rf = 0."""
    n = 252
    net = _const_series(0.0004, n)
    m = ts.tearsheet(_fake_result(net), verbose=False)

    assert m["n_days"] == n
    assert m["years"] == pytest.approx(1.0)
    assert m["start"] == net.index[0]
    assert m["end"] == net.index[-1]
    assert m["cagr"] == pytest.approx(1.0004 ** 252 - 1.0)
    assert m["ann_vol"] == pytest.approx(0.0)
    assert m["max_drawdown"] == pytest.approx(0.0)
    assert np.isnan(m["sharpe_net"])             # zero variance
    assert m["hit_rate"] == pytest.approx(1.0)
    assert m["avg_annual_turnover"] == pytest.approx(0.0)


def test_tearsheet_gross_and_net_differ_by_costs_only():
    """Net Sharpe must be strictly worse than gross once costs bite, and the
    cost drag must be reported at the right annualized size."""
    n = 504                                     # two years
    rng = np.random.default_rng(9)
    gross = pd.Series(rng.normal(0.0005, 0.01, n),
                      index=pd.bdate_range("2020-01-02", periods=n))
    cost = pd.Series(0.00002, index=gross.index)   # 2bp/day
    net = gross - cost

    m = ts.tearsheet(_fake_result(net, gross=gross, costs=cost), verbose=False)

    assert m["sharpe_net"] < m["sharpe_gross"]
    assert m["cagr"] < m["cagr_gross"]
    assert m["total_cost_drag"] == pytest.approx(n * 0.00002)
    assert m["cost_drag_annual"] == pytest.approx(252 * 0.00002)


def test_tearsheet_prints_sample_dates_and_n(capsys):
    """Standing rule: every generated tearsheet prints its sample and N."""
    net = _const_series(0.0004, 100)
    m = ts.tearsheet(_fake_result(net, name="printer"), verbose=True)

    out = capsys.readouterr().out
    assert str(net.index[0].date()) in out
    assert str(net.index[-1].date()) in out
    assert "N=100" in out
    assert "printer" in out
    assert m["n_days"] == 100


def test_tearsheet_is_silent_when_asked_to_be(capsys):
    ts.tearsheet(_fake_result(_const_series(0.0004, 50)), verbose=False)
    assert capsys.readouterr().out == ""


def test_tearsheet_works_on_a_real_backtest_result(costs_simple):
    n = 60
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])
    # Buy-and-hold for the whole window: the long carry is the point here, so
    # the stale weight guard is opted out of deliberately.
    res = engine.run_backtest(weights, rets, costs_simple,
                              rf=zero_rf(rets.index), max_ffill_days=None,
                              verbose=False)

    m = ts.tearsheet(res, verbose=False)
    assert m["n_days"] == n
    assert m["start"] == rets.index[0]
    assert m["cagr"] > 0


def test_tearsheet_rejects_objects_that_are_not_results():
    with pytest.raises(TypeError, match="needs a result object"):
        ts.tearsheet({"net": [0.1, 0.2]}, verbose=False)


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def test_to_markdown_carries_the_sample_line():
    net = _const_series(0.0004, 252)
    md = ts.to_markdown(ts.tearsheet(_fake_result(net, name="S1"),
                                     verbose=False))

    assert "### S1" in md
    assert str(net.index[0].date()) in md
    assert str(net.index[-1].date()) in md
    assert "N = 252" in md
    assert "| metric | value |" in md
    for row in ("CAGR (net)", "Annualized vol", "Sharpe (net, excess of rf)",
                "Max drawdown", "Worst calendar month",
                "Avg annual turnover (one-way)"):
        assert row in md


def test_to_markdown_accepts_a_result_directly():
    net = _const_series(0.0004, 60)
    md = ts.to_markdown(_fake_result(net, name="direct"))
    assert "### direct" in md


def test_to_markdown_renders_nan_as_na_not_a_crash():
    """A zero-variance path gives NaN Sharpe; the table must still render."""
    md = ts.to_markdown(_fake_result(_const_series(0.0004, 30), name="flat"))
    assert "n/a" in md


def test_compare_builds_one_row_per_result():
    a = _fake_result(_const_series(0.0004, 100), name="A")
    b = _fake_result(_const_series(0.0002, 100), name="B")

    df = ts.compare([a, b], verbose=False)
    assert list(df.index) == ["A", "B"]
    assert df.loc["A", "cagr"] > df.loc["B", "cagr"]


def test_write_markdown_round_trips(tmp_path):
    net = _const_series(0.0004, 60)
    path = tmp_path / "sub" / "sheet.md"
    text = ts.write_markdown(_fake_result(net, name="W"), path)
    assert path.read_text() == text
    assert "### W" in text
