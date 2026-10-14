"""C5 feasibility: the declared opening-price rule and the trade counter.

Synthetic frames only. These test the CODE that turns the pre-registration's
declarations into counts (`results/cef/PREREG_C5_OPEN_AUCTION_2026-10-13.md`);
they make no claim about any fund or any market (CLAUDE.md: synthetic data
tests a method, never the world). No panel is read and no network is touched.
"""
import math

import numpy as np
import pandas as pd
import pytest

from scripts.cef import c5_feasibility as c5

IDX = pd.bdate_range("2020-01-06", periods=5)
COLS = ["AAA", "BBB"]


def _prints(rows):
    return pd.DataFrame(rows, columns=["date", "ticker", "exchange", "condition", "price", "t"])


def test_open_rule_takes_the_primary_O_print_and_ignores_other_venues():
    a = _prints([
        (IDX[0], "AAA", "N", "O", 10.00, "x"),
        (IDX[0], "AAA", "P", "O", 10.50, "x"),     # Arca's own open: not the NYSE cross
        (IDX[0], "AAA", "N", "Q", 10.00, "x"),
        (IDX[1], "BBB", "N", "Q", 20.00, "x"),     # official open with no auction trade
    ])
    O, Q = c5.nyse_open_prints(a, IDX, COLS)
    assert O.loc[IDX[0], "AAA"] == 10.00
    assert np.isnan(O.loc[IDX[1], "BBB"]) and Q.loc[IDX[1], "BBB"] == 20.00


def test_open_rule_raises_on_two_O_prints_for_one_name_day():
    a = _prints([(IDX[0], "AAA", "N", "O", 10.00, "x"), (IDX[0], "AAA", "N", "O", 10.01, "y")])
    with pytest.raises(ValueError, match="ambiguous"):
        c5.nyse_open_prints(a, IDX, COLS)


def test_classes_are_O_Q_only_none_and_unpriced_days_are_not_counted():
    O = pd.DataFrame(np.nan, index=IDX, columns=COLS)
    Q = O.copy()
    O.loc[IDX[0], "AAA"] = 1.0
    Q.loc[IDX[1], "AAA"] = 1.0
    priced = pd.DataFrame(True, index=IDX, columns=COLS)
    priced.loc[IDX[4], "BBB"] = False
    cls = c5.classify_open(O, Q, priced)
    assert cls.loc[IDX[0], "AAA"] == "O"
    assert cls.loc[IDX[1], "AAA"] == "Q_only"
    assert cls.loc[IDX[2], "AAA"] == "none"
    assert pd.isna(cls.loc[IDX[4], "BBB"])
    t = c5.coverage_table(cls, "name")
    assert int(t.loc["BBB", "name_days"]) == 4 and int(t.loc["AAA", "name_days"]) == 5


def test_turnover_is_evaluates_turn_line():
    """The feasibility count must use the harness's definition of turnover
    (H2), not a second one. evaluate() is called here on zero returns only."""
    from scripts.cef.band_frontier import evaluate
    rng = np.random.default_rng(0)
    H = pd.DataFrame(rng.normal(0, 0.1, (40, 2)), index=pd.bdate_range("2020-01-01", periods=40), columns=COLS)
    R = pd.DataFrame(0.0, index=H.index, columns=COLS)
    assert math.isclose(c5.turnover(H).mean() * 252, evaluate(H, R)["turn"], rel_tol=1e-12)


def test_a_trade_decided_at_t_is_counted_at_the_open_of_t_plus_1():
    """Alignment: the trade decided on row t goes to the open of row t+1, so it
    needs the opening print of t+1. Removing the shift(1) in trade_summary
    counts it against the print of t and this test fails."""
    H = pd.DataFrame(0.0, index=IDX, columns=COLS)
    H.loc[IDX[2]:, "AAA"] = 0.10                      # decided on IDX[2]
    cls = pd.DataFrame("O", index=IDX, columns=COLS)
    cls.loc[IDX[3], "AAA"] = "none"                   # no cross on IDX[3], the fill day
    r = c5.trade_summary(H, cls, IDX[0], IDX[-1])
    assert r["trade_name_days_material"] == 1
    assert r["material_none"] == 1 and r["material_O"] == 0


def test_trades_below_materiality_are_not_counted_as_material():
    H = pd.DataFrame(0.0, index=IDX, columns=COLS)
    H.loc[IDX[2]:, "AAA"] = c5.MATERIAL / 2
    r = c5.trade_summary(H, None, IDX[0], IDX[-1])
    assert r["trade_sessions_any"] == 1 and r["trade_sessions_material"] == 0


def test_adv_floor_is_restored_even_when_the_body_raises():
    from scripts.cef import band_frontier as bf
    before = bf.MIN_ADV
    with pytest.raises(RuntimeError):
        with c5.adv_floor(0.0):
            assert bf.MIN_ADV == 0.0
            raise RuntimeError("boom")
    assert bf.MIN_ADV == before


def test_holdout_sign_rule_false_kill_is_one_half_at_zero_sharpe():
    assert math.isclose(c5.holdout_false_kill(0.0, 939), 0.5)
    assert c5.holdout_false_kill(1.0, 939) < c5.holdout_false_kill(0.5, 939)


def test_fit_guard_refuses_a_2023_frame():
    with pytest.raises(AssertionError, match="holdout leak"):
        c5._assert_fit(pd.Series(1.0, index=pd.DatetimeIndex(["2022-12-30", "2023-01-03"])))
