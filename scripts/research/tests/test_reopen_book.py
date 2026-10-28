"""Tests for `scripts/research/reopen_book/reopen_book.py`'s helpers.

WHY THESE. The re-open's verdict rests on four mechanical steps: the common
window (a calendar mismatch must be reported, a 2023 date must raise), the
active-spell length that sets the bootstrap block, the non-overlapping sums
behind the 21-session ρ, and the combination arithmetic (P&L, turnover and
gross add; nothing nets). Each is tested on synthetic frames, so these are
statements about the code, never about the market. The module is new, so each
test fails against the tree before it (ImportError).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.research import inference as I
from scripts.research.reopen_book import reopen_book as RB


def _frame(idx, pnl, held, turn=None):
    return pd.DataFrame({"pnl": pnl, "turn": np.zeros(len(idx)) if turn is None else turn,
                         "held_gross": held}, index=idx)


def test_common_window_starts_when_both_exist_and_reports_calendar_gaps():
    idx = pd.bdate_range("2012-01-02", periods=40)
    book = _frame(idx, np.arange(40.0), np.r_[np.zeros(10), np.ones(30)])        # holds from day 10
    s_idx = idx[5:].insert(3, pd.Timestamp("2012-01-21"))                        # a Saturday the book lacks, after day 10
    sleeve = _frame(s_idx.sort_values(), np.ones(len(s_idx)), np.ones(len(s_idx)))
    w, info = RB.common_window(sleeve, book)
    assert w[0] == idx[10] and w[-1] == idx[-1]
    assert info["sleeve_sessions_not_in_book"] == 1 and info["sleeve_pnl_on_those_sessions"] == 1.0
    late = _frame(pd.DatetimeIndex(["2022-12-30", "2023-01-03"]), [0.0, 0.0], [1.0, 1.0])
    with pytest.raises(AssertionError):
        RB.common_window(late, book)


def test_spells_and_block_sums():
    a = pd.Series([0, 1, 1, 0, 1, 1, 1, 0, 0, 1], dtype=bool)
    assert RB.spells(a).tolist() == [2, 3, 1]
    assert RB.spells(pd.Series([False] * 4)).size == 0
    x = pd.Series(np.arange(1.0, 23.0), index=pd.bdate_range("2020-01-01", periods=22))
    s = RB.block_sums(x, 5)                                   # 4 full blocks, 2 sessions dropped
    assert s.tolist() == [15.0, 40.0, 65.0, 90.0] and s.index[0] == x.index[4]
    with pytest.raises(ValueError):
        RB.block_sums(x, 6)                                   # only 3 blocks


def test_combine_adds_pnl_turnover_and_gross_and_refuses_misaligned_frames():
    idx = pd.bdate_range("2015-01-01", periods=5)
    b = _frame(idx, np.full(5, 0.001), np.full(5, 1.2), np.full(5, 0.05))
    s = _frame(idx, np.full(5, -0.002), np.full(5, 0.6), np.full(5, 0.01))
    c = RB.combine(b, s, 1.0)
    assert np.allclose(c["pnl"], -0.001) and np.allclose(c["turn"], 0.06) and np.allclose(c["held_gross"], 1.8)
    assert RB.leverage(c["held_gross"] + np.r_[0, 0, 0, 0, 0.1], 1.8)["share_days_above_cap"] == pytest.approx(0.2)
    with pytest.raises(ValueError):
        RB.combine(b, s.iloc[1:], 1.0)


def test_reading_keys_on_the_upper_end_of_rho_and_the_net_grid():
    assert RB.reading(0.1, 0.2, True).startswith("MEETS the paper-admission rule across")
    assert RB.reading(-0.1, 0.2, True).startswith("MEETS it only at the point")
    assert RB.reading(-0.2, -0.1, True).startswith("DOES NOT MEET (SR_sleeve")
    assert RB.reading(0.1, 0.2, False).startswith("DOES NOT MEET (the combined")
    # the reading's inputs come from marginal_gain, which falls as rho rises when SR_book > 0
    assert I.marginal_gain(0.3, 1.0, 0.4) < I.marginal_gain(0.3, 1.0, 0.0)


def test_deflated_reports_both_bars_and_the_desk_bar_is_desk_dsr():
    rng = np.random.default_rng(2)
    pnl = pd.Series(rng.standard_normal(2_500) * 0.003 + 0.0002)
    s = RB.stats(pnl, pd.Series(np.zeros(2_500)))
    d = RB.deflated(s)
    assert d["desk_dsr"] == pytest.approx(d["upper"]["dsr"], abs=1e-12)
    assert d["gumbel"]["sr0_annual"] < d["upper"]["sr0_annual"]          # the paper's bar is the lower one
    assert d["gumbel"]["dsr"] > d["upper"]["dsr"]
