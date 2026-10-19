"""The merger-arb v2 feasibility rules (`scripts/events/merger_arb_v2_feasibility.py`), on synthetic inputs.

WHY THESE TESTS
---------------
Every number in `results/events/MERGER_ARB_V2_2026-10-19.md` comes from a
few rules on dates, fees and published test statistics. Each way they could go
wrong silently has a test:

  * `announcement_dates`: the announcement document's date is used only inside
    the census's own search window [d0 - 30d, d0 + 10d]; otherwise d0, labelled
    an upper bound. A doc_date outside the window is a different filing.
  * `exits`: a completion after the administrative censor (2022-12-30) is NOT
    seen (the deal is open at the censor), so no 2023+ date enters a fit table;
    bracket A exits a failed deal at its last anchor, bracket B at 52 weeks.
  * `completion_hazard`: a censored or failed deal is at risk in its exit week
    and never counted as a completion (checked to fail against a hazard that
    counts every exit as an event).
  * `window_spells` / `leg_turnover`: a completion inside a window is a FREE
    exit (cash paid, or conversion closes the short), a window end or failure is
    PAID, a position open at the censor is neither; a deal gone before its
    window opens has no spell.
  * the power arithmetic is the XASSET slate's (`slate_feasibility`), and the
    IR implied by a one-sided p is z / sqrt(years).
  * the borrow convention is fee x days / 360 on 102%.
  * `assert_fit_only` raises on any 2023+ date.
  * `pending_by_window` refuses an ambiguous census lookup.
Synthetic inputs test the code, not the market. No network: the root conftest blocks it.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from scripts.events import merger_arb_v2_feasibility as m

T = pd.Timestamp


def _deals(rows):
    d = pd.DataFrame(rows)
    for c in ("d0", "a1", "delist_date", "doc_date"):
        d[c] = pd.to_datetime(d[c])
    return d


def test_announcement_date_uses_document_only_inside_the_census_window():
    d = _deals([
        {"d0": "2015-03-01", "doc_date": "2015-02-10", "doc_source": "8-K 1.01", "a1": "2015-04-01", "delist_date": None},
        {"d0": "2015-03-01", "doc_date": "2014-12-01", "doc_source": "8-K 1.01 (wide)", "a1": "2015-04-01", "delist_date": None},
        {"d0": "2015-03-01", "doc_date": None, "doc_source": None, "a1": "2015-04-01", "delist_date": None},
    ])
    ann, basis = m.announcement_dates(d)
    assert ann.tolist() == [T("2015-02-10"), T("2015-03-01"), T("2015-03-01")]
    assert basis.tolist() == ["document", "d0_upper_bound", "d0_upper_bound"]


def _exit_frame():
    d = _deals([
        # completes inside the fit window
        {"ann": "2015-01-05", "d0": "2015-01-05", "doc_date": None, "a1": "2015-03-01", "completed": True, "delist_date": "2015-05-04"},
        # completes, but only after the censor: must be open at the censor
        {"ann": "2022-10-03", "d0": "2022-10-03", "doc_date": None, "a1": "2022-11-01", "completed": True, "delist_date": "2023-02-01"},
        # never completes
        {"ann": "2016-01-04", "d0": "2016-01-04", "doc_date": None, "a1": "2016-04-01", "completed": False, "delist_date": None},
    ])
    d["ann"] = pd.to_datetime(d["ann"])
    return d


def test_exits_never_see_a_completion_after_the_censor():
    d = _exit_frame()
    a = m.exits(d, "A")
    assert a["kind"].tolist() == ["complete", "admin", "fail"]
    assert a["exit"].tolist() == [T("2015-05-04"), m.ADMIN_CENSOR, T("2016-04-01")]
    b = m.exits(d, "B")
    assert b["kind"].tolist() == ["complete", "admin", "fail"]
    assert b["exit"].iloc[2] == T("2016-01-04") + pd.Timedelta(days=7 * m.MAX_WEEK)
    assert (a["exit"] < m.HOLDOUT_START).all() and (b["exit"] < m.HOLDOUT_START).all()
    with pytest.raises(ValueError):
        m.exits(d, "C")


def test_completion_hazard_counts_only_completions():
    ann = pd.Series([T("2015-01-05")] * 4)
    ex = pd.Series([ann[0] + pd.Timedelta(days=d) for d in (8, 10, 15, 22)])   # weeks 2, 2, 3, 4
    kind = pd.Series(["complete", "complete", "fail", "complete"])
    h = m.completion_hazard(ann, ex, kind, max_week=5).set_index("week")
    assert h.loc[1, "at_risk"] == 4 and h.loc[1, "completions"] == 0
    assert h.loc[2, "at_risk"] == 4 and h.loc[2, "hazard"] == 0.5
    assert h.loc[3, "at_risk"] == 2 and h.loc[3, "completions"] == 0     # the failure is censored, not an event
    assert h.loc[4, "at_risk"] == 1 and h.loc[4, "hazard"] == 1.0
    assert h.loc[5, "at_risk"] == 0 and np.isnan(h.loc[5, "hazard"])
    # the wrong rule (every exit an event) would put a completion in week 3
    wrong = m.completion_hazard(ann, ex, pd.Series(["complete"] * 4), max_week=5).set_index("week")
    assert wrong.loc[3, "completions"] == 1 and h.loc[3, "completions"] != wrong.loc[3, "completions"]


def test_hazard_rejects_an_exit_before_its_announcement():
    with pytest.raises(ValueError):
        m.completion_hazard(pd.Series([T("2015-01-05")]), pd.Series([T("2015-01-01")]), pd.Series(["complete"]))


def test_window_spells_mark_paid_and_free_exits():
    ann = pd.Series([T("2015-01-05")] * 4 + [T("2022-12-01")])
    days = pd.to_timedelta
    ex = pd.Series([
        ann[0] + days(13 * 7 + 2, unit="D"),        # completes in week 14: free
        ann[0] + days(200 * 7, unit="D"),           # outlives the window: paid at the window end
        ann[0] + days(20 * 7, unit="D"),            # fails in week 21: paid
        ann[0] + days(5 * 7, unit="D"),             # completes before week 12: no spell
        m.ADMIN_CENSOR,                             # open at the censor: no exit counted
    ])
    kind = pd.Series(["complete", "admin", "fail", "complete", "admin"])
    sp = m.window_spells(ann, ex, kind, 1, 35)
    assert len(sp) == 5
    sp_hi = m.window_spells(ann, ex, kind, 12, 35)
    assert len(sp_hi) == 3                          # the week-6 completion and the late deal have no High spell
    assert sp_hi["paid_exit"].tolist() == [False, True, True]
    assert sp_hi["end"].iloc[1] == ann[0] + days(35 * 7, unit="D")


def test_leg_turnover_arithmetic():
    sp = pd.DataFrame({"entry": [T("2015-01-01"), T("2015-07-01")],
                       "end": [T("2015-04-01"), T("2015-10-01")],
                       "paid_exit": [True, False]})
    t = m.leg_turnover(sp, start=T("2015-01-01"), stop=T("2016-01-01"))
    years = 365 / m.CAL_DAYS_PER_YEAR
    assert t["positions"] == 2 and t["paid_exits"] == 1 and t["free_exits"] == 1
    assert math.isclose(t["avg_concurrent"], (90 + 92) / 365)
    assert math.isclose(t["paid_trades_per_year"], 3 / years)
    assert math.isclose(t["turnover_per_unit_gross_per_year"], (3 / years) / ((90 + 92) / 365))
    assert math.isclose(t["cost_drag_bp_per_year_at_15bp"], 15 * t["turnover_per_unit_gross_per_year"])


def test_power_inputs_and_shared_arithmetic():
    from statistics import NormalDist
    from scripts.xasset import slate_feasibility as sf
    p = 1 - NormalDist().cdf(2.0)
    assert math.isclose(m.ir_from_one_sided_p(p, 4.0), 1.0, rel_tol=1e-9)
    with pytest.raises(ValueError):
        m.ir_from_one_sided_p(0.0, 4.0)
    assert m.MCLEAN_PONTIFF_KEEP == sf.MCLEAN_PONTIFF_KEEP
    # independent legs: t = 0.0112 / sqrt(0.0024^2 + 0.0021^2)
    ir = m.ir_from_leg_alphas((0.0113, 0.0024), (0.0001, 0.0021), 0.0, 41.0)
    assert math.isclose(ir, 0.0112 / math.hypot(0.0024, 0.0021) / math.sqrt(41.0))
    keys = [k for k, *_ in m.published_irs()]
    assert len(keys) == len(set(keys)) == len(m.GS_TESTS) + len(m.GS_SMALL_RHO)


def test_borrow_cost_convention():
    # 3.6%/yr for 360 days on 102% collateral = 367.2bp
    assert math.isclose(m.borrow_cost_bp(3.6, 360.0), 367.2)


def test_assert_fit_only_raises_on_the_holdout():
    m.assert_fit_only(pd.Series([T("2022-12-30")]), "ok")
    with pytest.raises(AssertionError):
        m.assert_fit_only(pd.Series([T("2022-12-30"), T("2023-01-03")]), "bad")


def test_pending_lookup_refuses_ambiguous_census_keys(tmp_path):
    deals = pd.DataFrame({"target_cik": [1, 1], "d0": [T("2026-01-02")] * 2, "ann": [T("2026-01-01")] * 2})
    pend = pd.DataFrame({"target_cik": [1], "d0": ["2026-01-02"], "final_class": ["cash"], "tender": [False],
                         "acquirer_ticker_today": [None], "tgt_alp_shortable": [True], "tgt_ibkr_fee_pct": [0.4],
                         "tgt_adv_usd": [1e6], "acq_alp_shortable": [None], "acq_ibkr_fee_pct": [None],
                         "stale": [False]})
    f = tmp_path / "pending.csv"
    pend.to_csv(f, index=False)
    with pytest.raises(ValueError):
        m.pending_by_window(deals, path=f, asof=T("2026-03-01"))
    ok = m.pending_by_window(deals.iloc[:1], path=f, asof=T("2026-03-01"))
    assert ok["ann_basis"].tolist() == ["census"] and ok["week"].iloc[0] == (59 // 7 + 1)
    assert ok["window"].iloc[0] == "low1"
