"""Tests for scripts/cef/portfolio_baseline.py's pure helpers.

Every input here is synthetic: these test whether the METHODS behave (CLAUDE.md,
"synthetic data tests whether a method behaves, never a claim about the market").
Nothing reads data/ and nothing opens a socket. Each test was checked to fail
against a deliberately wrong version of the helper it covers (named in its
docstring) before it was kept.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.cef import portfolio_baseline as pb
from scripts.cef.spec import risk


def _s(vals, start="2015-01-02"):
    return pd.Series(vals, index=pd.bdate_range(start, periods=len(vals)), dtype=float)


def test_max_drawdown_known_path():
    """Fails if the peak is taken before compounding, or if the start (1.0) is not a peak."""
    m = pb.max_drawdown(_s([0.10, -0.50, 0.20, 1.00]))
    assert m["mdd"] == pytest.approx(0.5)
    assert m["peak"] == pd.Timestamp("2015-01-02")
    assert m["trough"] == pd.Timestamp("2015-01-05")
    assert m["recovered"] == pd.Timestamp("2015-01-07")
    first = pb.max_drawdown(_s([-0.10, 0.05]))
    assert first["mdd"] == pytest.approx(0.10)
    assert first["peak"] is None and first["recovered"] is None
    assert pb.max_drawdown(_s([0.01, 0.02]))["mdd"] == 0.0


def test_max_drawdown_refuses_a_gap():
    with pytest.raises(ValueError):
        pb.max_drawdown(_s([0.01, np.nan]))


def test_euler_split_sums_to_one_and_matches_by_hand():
    """h = (1, -1), S = diag(1, 4), b = (1, 0): b'Sh = 1 of h'Sh = 5. Fails if the
    split uses b'Sb instead of b'Sh (it would not sum to one)."""
    S = np.diag([1.0, 4.0])
    sb, sw = pb.euler_split(np.array([1.0, -1.0]), S, np.array([1.0, 0.0]))
    assert (sb, sw) == pytest.approx((0.2, 0.8))
    rng = np.random.default_rng(1)
    A = rng.standard_normal((6, 6))
    S = A @ A.T
    h, b = rng.standard_normal(6), rng.standard_normal(6)
    sb, sw = pb.euler_split(h, S, b)
    tot = h @ S @ h
    assert sb == pytest.approx(b @ S @ h / tot)
    assert sw == pytest.approx((h - b) @ S @ h / tot)


def test_group_component_nets_to_zero_within_every_group():
    """The remainder h - b must be pure selection. Fails if the group net is
    spread over the HELD names only (then an unheld member carries no group risk)."""
    names = ["a", "b", "c", "d", "e"]
    grp = {"a": "g1", "b": "g1", "c": "g2", "d": "g2", "e": "g2"}
    h = pd.Series({"a": 0.3, "b": 0.0, "c": -0.1, "d": -0.2, "e": 0.0})
    b = pb.group_component(h, grp, names)
    assert b["a"] == pytest.approx(0.15) and b["b"] == pytest.approx(0.15)
    assert b[["c", "d", "e"]].tolist() == pytest.approx([-0.1, -0.1, -0.1])
    w = h.reindex(names) - b
    for g in ("g1", "g2"):
        assert w[[n for n in names if grp[n] == g]].sum() == pytest.approx(0.0)


def test_group_component_refuses_a_held_name_without_covariance():
    with pytest.raises(ValueError):
        pb.group_component(pd.Series({"a": 0.5, "z": -0.5}), {"a": "g", "z": "g"}, ["a"])


def test_breadth_is_n_on_independent_equal_risk_names_and_near_one_on_one_factor():
    """Fails if the tail components are lumped or if v_k omits the eigenvalue
    (diag(4, 1) with h = (1, 1): v = (0.8, 0.2), BR = 1/0.68; without the
    eigenvalue v = (0.5, 0.5) and BR would read 2)."""
    assert pb.breadth(np.ones(2), np.diag([4.0, 1.0]))["br"] == pytest.approx(1 / 0.68)
    n = 8
    h = np.array([1, -1] * (n // 2), dtype=float)
    assert pb.breadth(h, np.eye(n))["br"] == pytest.approx(n)
    beta = np.linspace(0.5, 1.5, n)
    S = 100.0 * np.outer(beta, beta) + 0.01 * np.eye(n)
    r = pb.breadth(beta, S)
    assert r["br"] < 1.01 and r["top"] > 0.99


def test_breadth_refuses_a_covariance_that_is_not_psd():
    with pytest.raises(ValueError):
        pb.breadth(np.array([1.0, -1.0]), np.array([[1.0, 2.0], [2.0, 1.0]]))


def test_estimable_names_drops_the_name_with_no_overlap():
    """A name that had not listed yet has no covariance with the others; it is
    dropped, never filled. Fails if the selection keeps every name with a variance."""
    idx = pd.bdate_range("2020-01-01", periods=260)
    rng = np.random.default_rng(3)
    R = pd.DataFrame(rng.standard_normal((260, 4)) * 0.01, index=idx,
                     columns=["a", "b", "old", "new"])
    R.loc[idx[130:], "old"] = np.nan          # delisted half-way
    R.loc[idx[:130], "new"] = np.nan          # listed half-way: never overlaps "old"
    S = R.cov(min_periods=126)
    assert S.loc["old", "old"] == S.loc["old", "old"] and S.loc["new", "new"] == S.loc["new", "new"]
    assert pd.isna(S.loc["old", "new"])
    assert pb.estimable_names(S, R.notna().sum()) == ["a", "b", "old"]


def test_stationary_index_is_reproducible_in_range_and_continues_blocks():
    """Fails if a new block starts every step (iid) or never (one block)."""
    n, L, reps, mb = 300, 252, 400, 21
    i1 = pb.stationary_index(n, L, reps, mb, np.random.default_rng(7))
    i2 = pb.stationary_index(n, L, reps, mb, np.random.default_rng(7))
    assert i1.shape == (reps, L) and (i1 == i2).all()
    assert i1.min() >= 0 and i1.max() < n
    cont = ((i1[:, 1:] - i1[:, :-1]) % n == 1).mean()
    assert cont == pytest.approx(1 - 1 / mb, abs=0.01)
    with pytest.raises(ValueError):
        pb.stationary_index(30, L, reps, 21, np.random.default_rng(0))


def test_p_breach_is_zero_for_a_tiny_book_and_rises_with_size():
    rng = np.random.default_rng(11)
    x = rng.standard_normal(2000) * 0.004 + 0.0002
    idx = pb.stationary_index(len(x), 252, 2000, 21, np.random.default_rng(12))
    ps = [pb.p_breach(x, s, 0.12, idx=idx) for s in (0.01, 0.05, 0.10, 0.20, 0.30)]
    assert ps[0] == 0.0
    assert all(a <= b for a, b in zip(ps, ps[1:])) and ps[-1] > 0.5
    with pytest.raises(ValueError):
        pb.p_breach(x, 0.1, 0.12)                    # neither idx nor gauss


def test_sigma_star_meets_the_tolerance_at_its_edge():
    """Fails if the bisection keeps the breaching end of the bracket."""
    rng = np.random.default_rng(21)
    x = rng.standard_normal(2000) * 0.004 + 0.0001
    g = np.random.default_rng(22).standard_normal((2000, 252))
    s = pb.sigma_star(x, 0.12, 0.05, gauss=g)
    assert s is not None and 0.001 < s < 0.40
    assert pb.p_breach(x, s, 0.12, gauss=g) <= 0.05
    assert pb.p_breach(x, s + 0.005, 0.12, gauss=g) > 0.05
    # a series that loses heavily breaches even at the bottom of the bracket
    bad = rng.standard_normal(2000) * 0.004 - 0.004
    assert pb.sigma_star(bad, 0.12, 0.05, gauss=g, lo=0.05) is None


def test_group_proxy_fills_from_the_same_day_group_mean_and_counts():
    idx = pd.bdate_range("2008-09-01", periods=3)
    r = pd.DataFrame({"a": [0.01, 0.02, 0.03], "b": [0.03, np.nan, 0.01],
                      "c": [np.nan, np.nan, np.nan], "m": [0.0, 0.0, 0.0]}, index=idx)
    grp = {"a": "tax", "b": "tax", "c": "tax", "m": "muni"}
    out, n = pb.group_proxy(r, grp)
    assert n == 4
    assert out.loc[idx[1], "b"] == pytest.approx(0.02)          # the mean of a alone that day
    assert out["c"].tolist() == pytest.approx([0.02, 0.02, 0.02])
    with pytest.raises(ValueError):
        pb.group_proxy(pd.DataFrame({"x": [np.nan]}, index=idx[:1]), {"x": "g"})


def test_drawdown_lines_are_the_specs_fractions():
    """The units trap of 2026-08-31: a percent key read as a fraction. These are fractions."""
    assert pb.HALVE_DD == float(risk("halve_drawdown"))
    assert pb.KILL_DD == float(risk("kill_drawdown"))
    assert 0 < pb.HALVE_DD < pb.KILL_DD < 1
