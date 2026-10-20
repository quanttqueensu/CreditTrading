"""`scripts/events/mahz_spread_measure.py` on synthetic staged data.

WHY THESE TESTS
---------------
The measurement must decide whether MA-HZ's trial is worth spending without
reading a return. Each way it could go wrong silently has a test:

  * it never reads a return: `MEASURE_COLS` holds none, a frame carrying one is
    refused, and missing staged files raise naming the staging run;
  * the half-spread is (ask - bid) / (ask + bid), and a crossed, zero or missing
    quote is UNQUOTED (NaN), never a number;
  * event weeks: day 0-6 is week 1, the day before is week -1;
  * exits: a CRSP merger delisting completes; a non-merger delisting is an
    observed failure at its date; a completion the census saw after the censor
    leaves the deal open, not failed;
  * ADV is taken strictly BEFORE the decision day (H7): a volume spike on the
    decision day must not move it, and a short history is NaN, not a smaller window;
  * the measured drag is turnover x the mean half-spread of the paid fills, and
    a completion is a free exit;
  * the pre-declared cost and hump readings return the verdict their rules state;
  * the power window starts two sessions after both legs first hold a deal (H1);
  * every committed table is an aggregate: no deal id or permno column.
Synthetic inputs test the code, not the market. No network: the root conftest blocks it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.data import stage_crsp_merger_targets as S
from scripts.events import mahz_spread_measure as M
from scripts.events import merger_arb_v2_feasibility as V

T = pd.Timestamp
CAL = pd.DatetimeIndex(pd.bdate_range("2000-06-01", "2023-01-31"))


def _deals(rows):
    cols = ["deal_id", "universe", "permno", "ann", "a1", "crsp_outcome", "dlstdt", "completed_edgar",
            "delist_date_edgar"]
    d = pd.DataFrame(rows, columns=cols)
    for c in ("ann", "a1", "dlstdt", "delist_date_edgar"):
        d[c] = pd.to_datetime(d[c])
    d["d0"] = d["ann"]
    d["link_status"], d["exchcd_at_d0"], d["rows"] = "linked", 3, 100
    d["fetch_lo"] = d["ann"] - pd.Timedelta(days=S.PRE_PAD_DAYS)
    d["completed_edgar"] = d["completed_edgar"].astype(bool)
    return d


def _px(permno, start, end, hs_bp=50.0, vol=1000.0, prc=20.0):
    dates = pd.bdate_range(start, end)
    mid = 20.0
    half = mid * hs_bp / 1e4
    return pd.DataFrame({"permno": permno, "date": dates, "prc": prc, "bid": mid - half, "ask": mid + half,
                         "vol": vol, "shrout": 1000.0})


# --------------------------------------------------------------------------- no returns
def test_no_return_column_is_ever_read():
    assert not set(M.MEASURE_COLS) & set(S.RETURN_FIELDS)
    with pytest.raises(M.MeasureError, match="return column"):
        M.assert_no_returns(pd.DataFrame({"permno": [1], "ret": [0.01]}))


def test_missing_staged_files_raise_naming_the_staging_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="staging run"):
        M.load_staged(tmp_path)


def test_load_reads_only_the_measure_columns_and_refuses_2023(tmp_path):
    d = _deals([("C1", "CASH_1STEP", 1, "2012-01-02", "2012-03-01", "merger", "2012-06-01", True, "2012-06-01")])
    d.to_csv(tmp_path / S.DEALS_CSV, index=False)
    px = _px(1, "2011-09-01", "2012-06-01").assign(ret=0.0, retx=0.0)
    px.to_parquet(tmp_path / S.DSF_PARQUET, index=False)
    deals, got = M.load_staged(tmp_path)
    assert list(got.columns) == list(M.MEASURE_COLS) and len(deals) == 1
    pd.concat([px, _px(1, "2023-01-03", "2023-01-05").assign(ret=0.0, retx=0.0)]).to_parquet(
        tmp_path / S.DSF_PARQUET, index=False)
    with pytest.raises(AssertionError, match="2023-01-01"):
        M.load_staged(tmp_path)


# --------------------------------------------------------------------------- spreads and weeks
def test_half_spread_and_unquoted_sessions():
    hs = M.half_spread_bp(pd.Series([99.5, 0.0, 10.0, np.nan]), pd.Series([100.5, 1.0, 9.0, 10.0]))
    assert hs.iloc[0] == pytest.approx(50.0)
    assert hs.iloc[1:].isna().all()


def test_signed_event_week():
    ann = pd.Series([T("2012-01-02")] * 6)
    dates = pd.Series(pd.to_datetime(["2012-01-02", "2012-01-08", "2012-01-09", "2012-01-01", "2011-12-26",
                                      "2011-12-25"]))
    assert M.signed_week(ann, dates).tolist() == [1, 1, 2, -1, -1, -2]


def test_window_of_week_follows_the_papers_cash_cutoffs():
    w = pd.Series([-3, 1, 10, 11, 12, 35, 36, 37, 45, 46])
    assert M.window_of_week(w).tolist() == ["pre", "low1", "low1", "gap", "high", "high", "gap", "low2", "low2",
                                            "beyond"]


# --------------------------------------------------------------------------- exits
def test_exits_from_crsp_with_observed_failures_and_late_completions_open():
    d = _deals([
        ("M", "CASH_1STEP", 1, "2012-01-02", "2012-03-01", "merger", "2012-06-01", True, "2012-06-01"),
        ("O", "CASH_1STEP", 2, "2012-01-02", "2012-03-01", "other_delist", "2012-05-01", False, None),
        ("L", "CASH_1STEP", 3, "2022-06-01", "2022-09-01", "none", None, True, "2023-02-01"),
        ("E", "CASH_1STEP", 4, "2012-01-02", "2012-03-01", "none", None, True, "2012-06-01"),
        ("N", "CASH_1STEP", 5, "2012-01-02", "2012-03-01", "none", None, False, None)])
    a = M.crsp_exits(d, "A").set_index(d["deal_id"])
    b = M.crsp_exits(d, "B").set_index(d["deal_id"])
    assert (a.loc["M", "kind"], a.loc["M", "exit"]) == ("complete", T("2012-06-01"))
    assert (a.loc["O", "kind"], a.loc["O", "exit"], a.loc["O", "how"]) == ("fail", T("2012-05-01"), "crsp_other_delist")
    assert (b.loc["O", "kind"], b.loc["O", "exit"]) == ("fail", T("2012-05-01"))
    assert (a.loc["L", "kind"], a.loc["L", "exit"]) == ("admin", V.ADMIN_CENSOR)
    assert a.loc["E", "kind"] == "fail" and a.loc["E", "how"].endswith("edgar_completed_crsp_not")
    assert (a.loc["N", "exit"], b.loc["N", "exit"]) == (T("2012-03-01"), T("2012-01-02") + pd.Timedelta(weeks=52))


# --------------------------------------------------------------------------- ADV, trades, drag
def test_adv_is_strictly_before_the_decision_day_and_never_a_shorter_window():
    px = _px(1, "2012-01-02", "2012-12-31")
    px["vol"] = np.arange(1, len(px) + 1, dtype=float)          # strictly increasing: any shift moves the median
    dec = px["date"].iloc[100]
    b = M.Book(px)
    # rows 37..99 (the 63 sessions before row 100) hold volumes 38..100: median 69, at $20 a share
    assert b.adv(1, dec) == pytest.approx(69.0 * 20.0)
    px.loc[px.index[50], "vol"] = np.nan
    assert np.isnan(M.Book(px).adv(1, dec))                      # a missing volume is not skipped
    short = M.Book(_px(1, "2012-01-02", "2012-03-01"))
    assert np.isnan(short.adv(1, T("2012-03-01")))     # 43 sessions < ADV_SESSIONS


def _one_deal_completing_in_week_20():
    ann = T("2012-01-02")
    d = _deals([("C1", "CASH_1STEP", 1, str(ann.date()), "2012-03-15", "merger",
                 str((ann + pd.Timedelta(weeks=19, days=2)).date()), True, None)])
    d["size_half"], d["era"] = "small", "2010-22"
    return d


def test_measured_drag_is_turnover_times_the_paid_fills_half_spread_and_completion_is_free():
    d = _one_deal_completing_in_week_20()
    px = _px(1, "2011-07-01", "2012-05-31", hs_bp=50.0)
    ex = M.crsp_exits(d, "A")
    book = M.Book(px)
    hi, lo = M.leg_spells(d, ex, "high"), M.leg_spells(d, ex, "low")
    assert len(hi) == 1 and not hi["paid_exit"].iloc[0]          # completion inside High: free
    assert len(lo) == 1 and lo["paid_exit"].iloc[0]              # Low 1 ends before the deal: paid
    t_hi = M.leg_trades(hi, book, CAL, 100_000.0)
    t_lo = M.leg_trades(lo, book, CAL, 100_000.0)
    assert len(t_hi) == 1 and len(t_lo) == 2
    assert (t_lo["fill"] > t_lo["decision"]).all()               # H1: fill the session after the decision
    r = M.turnover_rows(lo, t_lo, T("2010-01-01"), V.ADMIN_CENSOR)
    assert r["hs_mean_bp"] == pytest.approx(50.0, abs=1e-6)
    assert r["measured_drag_bp_per_year"] == pytest.approx(r["turnover_per_unit_gross_per_year"] * 50.0, rel=1e-6)


def test_capacity_fit_is_position_against_5pct_of_prior_adv():
    d = _one_deal_completing_in_week_20()
    px = _px(1, "2011-07-01", "2012-05-31", vol=1000.0)          # ADV = $20k a day; 5% = $1k
    ex = M.crsp_exits(d, "A")
    t = M.leg_trades(M.leg_spells(d, ex, "high"), M.Book(px), CAL, 1_000.0)
    # one deal in the leg: position = capital x scale / 2
    assert t["fits_x1"].iloc[0] == True          # noqa: E712  $500 <= $1,000
    assert t["fits_x10"].iloc[0] == False        # noqa: E712  $5,000 > $1,000


# --------------------------------------------------------------------------- verdicts
def _ls(drag_a, drag_b, q=0.9):
    return pd.DataFrame([{"universe": "CASH_1STEP", "era": M.DECIDING_ERA, "bracket": br, "measured_drag_bp": v,
                          "quoted_share_high": q, "quoted_share_low": q} for br, v in (("A", drag_a), ("B", drag_b))])


def test_cost_verdict_follows_its_declared_rule():
    g = M.published_gross_bp()
    assert g["late"] == pytest.approx((43 + 3) / 2 * 12) and g["full_x0.42"] == pytest.approx(414 * 0.42)
    assert M.cost_verdict(_ls(g["late"] + 1, g["late"] + 50), g)["verdict"] == "D2_PREDICTED"
    assert M.cost_verdict(_ls(g["full_x0.42"] - 1, 10), g)["verdict"] == "COSTS_DO_NOT_DECIDE"
    assert M.cost_verdict(_ls(g["late"] + 1, 10), g)["verdict"] == "MARGINAL"
    assert M.cost_verdict(_ls(500, 500, q=0.4), g)["verdict"] == "UNMEASURED"


def _hazard_deals(weeks, era_start):
    rows = []
    for i, w in enumerate(weeks):
        ann = era_start + pd.Timedelta(days=7 * (i % 50))
        rows.append((f"D{i}", "CASH_1STEP", i, str(ann.date()), str((ann + pd.Timedelta(weeks=60)).date()),
                     "merger", str((ann + pd.Timedelta(days=7 * (w - 1) + 2)).date()), True, None))
    d = _deals(rows)
    d["era"] = M.era_of(d["ann"])
    return d


def test_hump_verdict_holds_for_a_mid_window_hump_and_fails_for_early_completions():
    # FAILS needs deals still at risk through the High weeks (36 complete in week 44), with
    # completions in Low 1 and none in High; if nothing is at risk the reading is UNMEASURED
    early_then_late = [3, 4, 5, 6, 7, 8] * 6 + [44] * 36
    nothing_left = [2, 3, 4, 5, 6, 7, 8, 9] * 6
    for weeks, want in (([13, 14, 15, 16, 17, 18, 19, 20] * 6, "HOLDS"), (early_then_late, "FAILS"),
                        (nothing_left, "UNMEASURED")):
        d = _hazard_deals(weeks, T("2003-01-06"))
        ex = {br: M.crsp_exits(d, br) for br in M.BRACKETS}
        _, hs = M.hazard_tables(d, ex)
        assert M.hump_verdict(hs)["verdict"] == want


def test_power_window_starts_two_sessions_after_both_legs_first_hold_a_deal():
    hi = pd.DataFrame({"entry": [T("2012-03-05")], "end": [T("2012-06-01")], "paid_exit": [False]})
    lo = pd.DataFrame({"entry": [T("2012-03-07")], "end": [T("2012-04-02")], "paid_exit": [True]})
    rows = M.power_rows({"high": hi, "low": lo}, CAL, T("2012-01-01"), "t")
    r = rows[0]
    i = CAL.searchsorted(T("2012-03-07"))
    assert r["first_pnl"] == str(CAL[i + 2].date())
    assert r["sessions"] == int(((CAL >= CAL[i + 2]) & (CAL < V.HOLDOUT_START)).sum())
    assert r["sessions_both_legs"] == int(((CAL >= T("2012-03-07")) & (CAL < T("2012-04-02"))).sum())


# --------------------------------------------------------------------------- end to end
def _universe():
    rows, px = [], []
    k = 0
    for era_start in (T("2004-01-05"), T("2014-01-06")):
        for i in range(40):
            k += 1
            ann = era_start + pd.Timedelta(days=7 * i)
            w = 13 + (i % 8)
            done = ann + pd.Timedelta(weeks=w - 1, days=2)
            out = "merger" if i % 10 else "other_delist"
            end = done if out == "merger" else ann + pd.Timedelta(weeks=20)
            rows.append((f"C{k}", "CASH_1STEP" if i % 9 else "TENDER_CASH", k, str(ann.date()),
                         str((ann + pd.Timedelta(weeks=8)).date()), out, str(end.date()), out == "merger",
                         str(end.date()) if out == "merger" else None))
            px.append(_px(k, ann - pd.Timedelta(days=S.PRE_PAD_DAYS), end, hs_bp=20.0 + i, vol=5000.0 + 100 * i,
                          prc=10.0 + i % 5))
    return _deals(rows), pd.concat(px, ignore_index=True)


def test_measure_end_to_end_writes_aggregates_only():
    deals, px = _universe()
    res = M.measure(deals, px, CAL, 100_000.0)
    for k in ("spread_by_week", "spread_by_window", "quote_coverage", "hazard_weekly", "hazard_summary",
              "turnover", "ls_cost", "capacity", "power"):
        assert len(res[k]), k
        assert not {"deal_id", "permno", "ann", "date"} & set(res[k].columns), k
    assert res["cost_verdict"]["verdict"] in ("D2_PREDICTED", "COSTS_DO_NOT_DECIDE", "MARGINAL", "UNMEASURED")
    assert res["hump_verdict"]["verdict"] in ("HOLDS", "FAILS", "UNMEASURED")
    w = res["spread_by_window"]
    assert (w["hs_median_bp"].dropna() >= 20.0).all() and (w["quoted_share"] == 1.0).all()
    assert set(res["ls_cost"]["era"]) >= {"2001-09", "2010-22", "2001-22"}
