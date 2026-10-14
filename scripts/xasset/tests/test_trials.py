"""The four XASSET trial builders and the stage pipeline, on SYNTHETIC returns.

These are claims about the code (CLAUDE.md: synthetic data tests a method, never
the market). No panel, cache or network is read: every input is generated here,
and the readers of real caches (AQR, French) are replaced by stubs. What is
checked: each rule builds the declared positions on the declared days; the
pipeline runs every stage in order and names the first failing rule; the holdout
reproduces the fit rows exactly from one continuous series; and the X1/X4
placebo REFUSES to invent a return for a fund that did not yet exist (the
question put to the team lead on 2026-10-14), rather than silently scoring 0.
"""
import dataclasses
import functools

import numpy as np
import pandas as pd
import pytest

from scripts.cef.band_frontier import month_end_sessions
from scripts.xasset import protocol as P, runner, tsmom
from scripts.xasset import x1_credit_trend as x1, x2_rebalancing as x2, x3_month_end as x3

FIRSTS = {"HYG": "2007-04-12", "LQD": "2002-07-29", "IEF": "2002-07-29", "TLT": "2002-07-29",
          "EMB": "2007-12-20", "PFF": "2007-04-02", "MUB": "2007-09-11", "BKLN": "2011-03-04",
          "CWB": "2009-04-17", "SPY": "1993-02-01", "EFA": "2001-08-20", "EEM": "2003-04-14",
          "GLD": "2004-11-19", "DBC": "2006-02-06", "SHY": "2002-07-29", "BIL": "2007-05-31",
          "IEI": "2007-01-12", "TLH": "2007-01-12", "AGG": "2003-09-29"}


def _panel(end="2026-09-30", seed=0, drift=0.0002):
    cal = pd.bdate_range("2001-01-02", end)
    rng = np.random.default_rng(seed)
    R = pd.DataFrame(rng.normal(drift, 0.008, (len(cal), len(FIRSTS))), index=cal, columns=list(FIRSTS))
    for n, f in FIRSTS.items():
        R.loc[R.index < pd.Timestamp(f), n] = np.nan
    rf = pd.Series(0.00005, index=cal)
    return R, rf


def _data(end):
    R, rf = _panel()
    R = R.loc[:end] if end != "fit" else R.loc[R.index < P.HOLDOUT_START]
    rf = rf.reindex(R.index)
    Rx = P.excess(R, rf)
    panel = (R.stack().rename("ret_total").reset_index().rename(columns={"level_0": "date", "level_1": "ticker"}))
    panel["prc_adj"], panel["volume"] = 50.0, 1e6
    book = pd.Series(np.random.default_rng(1).normal(0, 0.005, len(R)), index=R.index).loc["2013-06-03":]
    flags = pd.DataFrame(columns=["ticker", "date", "check"])
    return dict(panel=panel, R=R, rf=rf, Rx=Rx, cal=R.index, book=book, flags=flags, R_inhouse=R.copy())


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(P, "BOOT_REPS", 40)
    monkeypatch.setattr(P, "placebo", functools.partial(P.placebo, draws=15))
    monkeypatch.setattr(P, "paired_sharpe_diff", functools.partial(P.paired_sharpe_diff, reps=40))
    monkeypatch.setattr(P, "aqr_regression", lambda *a, **k: {"stub": True})
    monkeypatch.setattr(P, "ff_regression", lambda *a, **k: {"stub": True})
    monkeypatch.setattr(x2, "PERMUTATIONS", 10)


# ----------------------------------------------------------------------------- builders
def test_tsmom_weights_signs_eligibility_and_mub():
    cal = pd.bdate_range("2010-01-01", "2012-06-29")
    Rx = pd.DataFrame(0.0, index=cal, columns=["A", "MUB", "C"])
    Rx["A"] = 0.001                       # up-trend
    Rx["MUB"] = -0.001                    # down-trend: long-or-flat gives 0
    Rx["C"] = np.where(cal >= pd.Timestamp("2011-09-01"), 0.001, np.nan)   # too young until 2012-08
    Rx = Rx + np.random.default_rng(0).normal(0, 1e-4, Rx.shape) * Rx.notna()
    T = tsmom.targets(Rx, ["A", "MUB", "C"], pd.Timestamp("2011-01-31"))
    E = pd.Timestamp("2011-06-30")
    sig = tsmom.ex_ante_sigma(Rx["A"]).loc[E]
    assert T.loc[E, "A"] == pytest.approx(0.40 / sig / 2)      # S = 2: A and MUB (C ineligible)
    assert T.loc[E, "MUB"] == 0.0 and T.loc[E, "C"] == 0.0
    assert (T >= 0).all().all()
    tsh = tsmom.targets(Rx, ["A", "MUB", "C"], pd.Timestamp("2011-01-31"), "tsh")
    assert tsh.loc[E, "A"] == pytest.approx(T.loc[E, "A"])     # same weights, same sign here


