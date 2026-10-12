"""Tests for W10 Part B's decompositions, the core-signal event-time indexing,
and the group-observables fetcher's guards.

WHY THESE. Every number in results/cef/W10_PARTB_2026-10-12.md rests on two
exact identities (z - zbar = between + within; H = B + W with P&L adding up)
and on one claim the negative control is built on: if forward returns are
linear in z with no group structure, the between and within slopes are EQUAL
for any grouping. Each is pinned on synthetic input -- a statement about the
code, never about the market (CLAUDE.md data rules). The fetcher tests feed
literal data to the parsers and the splice; nothing here opens a socket (the
root conftest blocks it anyway).
"""
from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd
import pytest

from scripts.cef import w10_partb as w
from scripts.cef import core_signal_decomp as c
from scripts.cef.band_frontier import evaluate
from scripts.data import fetch_group_observables as g

NAMES = list("ABCDEFGH")
GRP = {"A": "multi", "B": "multi", "C": "multi", "D": "multi", "E": "hy", "F": "hy",
       "G": "muni", "H": "loan"}


def _z(n=60, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-04", periods=n)
    z = pd.DataFrame(rng.normal(size=(n, len(NAMES))), index=idx, columns=NAMES)
    M = pd.DataFrame(rng.random((n, len(NAMES))) > 0.15, index=idx, columns=NAMES)
    M.iloc[:, :6] = True                       # always >= 6 admitted, like min_names
    return z, M


@pytest.mark.parametrize("rule", ["algebraic", "declared"])
def test_signal_decomposition_is_exact(rule):
    z, M = _z()
    zb, zw = w.decompose_signal(z, M, GRP, rule)
    zz = z.where(M)
    assert np.allclose((zb + zw).stack(), zz.sub(zz.mean(axis=1), axis=0).stack())
    assert (zb.notna() == zz.notna()).all().all()
    for grp in set(GRP.values()):
        cols = [t for t in NAMES if GRP[t] == grp]
        assert (zw[cols].sum(axis=1, min_count=1).dropna().abs() < 1e-12).all()


def test_algebraic_parts_are_orthogonal_and_between_is_constant_in_group():
    z, M = _z(seed=1)
    zb, zw = w.decompose_signal(z, M, GRP, "algebraic")
    assert ((zb * zw).sum(axis=1).abs() < 1e-12).all()
    multi = [t for t in NAMES if GRP[t] == "multi"]
    for d in z.index:
        v = zb.loc[d, multi].dropna()
        assert np.allclose(v, v.iloc[0])


def test_declared_rule_makes_small_groups_between_only():
    z, M = _z(seed=2)
    zb, zw = w.decompose_signal(z, M, GRP, "declared")
    for t in ("E", "F", "G", "H"):                 # hy (2), muni (1), loan (1) are < 3
        assert (zw[t].dropna() == 0).all()
    zz = z.where(M)
    assert np.allclose(zb["E"].dropna(), (zz["E"] - zz.mean(axis=1)).dropna())


@pytest.mark.parametrize("rule", ["algebraic", "declared"])
def test_holdings_decomposition_adds_up_through_evaluate(rule):
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2016-01-04", periods=80)
    H = pd.DataFrame(rng.normal(0, 0.1, (80, 8)), index=idx, columns=NAMES)
    H[H.abs() < 0.03] = 0.0                        # some names not held
    R = pd.DataFrame(rng.normal(0, 0.01, (80, 8)), index=idx, columns=NAMES)
    B, W = w.decompose_holdings(H, GRP, rule)
    assert (B + W - H).abs().max().max() < 1e-15
    pt, pb, pw = (evaluate(X, R)["pnl"] for X in (H, B, W))
    assert np.allclose(pb + pw, pt, atol=1e-15)
    # between P&L = sum over groups of net weight x mean return of the HELD names (algebraic)
    if rule == "algebraic":
        Hs, d = H.shift(2), idx[10]
        exp = 0.0
        for grp in set(GRP.values()):
            cols = [t for t in NAMES if GRP[t] == grp and Hs.loc[d, t] != 0]
            if cols:
                exp += Hs.loc[d, cols].sum() * R.loc[d, cols].mean()
        assert np.isclose(pb.loc[d], exp)


def test_slopes_equal_for_any_grouping_without_group_structure():
    """The negative control's null: F linear in (z - zbar), no noise -> both
    component slopes equal the true slope, whatever the grouping."""
    z, M = _z(n=40, seed=4)
    zz = z.where(M)
    beta = -0.0012
    F = beta * zz.sub(zz.mean(axis=1), axis=0)
    rng = np.random.default_rng(5)
    for _ in range(5):
        perm = dict(zip(NAMES, rng.permutation(list(GRP.values()))))
        zb, zw = w.decompose_signal(z, M, perm, "algebraic")
        r, _ = w.pooled_components(zb, zw, F, M, z.index)
        assert np.isclose(r["slope_between"], beta * 1e4)
        assert np.isclose(r["slope_within"], beta * 1e4)
        assert np.isclose(r["slope_z"], beta * 1e4)


def test_event_days_index_sessions_and_prefer_post():
    idx = pd.bdate_range("2016-01-04", periods=40)
    ex = pd.DataFrame(False, index=idx, columns=["A"])
    ex.iloc[[10, 30], 0] = True
    sp = ex.copy()
    sp.iloc[30, 0] = True
    sp.iloc[10, 0] = False
    K, T = c.event_days(ex, sp)
    assert K.iloc[10, 0] == 0 and K.iloc[5, 0] == -5 and K.iloc[20, 0] == 10
    assert np.isnan(K.iloc[4, 0])                       # beyond PRE before the first event
    assert K.iloc[25, 0] == -5 and T.iloc[25, 0] == 1.0  # 25 is post+15 of the first: pre-5 of the second
    assert T.iloc[12, 0] == 0.0


# ------------------------------------------------------------------ fetcher guards

def _hist(dates, vals):
    return pd.DataFrame({"date": pd.to_datetime(dates), "bamlh0a0hym2": vals})


def test_splice_ice_requires_exact_overlap(monkeypatch):
    monkeypatch.setattr(g, "MIN_OVERLAP", 2)
    hist = _hist(["2024-01-02", "2024-01-03", "2024-01-04"], [3.0, 3.1, 3.2])
    patch = pd.DataFrame({"date": pd.to_datetime(["2024-01-03", "2024-01-04", "2024-01-05"]),
                          "value": [3.1, 3.2, 3.3]})
    out = g.splice_ice("hy_oas", "BAMLH0A0HYM2", hist, patch)
    assert list(out.value) == [3.0, 3.1, 3.2, 3.3]
    bad = patch.assign(value=[3.1, 3.25, 3.3])
    with pytest.raises(g.ObservableError, match="disagree"):
        g.splice_ice("hy_oas", "BAMLH0A0HYM2", hist, bad)
    short = patch.iloc[2:]
    with pytest.raises(g.ObservableError, match="overlaps"):
        g.splice_ice("hy_oas", "BAMLH0A0HYM2", hist, short)


def test_parse_ofr_drops_null_and_rejects_shape():
    df = g.parse_ofr("X", json.dumps([["2020-01-02", 1.5], ["2020-01-03", None], ["2020-01-06", 1.6]]))
    assert list(df.value) == [1.5, 1.6]
    with pytest.raises(g.ObservableError):
        g.parse_ofr("X", json.dumps({"error": "nope"}))


def test_parse_sifma_and_weekly_guard():
    buf = io.BytesIO()
    raw = pd.DataFrame([["Date", "Index Value"], [pd.Timestamp("2020-01-15"), 1.2],
                        [pd.Timestamp("2020-01-08"), 1.1]])
    raw.to_excel(buf, sheet_name="S", header=False, index=False)
    df = g.parse_sifma(buf.getvalue(), "S")
    assert list(df.date) == [pd.Timestamp("2020-01-08"), pd.Timestamp("2020-01-15")]
    g.check_weekly(df)
    odd = pd.concat([df, pd.DataFrame({"date": [pd.Timestamp("2020-01-17")], "value": [1.3]})])
    with pytest.raises(g.ObservableError, match="KNOWN_IRREGULAR"):
        g.check_weekly(odd.reset_index(drop=True))
