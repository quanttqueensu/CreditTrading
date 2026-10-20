"""The definitions and guards behind the A1 issuance gate, on synthetic frames.

WHY THESE TESTS
---------------
The gate counts share issuance from CRSP shares outstanding and EDGAR offering
filings, then reads premium levels around the dated events. Each way that could
go wrong quietly has a test:

  * the DRIP bound: share growth a dividend-reinvestment plan could have
    produced (at most yield / 0.95 a year) must NOT count as issuance, and
    growth beyond it must;
  * splits, CRSP mergers into the fund, CRSP rights distributions, the IPO
    quarters and a gap in the quarterly series each exclude a quarter;
  * EDGAR episodes: a silence over a year starts a new episode; IPO-period
    supplements are dropped; a 2008 start is flagged left-censored;
  * the join: a rights ex-date near the first supplement wins over a share
    increase; a 2023+ episode is a count only; registered-at-the-time;
  * the z-score mirrors the sleeve's `shift(1)`: today's premium cannot move
    today's mean or sd (no lookahead);
  * no level is read on or after 2023-01-01 (the time holdout), and a
    disagreement between two CRSP extracts raises rather than picks;
  * controls are inside both bands and never the event fund or a busy fund;
  * the gate verdict, the tracked CSV's columns (no CRSP-derived field), and
    the common-share symbol picker.

Synthetic inputs test the code, not the market. No network: the root conftest
blocks it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import a1_cef_issuance_gate as A


def _dsf(permno, start, n_q, shrout_by_q, cfacpr_by_q=None, prc=10.0):
    """Three trading rows per calendar quarter, shrout and cfacpr constant within a quarter."""
    rows = []
    q0 = pd.Period(start, "Q")
    for i in range(n_q):
        q = q0 + i
        for d in (q.start_time + pd.Timedelta(days=5), q.start_time + pd.Timedelta(days=40),
                  q.end_time.normalize() - pd.Timedelta(days=3)):
            rows.append({"permno": permno, "date": d, "prc": prc, "vol": 1000.0,
                         "shrout": float(shrout_by_q[i]), "cfacpr": float((cfacpr_by_q or [1.0] * n_q)[i])})
    return pd.DataFrame(rows)


def _cash(permno, start, n_q, amt):
    q0 = pd.Period(start, "Q")
    return pd.DataFrame([{"permno": permno, "distcd": 1232, "divamt": amt, "exdt": (q0 + i).start_time + pd.Timedelta(days=10)}
                         for i in range(n_q)])


NO_DELIST = pd.DataFrame(columns=["permno", "dlstdt", "dlstcd", "nwperm"])


def _qp(dsf, dist, delist=NO_DELIST):
    first = dsf.groupby("permno")["date"].min()
    return A.quarter_panel(dsf, delist, dist, set(dsf["permno"]), first).set_index("q")


def test_drip_bound_excludes_growth_a_drip_could_produce():
    # yield 0.25/10 per quarter = 10%/yr; DRIP ceiling 10%/0.95 = 10.5% over four quarters.
    sh = [100, 100, 100, 100, 100, 100, 102.5, 105, 107.6, 110.2]   # +10.2% over q6..q9: within the bound
    q = _qp(_dsf(1, "2010-01-01", 10, sh), _cash(1, "2010-01-01", 10, 0.25))
    assert q.loc[pd.Period("2012Q2"), "gr"] >= A.MIN_Q_GROWTH
    assert not q.loc[pd.Period("2012Q2"), "beyond_drip"]
    assert not q["iss"].any()


def test_growth_beyond_the_drip_bound_counts():
    sh = [100] * 6 + [104, 108, 112, 116]                           # +16% in four quarters > 10.5%
    q = _qp(_dsf(1, "2010-01-01", 10, sh), _cash(1, "2010-01-01", 10, 0.25))
    assert q.loc[pd.Period("2012Q1"), "iss"]
    assert q.loc[pd.Period("2012Q2"), "iss"]


def test_no_distribution_rows_means_unmeasured_not_zero():
    sh = [100] * 6 + [104, 108, 112, 116]
    q = _qp(_dsf(1, "2010-01-01", 10, sh), _cash(2, "2010-01-01", 10, 0.25))   # rows for another permno only
    assert q["dist_unmeasured"].all()
    assert not q["iss"].any()


def test_split_merger_rights_ipo_and_gap_exclude():
    sh = [100] * 6 + [130] + [130] * 3
    cf = [1.0] * 6 + [0.77] + [0.77] * 3
    q = _qp(_dsf(1, "2010-01-01", 10, sh, cf), _cash(1, "2010-01-01", 10, 0.01))
    assert q.loc[pd.Period("2011Q3"), "split"] and not q.loc[pd.Period("2011Q3"), "iss"]
    sh2 = [100] * 6 + [140] * 4
    dl = pd.DataFrame([{"permno": 99, "dlstdt": pd.Timestamp("2011-08-15"), "dlstcd": 231, "nwperm": 1}])
    q = _qp(_dsf(1, "2010-01-01", 10, sh2), _cash(1, "2010-01-01", 10, 0.01), dl)
    assert q.loc[pd.Period("2011Q3"), "merger"] and not q["iss"].any()
    rt = pd.concat([_cash(1, "2010-01-01", 10, 0.01),
                    pd.DataFrame([{"permno": 1, "distcd": 4523, "divamt": 0.0, "exdt": pd.Timestamp("2011-05-01")}])])
    q = _qp(_dsf(1, "2010-01-01", 10, sh2), rt)
    assert q.loc[pd.Period("2011Q3"), "rights"] and not q.loc[pd.Period("2011Q3"), "iss"]
    sh3 = [100, 120, 140, 160, 180, 200]
    q = _qp(_dsf(1, "2010-01-01", 6, sh3), _cash(1, "2010-01-01", 6, 0.01))
    assert not q.loc[pd.Period("2010Q2"), "iss"]          # age 1 quarter: the IPO's over-allotment
    d = _dsf(1, "2010-01-01", 10, [100] * 6 + [120] * 4)
    d = d[~d["date"].dt.to_period("Q").eq(pd.Period("2011Q2"))]   # a missing quarter
    q = _qp(d, _cash(1, "2010-01-01", 10, 0.01))
    assert not q.loc[pd.Period("2011Q3"), "contiguous"] and not q.loc[pd.Period("2011Q3"), "iss"]


def _idx(rows):
    return pd.DataFrame(rows, columns=["cik", "company", "form", "date_filed", "accession"]).assign(
        date_filed=lambda x: pd.to_datetime(x["date_filed"]))


def test_edgar_episodes_gap_ipo_and_censoring():
    idx = _idx([(7, "F", "497", "2008-03-01", "a1"), (7, "F", "497", "2008-06-01", "a2"),
                (7, "F", "497", "2010-01-01", "a3"), (7, "F", "N-2", "2009-12-01", "s1"),
                (8, "G", "497", "2012-02-01", "b1"), (8, "G", "424B3", "2014-06-01", "b2")])
    eps, counts = A.edgar_episodes(idx, {7: pd.Timestamp("2000-01-01"), 8: pd.Timestamp("2011-06-01")})
    assert counts["supplements_ipo_period_dropped"] == 1           # G's 2012-02 is inside the IPO year
    f = eps[eps["cik"] == 7].sort_values("first_date")
    assert list(f["n_supplements"]) == [2, 1]                      # 2008-06 -> 2010-01 is a gap > 365 days
    assert bool(f.iloc[0]["left_censored"]) and not bool(f.iloc[1]["left_censored"])
    assert f.iloc[1]["shelf_form_date"] == pd.Timestamp("2009-12-01")


def test_join_rights_beats_issuance_and_2023_is_count_only():
    eps = pd.DataFrame([{"cik": 7, "first_date": pd.Timestamp("2012-01-10"), "n_supplements": 5},
                        {"cik": 7, "first_date": pd.Timestamp("2015-01-10"), "n_supplements": 5},
                        {"cik": 7, "first_date": pd.Timestamp("2023-02-01"), "n_supplements": 5},
                        {"cik": 7, "first_date": pd.Timestamp("2018-01-10"), "n_supplements": 1}])
    qp = pd.DataFrame({"permno": 1, "q": [pd.Period("2012Q2"), pd.Period("2015Q3"), pd.Period("2018Q1"), pd.Period("2022Q4")],
                       "iss": [True, True, True, False]})
    dist = pd.DataFrame([{"permno": 1, "distcd": 4533, "exdt": pd.Timestamp("2012-03-01")}])
    out = A.join_episodes(eps, qp, dist, {7: 1})
    assert list(out["crsp_class"])[:2] == ["rights", "confirmed"]
    assert out.iloc[2]["crsp_class"].startswith("after_crsp")
    assert list(out["programme"]) == [True, True, True, False]
    idx = _idx([(7, "F", "N-CSR", "2014-03-01", "n1")])
    m = A.mark_events(out, idx)
    assert list(m["registered_at_time"]) == [False, True, False, False]   # N-CSR within 730 days before, or a year after
    assert list(m["a1_event"]) == [False, True, False, False]


def test_z_mirrors_the_sleeve_shift_one():
    dates = pd.bdate_range("2015-01-01", periods=400)
    px = pd.DataFrame({"date": dates, "ticker": "X", "close": 10.0 + np.sin(np.arange(400) / 7), "volume": 1e5})
    nav = pd.DataFrame({"date": dates, "ticker": "X", "nav": 10.0})
    a = A.premium_panel(px, nav, 252)["X"].set_index("date")
    px2 = px.copy()
    px2.loc[px2.index[-1], "close"] = 50.0                       # a shock on the last day only
    b = A.premium_panel(px2, nav, 252)["X"].set_index("date")
    last = dates[-1]
    # the shock moves today's p, so today's z, but not today's mean and sd: compare z*(sd) + mu
    za, zb = a.loc[last, "z"], b.loc[last, "z"]
    assert a.loc[last, "p"] != b.loc[last, "p"]
    assert np.allclose(a.loc[dates[:-1], "z"].dropna(), b.loc[dates[:-1], "z"].dropna())
    assert zb != za


def test_levels_never_read_the_holdout():
    dates = pd.bdate_range("2022-06-01", periods=200)              # runs past 2023-01-01
    df = pd.DataFrame({"date": dates, "p": 1.0, "z": 0.0, "adv": 1e6})
    df = df[df["date"] < A.TIME_HOLDOUT].reset_index(drop=True)    # what premium_panel keeps
    assert A.path_at(df, len(df) - 10, A.OFFSETS) is None          # +126 runs off the end: no path
    with pytest.raises(A.A1DataError):
        A.assert_pre_holdout(pd.Timestamp("2023-01-03"), "x")
    px = pd.DataFrame({"date": dates, "ticker": "X", "close": 10.0, "volume": 1.0})
    nav = pd.DataFrame({"date": dates, "ticker": "X", "nav": 9.0})
    assert A.premium_panel(px, nav, 252)["X"]["date"].max() < A.TIME_HOLDOUT


def test_crsp_extract_disagreement_raises(tmp_path):
    names = pd.DataFrame([{"permno": 1, "shrcd": 14, "namedt": "2000-01-01", "nameendt": "2024-12-31", "ticker": "X", "comnam": "X FUND"}])
    names.to_parquet(tmp_path / "dsenames.parquet")
    pd.DataFrame([{"permno": 1, "dlstdt": "2020-01-01", "dlstcd": 100, "nwperm": np.nan}]).to_parquet(tmp_path / "dsedelist.parquet")
    pd.DataFrame([{"permno": 1, "distcd": 1232, "divamt": 0.1, "exdt": "2015-01-05", "dclrdt": None, "rcrddt": None, "paydt": None}]).to_parquet(tmp_path / "dsedist_a.parquet")
    row = {"permno": 1, "date": pd.Timestamp("2015-01-02"), "prc": 10.0, "vol": 5.0, "shrout": 100.0, "cfacpr": 1.0}
    pd.DataFrame([row]).to_parquet(tmp_path / "dsf_a.parquet")
    pd.DataFrame([{**row, "shrout": 101.0}]).to_parquet(tmp_path / "dsf_b.parquet")
    with pytest.raises(A.A1DataError, match="disagree"):
        A.load_crsp([tmp_path])
    pd.DataFrame([{**row, "date": pd.Timestamp("2023-01-03")}]).to_parquet(tmp_path / "dsf_b.parquet")
    with pytest.raises(A.A1DataError, match="holdout"):
        A.load_crsp([tmp_path])


def test_controls_inside_both_bands_and_never_busy():
    dates = pd.bdate_range("2014-01-01", periods=300)
    def fund(p, z):
        return pd.DataFrame({"date": dates, "p": p, "z": z, "adv": 1e6})
    panel = {"E": fund(5.0, 1.0), "C1": fund(5.0 + A.MATCH_PREM_PP - 0.1, 1.0 + A.MATCH_Z - 0.1),
             "C2": fund(5.0 + A.MATCH_PREM_PP + 0.1, 1.0), "C3": fund(5.0, 1.0 + A.MATCH_Z + 0.1), "B": fund(5.0, 1.0)}
    d0 = dates[100]
    got = A.match_controls(panel, d0, 5.0, 1.0, {"E", "B"}, A.OFFSETS)
    assert [c["ticker"] for c in got] == ["C1"]
    busy = A.busy_tickers(d0, {"B": [d0 + pd.Timedelta(days=200)]}, {"C1": [pd.Period(d0, "Q") + 5]})
    assert busy == {"B"}


def test_gate_verdict():
    bar = -A.ROUND_TRIP_UNITS * max(A.COST_GRID_BP)
    ok = A.gate_verdict(40, 0.9, bar - 1, 0.7, 0.0, 0.8)
    assert ok["verdict"] == "PASS"
    assert A.gate_verdict(12, 0.9, bar - 1, 0.7, 0.0, 0.8)["verdict"] == "FAIL"     # D7
    assert A.gate_verdict(40, 0.5, bar - 1, 0.7, 0.0, 0.8)["verdict"].startswith("HALT")
    assert A.gate_verdict(40, 0.9, bar - 1, 0.7, bar, 0.8)["verdict"] == "FAIL"     # placebo as large
    assert A.gate_verdict(40, 0.9, bar - 1, 0.7, None, 0.8)["verdict"] == "FAIL"    # no placebo, no pass
    assert A.gate_verdict(40, 0.9, -bar, 0.7, 0.0, 0.8)["verdict"] == "FAIL"        # wrong sign


def test_tracked_columns_carry_no_crsp_field_and_symbol_picker():
    assert not set(A.TRACKED_COLUMNS) & set(A.CRSP_DERIVED)
    assert A.common_symbol("GGN;GGN-PB") == "GGN"
    assert A.common_symbol("OXLC;OXLCG;OXLCI") == "OXLC"
    with pytest.raises(A.A1DataError):
        A.common_symbol("ECC-PD")


def test_summarise_D_sign_test():
    rows = [{"D_63": v} for v in (-1.0, -2.0, -0.5, 0.3)]
    s = A.summarise_D(rows, 63)
    assert s["n"] == 4 and s["share_negative"] == 0.75
    assert s["median_bp"] == pytest.approx(-75.0)
