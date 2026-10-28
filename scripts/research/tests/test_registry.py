"""The trial registry: stored series come back byte-identical, a judged result
is never replaced, and the bar's inputs are measured from the series.

The counter table is replaced by a fixture, so these tests never depend on how
many trials the live table holds today (H14).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from scripts.research import registry as rg  # noqa: E402


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "_counters", lambda: {"CEF": {"trials": 2}, "MACRO": {"trials": 0}})
    real_git = rg._git
    monkeypatch.setattr(rg, "_git", lambda *a: "" if a[0] == "status" else real_git(*a))
    return tmp_path


def _pnl(seed=0, n=600, start="2015-01-01", base=None, rho=0.0):
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0004, 0.01, n)
    if base is not None:
        x = rho * base.to_numpy() + np.sqrt(1 - rho ** 2) * x
    return pd.Series(x, index=pd.bdate_range(start, periods=n))


def test_round_trip_and_ledger(reg):
    s = _pnl()
    line = rg.record(s, counter="CEF", trial="CEF-53", variant="band_0.048", params={"b": 0.048}, root=reg)
    back = rg.load(line, root=reg)
    assert np.array_equal(back.to_numpy(), s.to_numpy()) and back.index.equals(s.index)
    ledger = [json.loads(x) for x in (reg / rg.LEDGER).read_text().splitlines()]
    assert len(ledger) == 1 and ledger[0]["sha256"] == line["sha256"]
    assert ledger[0]["kurt"] == pytest.approx(s.kurt() + 3)       # raw kurtosis, inference's convention
    assert ledger[0]["first"] == "2015-01-01" and ledger[0]["n"] == 600


def test_same_bytes_is_a_noop_different_bytes_refused(reg):
    s = _pnl()
    a = rg.record(s, counter="CEF", trial="CEF-53", variant="v", params={}, root=reg)
    b = rg.record(s.copy(), counter="CEF", trial="CEF-53", variant="v", params={}, root=reg)
    assert a == b and len((reg / rg.LEDGER).read_text().splitlines()) == 1
    with pytest.raises(ValueError, match="never replaced"):
        rg.record(s * 1.01, counter="CEF", trial="CEF-53", variant="v", params={}, root=reg)


@pytest.mark.parametrize("kw, match", [
    (dict(counter="NOPE"), "not in the canonical table"),
    (dict(trial="../x"), "must match"),
    (dict(variant="a b"), "must match"),
])
def test_refusals(reg, kw, match):
    args = dict(counter="CEF", trial="CEF-53", variant="v", params={}, root=reg)
    args.update(kw)
    with pytest.raises(ValueError, match=match):
        rg.record(_pnl(), **args)


def test_bad_series_refused(reg):
    s = _pnl()
    s.iloc[3] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        rg.record(s, counter="CEF", trial="T", variant="v", params={}, root=reg)
    with pytest.raises(ValueError, match="constant"):
        rg.record(s.fillna(0) * 0 + 0.001, counter="CEF", trial="T", variant="w", params={}, root=reg)
    with pytest.raises(TypeError, match="JSON"):
        rg.record(_pnl(), counter="CEF", trial="T", variant="x", params={"f": object()}, root=reg)


def test_dirty_tree_refused_unless_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "_counters", lambda: {"CEF": {"trials": 1}})
    real_git = rg._git
    monkeypatch.setattr(rg, "_git", lambda *a: " M x.py" if a[0] == "status" else real_git(*a))
    with pytest.raises(RuntimeError, match="uncommitted"):
        rg.record(_pnl(), counter="CEF", trial="T", variant="v", params={}, root=tmp_path)
    line = rg.record(_pnl(), counter="CEF", trial="T", variant="v", params={}, root=tmp_path,
                     allow_dirty=True)
    assert line["dirty"] is True


def test_tampered_series_refused(reg):
    line = rg.record(_pnl(), counter="CEF", trial="T", variant="v", params={}, root=reg)
    p = reg / line["path"]
    df = pd.read_parquet(p)
    df.iloc[0, 0] += 1e-9
    df.to_parquet(p)
    with pytest.raises(ValueError, match="altered"):
        rg.load(line, root=reg)


def test_matrix_reports_what_the_intersection_dropped(reg):
    rg.record(_pnl(1), counter="CEF", trial="T1", variant="a", params={}, root=reg)
    rg.record(_pnl(2, n=500, start="2015-03-02"), counter="CEF", trial="T1", variant="b", params={}, root=reg)
    M, info = rg.matrix("CEF", root=reg)
    assert M.shape[1] == 2 and info["common_sessions"] == len(M) == 500
    assert info["dropped"] == info["union_sessions"] - 500 > 0


def test_bar_inputs_measure_correlation_and_coverage(reg):
    base = _pnl(10)
    rg.record(base, counter="CEF", trial="T1", variant="a", params={}, root=reg)
    rg.record(_pnl(11, base=base, rho=0.999), counter="CEF", trial="T1", variant="b", params={}, root=reg)
    rg.record(_pnl(12, base=base, rho=0.999), counter="CEF", trial="T1", variant="c", params={}, root=reg)
    b = rg.bar_inputs("CEF", root=reg)
    assert b["variants"] == 3 and b["n_effective"] < 1.1     # three near-copies are about one trial
    assert b["stored_trials"] == 1 and b["coverage"] == 0.5
    assert b["paper_bar_may_gate"] is False                  # 1 of the counter's 2 trials stored
    rg.record(_pnl(20), counter="CEF", trial="T2", variant="a", params={}, root=reg)
    b = rg.bar_inputs("CEF", root=reg)
    assert b["paper_bar_may_gate"] is True and b["sr_var"] > 0
    assert 1.5 < b["n_effective"] < 4


def test_independent_variants_count_fully(reg):
    for i in range(4):
        rg.record(_pnl(30 + i), counter="CEF", trial=f"T{i}", variant="a", params={}, root=reg)
    b = rg.bar_inputs("CEF", root=reg)
    assert b["n_effective"] == pytest.approx(4, abs=0.3)
