"""The slate's bar arithmetic and eligibility rule, on synthetic inputs.

These test the CODE that turns a declared rule into a fit window and a required
Sharpe; they make no claim about any market (CLAUDE.md: synthetic data tests a
method, never the world). No panel is read and no network is touched.
"""
import math

import pandas as pd
import pytest

from scripts.xasset import slate_feasibility as sf


def test_required_sharpe_inverts_the_repo_bar():
    """At the returned Sharpe, validate._dsr sits on its PASS line (0.95), and the
    requirement rises with N and falls with history -- the two directions the
    slate-size argument rests on."""
    from scripts.cef.validate import _dsr
    n_days = 252 * 15
    r5 = sf.required_sharpe(5, n_days)
    d, _, _ = _dsr(r5, n_days, 0.0, 3.0, 5)
    assert d == pytest.approx(0.95, abs=1e-6)
    assert sf.required_sharpe(3, n_days) < r5 < sf.required_sharpe(162, n_days)
    assert sf.required_sharpe(5, 252 * 25) < r5
    # Above the agenda's sr0 reading: DSR 0.95 needs about 1.645 more t than sqrt(2 ln N).
    sr0 = math.sqrt(2 * math.log(5)) / math.sqrt(n_days / 252)
    assert r5 > sr0


def test_fit_window_half_rule_and_lag():
    """Three instruments; 'half' needs two eligible. Eligible at month-end E once
    the first return is on or before the first session after the month-end
    `lag` months earlier."""
    cal = pd.bdate_range("2000-01-03", "2003-12-31")
    firsts = {"A": pd.Timestamp("2000-01-03").date(),
              "B": pd.Timestamp("2000-06-01").date(),
              "C": pd.Timestamp("2002-01-01").date()}   # bdate_range keeps 1 Jan as a session
    first_dec, n_fit, need = sf.fit_window(["A", "B", "C"], 12, "half", firsts, cal)
    assert need == 2
    # B's first return 2000-06-01 is the first session after 2000-05-31, so B is
    # eligible at the month-end 12 months after May 2000.
    assert str(first_dec) == "2001-05-31"
    first_all, _, need_all = sf.fit_window(["A", "B", "C"], 12, "all", firsts, cal)
    assert need_all == 3 and str(first_all) == "2002-12-31"
    # One session late and the whole month is lost: C starting 2002-01-02 misses
    # the window that opens 2002-01-01, so 'all' first holds at 2003-01-31.
    late = dict(firsts, C=pd.Timestamp("2002-01-02").date())
    assert str(sf.fit_window(["A", "B", "C"], 12, "all", late, cal)[0]) == "2003-01-31"


def test_fit_window_raises_when_rule_never_holds():
    cal = pd.bdate_range("2000-01-03", "2000-12-29")
    with pytest.raises(RuntimeError):
        sf.fit_window(["A"], 36, "all", {"A": pd.Timestamp("2000-01-03").date()}, cal)


def test_coverage_raises_for_an_instrument_no_panel_holds():
    cal = pd.bdate_range("2000-01-03", "2000-01-10")
    df = pd.DataFrame({"date": cal, "ticker": "A", "ret_total": 0.0})
    with pytest.raises(KeyError):
        sf.coverage("ZZZ", {"p": df}, cal)


def test_coverage_counts_interior_gaps():
    cal = pd.bdate_range("2000-01-03", "2000-01-14")          # 10 sessions
    df = pd.DataFrame({"date": cal, "ticker": "A", "ret_total": 0.001})
    df.loc[3, "ret_total"] = float("nan")                      # one hole inside the range
    row = sf.coverage("A", {"p": df}, cal)
    assert row["interior_gaps"] == 1 and row["sessions"] == 9
