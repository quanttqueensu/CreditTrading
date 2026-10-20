"""`scripts/data/stage_crsp_merger_targets.py` on a fake CRSP source and a fake EDGAR index.

WHY THESE TESTS
---------------
The stage decides which security a deal's prices come from, which delisting ends
it, and which rows a trial will later read. Each way that could go wrong
silently has a test:

  * the TIME HOLDOUT: a source that hands back a 2023 `dsf` or `dsedelist` row
    (dlret is a return) is refused, not filtered;
  * a CRSP table missing a needed column raises, naming it;
  * TARGET -> PERMNO: only a name record in force on d0, on NYSE/AMEX/Nasdaq,
    with a common-stock share code, can link; two companies with the same name
    are `ambiguous`; two share classes of one company are `multi_class`; neither
    is guessed;
  * DELISTINGS: a target with two deals gives its delisting to the later one; a
    delisting after a1 + 730 days ends no deal; code 100 ("still trading") is no
    delisting; a non-merger code is an observed failure; two rows for a permno raise;
  * WINDOWS: at most PRE_SESSIONS rows before the announcement and POST_SESSIONS
    after the end; overlapping windows are stored once; conflicting rows raise;
  * the EXTENSION: before electronic Form 25 a completed target has none, so the
    census's own rule calls it unlisted; the CRSP listing rule keeps it;
  * the writer refuses the live `data/cef/`.
Synthetic inputs test the code, not the market. No network: the root conftest blocks it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.data import stage_crsp_merger_targets as S
from scripts.data.cef_families_common import FamiliesDataError

T = pd.Timestamp


def _names(rows):
    d = pd.DataFrame(rows, columns=["permno", "permco", "namedt", "nameenddt", "shrcd", "exchcd", "comnam", "ticker"])
    d["namedt"], d["nameenddt"] = pd.to_datetime(d["namedt"]), pd.to_datetime(d["nameenddt"])
    return d


NAMES = _names([
    (10001, 501, "2005-01-01", "2012-07-01", 11, 3, "ACME WIDGETS INC", "ACMW"),
    (10002, 502, "2005-01-01", "2024-12-31", 11, 1, "BRAVO HOLDINGS CORP", "BRVO"),
    (10003, 503, "2005-01-01", "2020-01-01", 11, 1, "CHARLIE FOODS INC", "CHF"),
    (10004, 504, "2005-01-01", "2020-01-01", 11, 1, "CHARLIE FOODS INC", "CHFX"),      # a second company, same name
    (10005, 505, "2005-01-01", "2020-01-01", 11, 1, "DELTA MOTORS CORP", "DLTA"),
    (10006, 505, "2005-01-01", "2020-01-01", 11, 1, "DELTA MOTORS CORP", "DLTB"),      # class B of the same company
    (10007, 507, "2005-01-01", "2020-01-01", 14, 1, "ECHO INCOME FUND", "EIF"),        # a closed-end fund
    (10008, 508, "2005-01-01", "2020-01-01", 11, 4, "FOXTROT LABS INC", "FXL"),        # not NYSE/AMEX/Nasdaq
])


def _targets(rows):
    return pd.DataFrame(rows, columns=["target_name", "on"]).assign(on=lambda x: pd.to_datetime(x["on"]))


# --------------------------------------------------------------------------- link
def test_link_needs_a_record_in_force_on_d0_and_refuses_to_guess():
    t = _targets([("ACME WIDGETS INC", "2012-03-01"),    # in force
                  ("ACME WIDGETS INC", "2013-03-01"),    # the record ended 2012-07-01
                  ("CHARLIE FOODS INC", "2012-03-01"),   # two companies
                  ("DELTA MOTORS CORP", "2012-03-01"),   # two classes of one company
                  ("ECHO INCOME FUND", "2012-03-01"),    # share code 14
                  ("FOXTROT LABS INC", "2012-03-01"),    # exchange code 4
                  ("ZULU PARTNERS LP", "2012-03-01"),
                  (None, "2012-03-01")])
    out = S.link_targets(t, NAMES)
    assert out["link_status"].tolist() == ["linked", "no_candidate", "ambiguous", "multi_class", "no_candidate",
                                           "no_candidate", "no_candidate", "no_name"]
    assert out.loc[0, "permno"] == 10001 and out.loc[0, "exchcd_at_d0"] == 3
    assert np.isnan(out.loc[2, "permno"]) and np.isnan(out.loc[3, "permno"])


def test_link_reads_crsp_abbreviations_and_edgar_state_suffixes():
    names = _names([(20001, 601, "2000-01-01", "2010-01-01", 11, 3, "INTL BUSINESS SYSTEMS INC", "IBS"),
                    (20002, 602, "2000-01-01", "2010-01-01", 11, 3, "INTERSTATE BAKERIES CORP", "IBC")])
    out = S.link_targets(_targets([("INTERNATIONAL BUSINESS SYSTEMS INC /DE/", "2004-06-01")]), names)
    assert out.loc[0, "link_status"] == "linked" and out.loc[0, "permno"] == 20001


def test_a_name_record_without_permco_raises():
    bad = NAMES.copy()
    bad.loc[0, "permco"] = np.nan
    with pytest.raises(S.StageError, match="permco"):
        S.prepare_names(bad)


# --------------------------------------------------------------------------- delistings
def _deals(rows):
    d = pd.DataFrame(rows, columns=["deal_id", "permno", "d0", "a1", "ann"])
    for c in ("d0", "a1", "ann"):
        d[c] = pd.to_datetime(d[c])
    return d


def _delist(rows):
    d = pd.DataFrame(rows, columns=["permno", "dlstdt", "dlstcd", "nwperm", "dlamt", "dlpdt", "dlprc", "dlret", "dlretx"])
    d["dlstdt"], d["dlpdt"] = pd.to_datetime(d["dlstdt"]), pd.to_datetime(d["dlpdt"])
    return d


def test_a_delisting_ends_the_latest_deal_before_it_and_only_inside_its_window():
    deals = _deals([("A1", 1, "2004-01-05", "2004-03-01", "2004-01-02"),      # failed: the target was bought later
                    ("A2", 1, "2006-02-01", "2006-04-01", "2006-01-30"),
                    ("B1", 2, "2004-01-05", "2004-03-01", "2004-01-02"),      # delisted four years on: not this deal
                    ("C1", 3, "2004-01-05", "2004-03-01", "2004-01-02"),      # code 100: still trading
                    ("D1", 4, "2004-01-05", "2004-03-01", "2004-01-02")])     # code 560: an observed failure
    dl = _delist([(1, "2006-06-30", 233, 0, 25.0, "2006-07-07", np.nan, 0.01, 0.01),
                  (2, "2008-06-30", 233, 0, 25.0, "2008-07-07", np.nan, 0.01, 0.01),
                  (3, "2004-06-30", 100, 0, np.nan, None, np.nan, np.nan, np.nan),
                  (4, "2004-05-03", 560, 0, np.nan, None, 1.2, -0.3, -0.3)])
    out = S.attribute_delistings(deals, dl).set_index("deal_id")
    assert out.loc["A1", "crsp_outcome"] == "none" and out.loc["A2", "crsp_outcome"] == "merger"
    assert out.loc["A2", "dlstdt"] == T("2006-06-30") and out.loc["A2", "dlamt"] == 25.0
    assert out.loc["B1", "crsp_outcome"] == "none"
    assert out.loc["C1", "crsp_outcome"] == "none"
    assert out.loc["D1", "crsp_outcome"] == "other_delist" and out.loc["D1", "dlstcd"] == 560


def test_two_delisting_rows_for_one_permno_raise():
    dl = _delist([(1, "2006-06-30", 233, 0, 25.0, "2006-07-07", np.nan, 0.0, 0.0),
                  (1, "2007-06-30", 233, 0, 25.0, "2007-07-07", np.nan, 0.0, 0.0)])
    with pytest.raises(S.StageError, match="two rows"):
        S.attribute_delistings(_deals([("A", 1, "2006-01-02", "2006-03-01", "2006-01-02")]), dl)


def test_a_2023_delisting_row_is_refused():
    dl = _delist([(1, "2023-02-01", 233, 0, 25.0, "2023-02-08", np.nan, 0.02, 0.02)])
    with pytest.raises(S.StageError, match="sealed"):
        S.attribute_delistings(_deals([("A", 1, "2022-06-01", "2022-08-01", "2022-06-01")]), dl)


# --------------------------------------------------------------------------- windows
def test_window_end_is_the_delisting_else_52_weeks_capped_at_the_last_fit_day():
    d = _deals([("A", 1, "2010-01-04", "2010-03-01", "2010-01-04"), ("B", 2, "2010-01-04", "2010-03-01", "2010-01-04"),
                ("C", 3, "2022-06-01", "2022-08-01", "2022-06-01")])
    d["crsp_outcome"] = ["merger", "none", "none"]
    d["dlstdt"] = pd.to_datetime(["2010-05-03", None, None])
    w = S.deal_windows(d).set_index("deal_id")
    assert w.loc["A", "end"] == T("2010-05-03")
    assert w.loc["B", "end"] == T("2010-01-04") + pd.Timedelta(weeks=52)
    assert w.loc["C", "end"] == S.LAST_FIT_DAY and w.loc["C", "fetch_hi"] == S.LAST_FIT_DAY
    assert (w["fetch_lo"] == w["ann"] - pd.Timedelta(days=S.PRE_PAD_DAYS)).all()


def _dsf(permno, start, end, bid=9.95, ask=10.05):
    dates = pd.bdate_range(start, end)
    n = len(dates)
    return pd.DataFrame({"permno": permno, "date": dates, "prc": 10.0, "bid": bid, "ask": ask, "bidlo": 9.9,
                         "askhi": 10.1, "openprc": 10.0, "vol": 1000.0, "numtrd": 10, "ret": 0.0, "retx": 0.0,
                         "shrout": 5000.0, "cfacpr": 1.0, "cfacshr": 1.0}, index=range(n))


def test_trim_keeps_63_sessions_before_and_10_after_and_stores_shared_rows_once():
    d = _deals([("A", 1, "2010-06-01", "2010-08-01", "2010-06-01"), ("B", 1, "2010-07-01", "2010-09-01", "2010-07-01")])
    d["crsp_outcome"] = ["none", "merger"]
    d["dlstdt"] = pd.to_datetime([None, "2010-10-01"])
    w = S.deal_windows(d)
    rows, out = S.trim_windows(w, S.unique_rows(_dsf(1, "2009-01-01", "2012-12-31")))
    out = out.set_index("deal_id")
    assert out["pre_sessions"].tolist() == [S.PRE_SESSIONS, S.PRE_SESSIONS]
    assert out.loc["A", "post_sessions"] == S.POST_SESSIONS and out.loc["B", "post_sessions"] == S.POST_SESSIONS
    assert not rows.duplicated(["permno", "date"]).any()
    pre_a = rows[rows["date"] < T("2010-06-01")]
    assert len(pre_a) == S.PRE_SESSIONS


def test_a_short_history_is_counted_not_filled():
    d = _deals([("A", 1, "2010-06-01", "2010-08-01", "2010-06-01")])
    d["crsp_outcome"], d["dlstdt"] = ["none"], pd.to_datetime([None])
    _, out = S.trim_windows(S.deal_windows(d), S.unique_rows(_dsf(1, "2010-05-03", "2011-12-31")))
    assert 0 < out["pre_sessions"].iloc[0] < S.PRE_SESSIONS


def test_conflicting_rows_for_one_permno_date_raise():
    x = _dsf(1, "2010-01-04", "2010-01-08")
    y = x.iloc[[0]].assign(prc=11.0)
    with pytest.raises(S.StageError, match="two different rows"):
        S.unique_rows(pd.concat([x, y]))


def test_the_pad_cannot_bind():
    assert S.PRE_PAD_DAYS >= S.PRE_SESSIONS / 5 * 7 + 21


def test_window_constants_are_the_censuss():
    from scripts.events import merger_arb_feasibility as F
    assert S.PRE_SESSIONS == F.ADV_SESSIONS
    assert S.COMPLETE_DAYS == F.COMPLETE_DAYS
    assert S.LINK_SHRCD == (10, 11, 12, 18)


# --------------------------------------------------------------------------- the stage, end to end
class FakeSource:
    """The R2Source interface over frames. `honest=False` ignores the date bound, as a
    broken mirror or a mistyped query would."""

    def __init__(self, names, delist, dsf, honest=True, drop_col=None):
        self._n, self._dl, self._dsf, self.honest, self.drop_col = names, delist, dsf, honest, drop_col

    def columns(self, table):
        cols = {"stocknames": S.NAME_COLS, "dsedelist": S.DELIST_COLS, "dsf": S.DSF_COLS}[table]
        return [c for c in cols if c != self.drop_col]

    def names(self):
        return self._n

    def delistings(self, permnos):
        x = self._dl[self._dl["permno"].isin(permnos)]
        return x[x["dlstdt"] <= S.LAST_FIT_DAY] if self.honest else x

    def dsf(self, windows):
        out = []
        for _, w in windows.iterrows():
            x = self._dsf[(self._dsf["permno"] == w["permno"]) & (self._dsf["date"] >= w["fetch_lo"])
                          & ((self._dsf["date"] <= w["fetch_hi"]) if self.honest else True)]
            out.append(x)
        x = pd.concat(out)
        return x[x["date"] <= S.LAST_FIT_DAY] if self.honest else x


def _census():
    rows = [
        # deal, target, d0, a1, ann, universe, completed, delist_date
        (1, "ACME WIDGETS INC", "2012-03-01", "2012-05-01", "2012-02-20", "CASH_1STEP", True, "2012-07-02"),
        (2, "BRAVO HOLDINGS CORP", "2022-06-01", "2022-09-01", "2022-05-25", "CASH_1STEP", True, "2023-03-01"),
        (3, "CHARLIE FOODS INC", "2012-03-01", "2012-05-01", "2012-03-01", "TENDER_CASH", True, "2012-06-01"),
        (4, "DELTA MOTORS CORP", "2012-03-01", "2012-05-01", "2012-03-01", "STOCK_1STEP", True, "2012-08-01"),
    ]
    c = pd.DataFrame(rows, columns=["deal", "target_name", "d0", "a1", "ann", "universe", "completed", "delist_date"])
    for k in ("d0", "a1", "ann", "delist_date"):
        c[k] = pd.to_datetime(c[k])
    c = c.assign(target_cik=c["deal"] * 100, doc_date=c["ann"], doc_source="8-K 1.01", ann_basis="document",
                 tender=c["universe"].eq("TENDER_CASH"), stock_structural=False, text_class="cash",
                 final_class="cash", acquirer_cik=np.nan, target_rule="single", target_registered=False, sic=1000.0,
                 deal_id="C" + c["deal"].astype(str), source="census_2010")
    return c


def _source(**kw):
    dl = _delist([(10001, "2012-07-02", 233, 0, 30.0, "2012-07-09", np.nan, 0.01, 0.01)])
    dsf = pd.concat([_dsf(10001, "2011-06-01", "2012-06-29"), _dsf(10002, "2021-06-01", "2023-06-30"),
                     _dsf(10003, "2011-06-01", "2013-06-28")], ignore_index=True)
    return FakeSource(NAMES, dl, dsf, **kw)


def test_stage_links_attributes_fetches_and_never_reaches_2023():
    res = S.stage(_source(), _census())
    d = res["deals"].set_index("deal_id")
    assert set(d.index) == {"C1", "C2", "C3"}                     # STOCK_1STEP is not staged
    assert d.loc["C1", "link_status"] == "linked" and d.loc["C1", "crsp_outcome"] == "merger"
    assert d.loc["C3", "link_status"] == "ambiguous"              # two CHARLIE FOODS: not guessed, not staged
    assert d.loc["C2", "crsp_outcome"] == "none" and d.loc["C2", "end"] == S.LAST_FIT_DAY
    assert d.loc["C1", "completed_edgar"] and "completed" not in d.columns
    assert res["dsf"]["date"].max() <= S.LAST_FIT_DAY
    assert set(res["dsf"]["permno"]) == {10001, 10002}
    assert res["summary"]["form25_vs_crsp"]["of_which_crsp_merger_delisting"] == 1
    assert res["summary"]["form25_vs_crsp"]["abs_gap_days_le_15"] == 1


def test_a_source_that_ignores_the_holdout_bound_is_refused():
    with pytest.raises(S.StageError, match="sealed"):
        S.stage(_source(honest=False), _census())


def test_a_missing_crsp_column_raises_naming_it():
    with pytest.raises(S.StageError, match="'bid'"):
        S.stage(_source(drop_col="bid"), _census())


def test_a_census_missing_a_column_raises():
    with pytest.raises(S.StageError, match="census lacks"):
        S.stage(_source(), _census().drop(columns=["a1"]))


def test_the_writer_refuses_the_live_cef_directory(tmp_path, monkeypatch):
    res = S.stage(_source(), _census())
    live = tmp_path / "cef"
    live.mkdir()
    monkeypatch.setattr(S, "LIVE_DIR", live)
    with pytest.raises(FamiliesDataError, match="refusing"):
        S.write_outputs(res, None, None, out_dir=live / "merger_targets")
    S.write_outputs(res, None, None, out_dir=tmp_path / "events" / "merger_targets")
    got = pd.read_csv(tmp_path / "events" / "merger_targets" / S.DEALS_CSV)
    assert len(got) == 3 and (tmp_path / "events" / "merger_targets" / S.SUMMARY_JSON).exists()


# --------------------------------------------------------------------------- the census extension
def _idx(rows):
    d = pd.DataFrame(rows, columns=["cik", "company", "form", "date_filed", "accession"])
    d["date_filed"] = pd.to_datetime(d["date_filed"])
    return d


def _fake_enrich(deals):
    d = deals.copy()
    on = d["listed"]
    d["sic"] = np.where(on, 2000.0, np.nan)
    for c in ("doc_source", "doc_accession", "doc_name"):
        d[c] = None
    d["text_class"] = np.where(on, "unclassified", None)
    d["text_why"] = np.where(on, "no announcement document found", None)
    return d


def test_extension_keeps_a_2003_target_the_form25_rule_would_call_unlisted():
    idx = _idx([(111, "GOLF TECHNOLOGIES INC", "PREM14A", "2003-04-01", "0000000111-03-000001"),
                (111, "GOLF TECHNOLOGIES INC", "DEFM14A", "2003-05-01", "0000000111-03-000002"),
                (222, "HOTEL VENTURES INC", "DEFM14A", "2003-05-01", "0000000222-03-000001"),
                (333, "INDIA FUND INC", "DEFM14A", "2003-05-01", "0000000333-03-000001"),
                (333, "INDIA FUND INC", "N-CSR", "2003-08-01", "0000000333-03-000002")])
    names = _names([(30001, 701, "1998-01-01", "2003-09-30", 11, 3, "GOLF TECHNOLOGIES INC", "GOLF")])
    calls = []

    def enrich(d):
        calls.append(int(d["listed"].sum()))
        return _fake_enrich(d)
    scope, counts = S.extend_census(idx, S.prepare_names(names), enrich)
    assert counts["form25_rule_listed"] == 0          # no Form 25 on EDGAR before 2006
    assert counts["crsp_listed"] == 1 and calls == [1]  # only the CRSP-linked deal is read from EDGAR
    assert len(scope) == 1
    r = scope.iloc[0]
    assert r["target_cik"] == 111 and r["universe"] == "CASH_1STEP"
    assert r["ann"] == T("2003-04-01") and r["ann_basis"] == "d0_upper_bound"
    assert counts["assembled_deals"] == 2             # the fund (an N-CSR filer) never becomes a deal


def test_splice_keeps_the_committed_row_where_two_indexes_saw_one_deal():
    ext = pd.DataFrame({"deal": [1, 2], "target_cik": [5, 6], "d0": pd.to_datetime(["2009-11-01", "2009-11-01"]),
                        "a1": pd.to_datetime(["2010-02-01", "2010-02-01"])})
    com = pd.DataFrame({"deal": [9], "target_cik": [5], "d0": pd.to_datetime(["2010-01-05"]),
                        "a1": pd.to_datetime(["2010-02-01"])})
    out, n = S.splice_census(ext, com)
    assert n == 1 and sorted(out["deal_id"]) == ["C9", "X2"]


def test_an_unusable_primary_document_is_recorded_and_any_other_error_raises():
    deals = pd.DataFrame({"deal": [1, 2], "listed": [True, True]})

    def one(d):
        if int(d["deal"].iloc[0]) == 2:
            raise ValueError("bad primary document name '' for 0000000002-02-000001")
        return d.assign(text_class="cash", text_why="cash=True")
    out = S.enrich_each(one, deals)
    assert out["text_class"].tolist() == ["cash", "unclassified"]
    assert out["text_why"].iloc[1].startswith("primary document unusable")

    def broken(d):
        raise ValueError("ragged submissions block")
    with pytest.raises(ValueError, match="ragged"):
        S.enrich_each(broken, deals)


def test_main_without_the_extension_wires_census_stage_and_writer(tmp_path, monkeypatch):
    out = tmp_path / "events" / "merger_targets"
    monkeypatch.setattr(S, "R2Source", lambda: _source())
    monkeypatch.setattr(S, "load_committed_census", _census)
    monkeypatch.setattr(S, "OUT_DIR", out)
    assert S.main(["--no-extension"]) == 0
    d = pd.read_csv(out / S.DEALS_CSV)
    assert set(d["deal_id"]) == {"C1", "C2", "C3"}
    assert pd.to_datetime(pd.read_parquet(out / S.DSF_PARQUET)["date"]).max() <= S.LAST_FIT_DAY
    assert not (out / S.EXT_CSV).exists()
