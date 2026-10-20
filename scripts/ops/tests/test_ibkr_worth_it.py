"""The pure helpers behind results/ops/IBKR_WORTH_IT_2026-10-19.md.

Synthetic inputs: each test is a claim about the code, not the market. Nothing
here reads a panel, a probe snapshot or the network.
"""
import numpy as np
import pandas as pd
import pytest

from scripts.ops import ibkr_worth_it as W


def test_commission_reproduces_ibkrs_own_examples():
    # IBKR's worked examples on the Pro Fixed page (docs/REFERENCES.md §12ag):
    # 100 sh @ 25 = USD 1.00; 1,000 @ 25 = 5.00; 1,000 @ 0.25 = 2.50 (the 1% cap).
    got = [float(W.ibkr_fixed_commission(np.array([q * p]), p)[0])
           for q, p in ((100, 25.0), (1000, 25.0), (1000, 0.25))]
    assert got == pytest.approx([1.00, 5.00, 2.50])


def test_commission_minimum_and_zero():
    # $500 of a $10 fund is 50 shares: 0.25 by the rate, so the USD 1 minimum binds
    assert float(W.ibkr_fixed_commission(np.array([500.0]), 10.0)[0]) == pytest.approx(1.00)
    assert float(W.ibkr_fixed_commission(np.array([0.0]), 10.0)[0]) == 0.0
    with pytest.raises(ValueError):
        W.ibkr_fixed_commission(np.array([-1.0]), 10.0)
    with pytest.raises(ValueError):
        W.ibkr_fixed_commission(np.array([100.0]), 0.0)


def test_routed_trades_are_the_negative_part_only():
    idx = pd.bdate_range("2021-01-04", periods=5)
    H = pd.DataFrame({"A": [0.0, -0.2, -0.3, 0.1, -0.1]}, index=idx)
    got = W.ibkr_routed_trades(H)["A"].round(12).tolist()
    # open -0.2 at IBKR, add -0.1, close 0.3 at IBKR (the +0.1 long is Alpaca's), open -0.1
    assert got == [0.0, 0.2, 0.1, 0.3, 0.1]


def test_names_needing_ibkr_is_derived_from_the_records():
    names = pd.DataFrame({
        "symbol": ["AAA", "BBB", "CCC", "DDD"],
        "in_spec": [True, True, True, False],
        "probe_unshortable": [0, 2, 0, 1],
        "alpaca_20261018_shortable": [False, True, True, False],
    })
    assert W.names_needing_ibkr(names) == ["AAA", "BBB"]
    with pytest.raises(ValueError):
        W.names_needing_ibkr(names.drop(columns="probe_unshortable"))


def test_block_flags_shape_and_extremes():
    idx = pd.bdate_range("2021-01-04", periods=23)
    rng = np.random.default_rng(0)
    f = W.block_flags(idx, ["A", "B"], 0.5, 5, rng)
    assert f.shape == (23, 2) and (f.dtypes == bool).all()
    # constant within each 5-session block
    for c in f:
        for s in range(0, 23, 5):
            assert f[c].iloc[s:s + 5].nunique() == 1
    assert not W.block_flags(idx, ["A"], 0.0, 5, rng).any().any()
    assert W.block_flags(idx, ["A"], 1.0, 5, rng).all().all()
    with pytest.raises(ValueError):
        W.block_flags(idx, ["A"], 1.5, 5, rng)


def test_reneutral_keeps_short_total_and_counts_rows_it_cannot_fix():
    idx = pd.bdate_range("2021-01-04", periods=2)
    T = pd.DataFrame({"A": [-0.2, -0.3], "B": [-0.1, 0.0], "C": [0.3, 0.3]}, index=idx)
    blk = pd.DataFrame({"A": [True, True]}, index=idx)
    T2, stuck = W.reneutral_targets(T, blk)
    assert T2.loc[idx[0]].tolist() == pytest.approx([0.0, -0.3, 0.3])   # B carries the whole short
    assert T2.loc[idx[1]].tolist() == pytest.approx([0.0, 0.0, 0.3])    # no other short: left net long
    assert stuck == 1


def test_nw_t_matches_iid_t_with_zero_lags():
    x = pd.Series(np.random.default_rng(1).normal(0.1, 1.0, 500))
    iid = x.mean() / (x.std(ddof=0) / np.sqrt(len(x)))
    assert W.nw_t(x, lags=0) == pytest.approx(iid)