def test_x3_window_rows_are_e_minus_4_to_e_minus_2():
    cal = pd.bdate_range("2021-01-04", "2021-03-31")
    h = x3.window_rows(cal)
    jan = h.loc["2021-01"]
    assert list(jan[jan == 1].index.strftime("%m-%d")) == ["01-25", "01-26", "01-27"]   # E = 01-29
    assert h.sum() == 9


def test_x2_drift_threshold_and_calendar_resets():
    cal = pd.bdate_range("2021-01-04", "2021-03-31")
    R = pd.DataFrame({"SPY": 0.01, "IEF": 0.0}, index=cal)
    thr, cs = x2.signals(R, cal[0])
    # one day of drift from 60%: 0.6*1.01/(0.6*1.01+0.4) - 0.6
    d1 = 0.6 * 1.01 / (0.6 * 1.01 + 0.4) - 0.6
    assert cs.iloc[1] == pytest.approx(d1)
    # the delta = 0 portfolio resets daily, the 2.5% one accumulates, so the mean
    # drift on day 2 exceeds one day's drift
    assert thr.iloc[2] > d1
    # Calendar resets at the month-end: the first session of February drifts one day
    feb1 = cal[cal.get_loc(pd.Timestamp("2021-01-29")) + 1]
    assert cs.loc[feb1] == pytest.approx(d1)
    w4, c4 = x2.calendar_components(cs)
    E = pd.Timestamp("2021-01-29")
    i = cal.get_loc(E)
    assert (w4.iloc[i - 5:i] == -1.0).all() and w4.iloc[i] == 0.0 and w4.iloc[i - 6] == 0.0
    assert c4.loc[E] == 1.0 and c4.drop(month_end_sessions(cal)).abs().sum() == 0.0


# ----------------------------------------------------------------------------- pipeline
def _spec(mod, data):
    w = P.pnl_window(pd.Timestamp(mod.SPEC.first_dec), data["cal"])
    return dataclasses.replace(mod.SPEC, T_declared=len(w))


def test_x3_pipeline_fit_then_holdout_reproduces_fit_rows(fast):
    d = _data("fit")
    spec = _spec(x3, d)
    out = runner.evaluate_fit(spec, 2, d)
    assert out["window"][0] == "2002-09-04" or out["window"][0].startswith("2002-09")
    for k in ("stage0b", "stage1", "stage2", "stage3", "stage4", "stage5", "reported", "fit_verdict"):
        assert k in out
    assert out["stage0b"]["k"] > 0 and out["stage3"]["shift3_decides"] is False
    assert len(out["stage4"]["regressions"]) == 2
    assert out["stage4"]["regressions"][1]["start"] >= "2007-04-12"
    ser = out["_series"]
    assert ser.index.max() < P.HOLDOUT_START
    full = _data("2026-09-30")
    h = runner.evaluate_holdout(spec, out, ser, full)     # raises if fit rows differ
    assert h["T"] > 0 and h["stage7"]["applies"] == out["fit_verdict"].startswith("PASS")


def test_x2_pipeline_runs_with_its_control(fast, monkeypatch):
    d = _data("fit")
    win = d["cal"][(d["cal"] >= pd.Timestamp(x2.BIL_FIRST)) & (d["cal"] <= P.FIT_END)]
    monkeypatch.setattr(x2, "CONTROL_T", len(win))
    out = runner.evaluate_fit(_spec(x2, d), 3, d)
    assert out["stage2"]["window_T"] == len(win)
    assert "mid_month_placebo_window" in out["reported"]
    assert str(out["reported"]["corr_with_x3_daily"]).startswith("pending")


def test_first_failing_rule_names_the_verdict(fast):
    d = _data("fit")
    out = runner.evaluate_fit(_spec(x3, d), 2, d)
    order = ["stage1", "stage2", "stage3", "stage4", "stage5"]
    first_fail = next((s for s in order if not out[s]["pass_"]), None)
    if first_fail is None:
        assert out["fit_verdict"].startswith("PASS")
    else:
        assert f"stage {first_fail[-1]}" in out["fit_verdict"]


