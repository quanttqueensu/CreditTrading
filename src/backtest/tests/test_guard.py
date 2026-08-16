"""Lookahead-guard tests: unlagged weights must be refused, and the
shift test must flag a pipeline that leaks future information.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest import engine, guard
from src.backtest.tests.conftest import make_panel, zero_rf


# ---------------------------------------------------------------------------
# assert_lagged
# ---------------------------------------------------------------------------

def test_guard_raises_on_unlagged_weights():
    """A row dated t claiming data from t+1 is a look-ahead: refuse."""
    idx = pd.bdate_range("2020-01-02", periods=3)
    weights = pd.DataFrame({"HYG": [1.0, 1.0, 1.0]}, index=idx)
    info = pd.Series([idx[0], idx[2], idx[2]], index=idx)   # row 1 peeks ahead

    with pytest.raises(guard.LookaheadError) as exc:
        guard.assert_lagged(weights, info)
    assert "AFTER their own date" in str(exc.value)
    assert str(idx[1].date()) in str(exc.value)


def test_guard_accepts_same_day_and_older_information():
    """info == row date is legal (signal built from day t's close, applied
    from t+1). Older info is legal too (e.g. a monthly rebalance)."""
    idx = pd.bdate_range("2020-01-02", periods=3)
    weights = pd.DataFrame({"HYG": [1.0, 1.0, 1.0]}, index=idx)

    guard.assert_lagged(weights, pd.Series(idx, index=idx))            # same day
    guard.assert_lagged(weights, pd.Series([idx[0]] * 3, index=idx))   # stale


def test_guard_counts_and_reports_every_offender():
    idx = pd.bdate_range("2020-01-02", periods=4)
    weights = pd.DataFrame({"HYG": [1.0] * 4}, index=idx)
    info = pd.Series([idx[1], idx[2], idx[3], idx[3]], index=idx)  # 3 bad rows

    with pytest.raises(guard.LookaheadError, match="3 weight row"):
        guard.assert_lagged(weights, info)


def test_guard_rejects_malformed_info_dates():
    idx = pd.bdate_range("2020-01-02", periods=3)
    weights = pd.DataFrame({"HYG": [1.0] * 3}, index=idx)

    with pytest.raises(TypeError):
        guard.assert_lagged(weights, list(idx))                 # not a Series
    with pytest.raises(ValueError, match="index must equal"):
        guard.assert_lagged(weights, pd.Series(idx[:2], index=idx[:2]))
    with pytest.raises(ValueError, match="NaT"):
        guard.assert_lagged(
            weights, pd.Series([idx[0], pd.NaT, idx[2]], index=idx))


# ---------------------------------------------------------------------------
# The engine enforces the guard
# ---------------------------------------------------------------------------

def test_engine_refuses_to_run_a_lookahead_strategy(costs_simple):
    """The guard is not advisory — run_backtest raises before simulating."""
    rets = make_panel({"HYG": [0.01] * 4, "BIL": [0.0] * 4})
    weights = pd.DataFrame({"HYG": [1.0] * 4}, index=rets.index)
    info = pd.Series(rets.index[[1, 2, 3, 3]], index=rets.index)  # all peek

    with pytest.raises(guard.LookaheadError):
        engine.run_backtest(weights, rets, costs_simple, rf=zero_rf(rets.index),
                            info_dates=info, verbose=False)


def test_engine_warns_loudly_when_info_dates_are_omitted(costs_simple, capsys):
    rets = make_panel({"HYG": [0.01] * 4, "BIL": [0.0] * 4})
    weights = pd.DataFrame({"HYG": [1.0]}, index=[rets.index[0]])

    engine.run_backtest(weights, rets, costs_simple, rf=zero_rf(rets.index),
                        verbose=True)
    out = capsys.readouterr().out
    assert "WARNING" in out and "lookahead" in out


# ---------------------------------------------------------------------------
# shift_test — the artifact detector
# ---------------------------------------------------------------------------

def test_shift_test_passes_exactly_when_the_delay_changes_nothing(tmp_path):
    """Deterministic honest case, built so the delay provably cannot matter.

    Weights turn on at row 10, so the base run is exposed from row 11 and the
    delayed run from row 12. Returns are zero through row 11, so the ONE day
    where the two exposures differ earns nothing either way and the two paths
    are identical. Costs are set to zero so 'identical' is exact (otherwise
    the entry charge merely lands on a different day). Improvement must be
    exactly 0 — no tolerance, no luck.
    """
    from src.backtest.tests.conftest import write_costs
    free = write_costs(tmp_path, "free.yaml", half_spread_bp=0.0)

    n = 200
    r = np.concatenate([np.zeros(12), np.full(n - 12, 0.001)])
    rets = make_panel({"HYG": r, "BIL": np.zeros(n)})
    w = np.concatenate([np.zeros(10), np.ones(n - 10)])
    weights = pd.DataFrame({"HYG": w}, index=rets.index)

    verdict = guard.shift_test(weights, rets, free,
                               rf=zero_rf(rets.index), verbose=False)
    assert verdict["improvement"] == pytest.approx(0.0, abs=1e-12)
    assert verdict["passed"] is True


def test_shift_test_passes_on_an_honest_signal(costs_simple):
    """An honest (here: information-free, always-invested) strategy cannot
    systematically improve when its signals are delayed.

    NOTE on sample length: shift_test's default tol=0.05 is calibrated for
    full-length samples (HYG is ~4,800 days). The one-day delay drops
    exactly one return from the path, and on a SHORT sample that single day
    can move Sharpe by much more than 0.05 — e.g. at n=300 with one -2.5%
    day, base 0.99 vs delayed 1.14. That is sampling noise, not leakage.
    This test therefore uses a realistic 2,000-day sample, where one day is
    worth ~0.02 of Sharpe. Short-sample callers must widen tol.
    """
    rng = np.random.default_rng(3)
    n = 2000
    rets = make_panel({"HYG": rng.normal(0.0002, 0.01, n), "BIL": np.zeros(n)})
    weights = pd.DataFrame({"HYG": [1.0] * n}, index=rets.index)

    verdict = guard.shift_test(weights, rets, costs_simple,
                               rf=zero_rf(rets.index), verbose=False)
    assert verdict["passed"] is True
    assert abs(verdict["improvement"]) < 0.05


def test_shift_test_catches_a_leaking_signal(costs_simple):
    """A signal built from TOMORROW's return is the planted look-ahead
    artifact. Delaying it by a day realigns it onto the return it was copied
    from... so the delayed run looks far better than the base run, and the
    test must fail.

    Construction: weight_t = 1 if return_{t+2} > 0. The engine applies row t
    from t+1, so the base run trades on return_{t+1} while its signal
    describes return_{t+2} — misaligned by one day, i.e. roughly noise. The
    +1d shift lands the signal exactly on the return it peeked at, producing
    an impossible Sharpe.
    """
    rng = np.random.default_rng(11)
    n = 400
    r = rng.normal(0.0, 0.01, n)
    rets = make_panel({"HYG": r, "BIL": np.zeros(n)})

    peek = pd.Series(r, index=rets.index).shift(-2).fillna(0.0)
    weights = pd.DataFrame({"HYG": (peek > 0).astype(float)}, index=rets.index)

    verdict = guard.shift_test(weights, rets, costs_simple,
                               rf=zero_rf(rets.index), verbose=False)

    # The default tolerance is now derived per signal (bootstrap + lag
    # profile) rather than a flat 0.05, so assert the verdict itself.
    assert verdict["passed"] is False
    assert verdict["improvement"] > 0
    assert verdict["p_value"] < 0.05
    assert verdict["z_shift_vs_other_lags"] > 3.0   # the shifted lag is the odd one out
    assert verdict["shifted_net_sharpe"] > verdict["base_net_sharpe"]


def test_shift_test_reports_its_sample(costs_simple, capsys):
    """Standing rule: the verdict block carries sample dates and N."""
    n = 60
    rets = make_panel({"HYG": [0.001] * n, "BIL": [0.0] * n})
    weights = pd.DataFrame({"HYG": [1.0] * n}, index=rets.index)

    verdict = guard.shift_test(weights, rets, costs_simple,
                               rf=zero_rf(rets.index), name="sample check",
                               verbose=True)
    out = capsys.readouterr().out
    assert str(verdict["start"].date()) in out
    assert str(verdict["end"].date()) in out
    assert f"N={verdict['n_days']}" in out