def test_x1_placebo_refuses_to_score_a_fund_before_it_existed(fast):
    """X1's later rows hold BKLN and CWB. A block shuffle moves them onto 2008
    dates when neither had a return. The protocol does not say what that earns,
    so the run raises instead of choosing (question to the team lead)."""
    d = _data("fit")
    with pytest.raises(P.ProtocolError, match="no return"):
        runner.evaluate_fit(_spec(x1, d), 1, d)


def test_counter_guard_reads_the_committed_table():
    assert runner.counter_value() >= 0


def test_x1_everything_but_the_placebo_runs(fast, monkeypatch):
    """With the placebo stubbed, X1's other stages and extras (TSH, LOO, the 21
    refresh offsets, R-LONG) run end to end: the raise above is the placebo's."""
    monkeypatch.setattr(P, "placebo", lambda *a, **k: dict(p95=0.0, pass_=True, stub=True))
    d = _data("fit")
    out = runner.evaluate_fit(_spec(x1, d), 1, d)
    assert out["first_decision"] == "2008-04-30"
    assert set(out["stage2"]["beats"]) == {"gross", "net5", "net15", "net30"}
    rep = out["reported"]
    assert len(rep["leave_one_out"]["by_name"]) == 9 and len(rep["refresh_offsets_21"]["all"]) == 21
    assert "LONG" in rep["r_long"]["betas"]
    assert out["stage3"]["shift3_decides"] is True


def test_tsmom_name_starting_on_its_windows_first_session_is_not_shorted():
    """A fund whose first return is exactly the first session after E_{m-12}
    (PFF: 2007-04-02) is eligible at E_m with a full window. Its 12-month return
    must be the sum of its returns, not NaN -- NaN >= 0 is False and would short
    it with no data behind the sign (the bug this test was written against)."""
    cal = pd.bdate_range("2006-01-02", "2008-06-30")
    Rx = pd.DataFrame({"OLD": 0.0005, "NEW": 0.0005}, index=cal)
    first = pd.Timestamp("2007-04-02")                    # first session after 2007-03-30
    Rx.loc[Rx.index < first, "NEW"] = np.nan
    Rx = Rx + np.random.default_rng(2).normal(0, 1e-5, Rx.shape) * Rx.notna()
    T = tsmom.targets(Rx, ["OLD", "NEW"], pd.Timestamp("2007-12-31"))
    E = pd.Timestamp("2008-03-31")
    assert T.loc[E, "NEW"] > 0                            # up-trending, so long
    assert T.loc[pd.Timestamp("2008-02-29"), "NEW"] == 0.0   # not yet a full window


def test_preflight_halts_before_stage0b_on_dates_alone():
    """The zero-trial preflight: the declared first decision is re-derived from the
    breadth rule; X1/X4 halt on open question 2 while it is unruled; X2 and X3
    pass. Nothing here builds a position or a P&L."""
    d = _data("fit")
    pf3 = runner.preflight(_spec(x3, d), d)
    assert pf3["first_decision"] == "2002-08-30" and pf3["late_names"] == []
    with pytest.raises(P.ProtocolError, match="open question 2"):
        runner.preflight(_spec(x1, d), d)
    wrong = dataclasses.replace(_spec(x1, d), first_dec="2008-05-30")
    with pytest.raises(P.ProtocolError, match="breadth rule"):
        runner.preflight(wrong, d)


def test_x4_pipeline_with_placebo_stubbed(fast, monkeypatch):
    from scripts.xasset import x4_multi_trend as x4
    monkeypatch.setattr(P, "placebo", lambda *a, **k: dict(p95=0.0, pass_=True, stub=True))
    d = _data("fit")
    out = runner.evaluate_fit(_spec(x4, d), 4, d)
    assert out["first_decision"] == "2005-11-30"
    regs = out["stage4"]["regressions"]
    assert len(regs) == 2 and len(regs[1]["betas"]) == 8 and regs[0]["start"] >= "2006-02-06"
    assert set(out["reported"]["asset_class_rows"]["rows"]) == {"credit_and_rates", "equity", "commodity"}


def test_run_refuses_nan_positions():
    idx = pd.bdate_range("2021-01-04", periods=5)
    H = pd.DataFrame({"A": [1.0, np.nan, 1.0, 1.0, 1.0]}, index=idx)
    with pytest.raises(P.ProtocolError, match="NaN"):
        P.run(H, pd.DataFrame({"A": 0.001}, index=idx), "t")
