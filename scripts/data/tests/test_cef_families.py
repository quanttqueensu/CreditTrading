"""The guards and pure methods of the C4 family-data build (scripts/data/*cef_families*).

WHY THESE TESTS
---------------
The build's two walls are the reason it is safe to run at all: nothing is
written under the live `data/cef/` (landmine 9), and no `cef_universe.csv`
name (the deployed 13 and the 27-name holdout) reaches a family panel. Each
wall is one function, and a refactor that quietly turned either into a no-op
would raise nothing at run time. The rest pin the methods the note's figures
rest on: the NAV-symbol rule (CEFConnect's `NavTicker` first, a conflict never
picked silently), the source comparison (never averaged; a one-day date shift
named as such), the split-basis verdict, the staleness window refusing the
time holdout, and the sleeve's ADV rule.

Synthetic frames only: these test the code, not the market. No network (the
root conftest blocks it); every fetch is behind a function no test calls.
Each test marked "Broken variant checked" was run against that variant on
2026-10-12 and failed, before it was kept.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.data import cef_families_common as C
from scripts.data import cef_families_quality as Q
from scripts.data import fetch_cef_families_cefconnect as CC
from scripts.data import fetch_cef_families_yf as YF
from scripts.data import stage_crsp_cef_families as CR
from scripts.data import cef_families_universe as U


# ---------------------------------------------------------------- the walls

def test_out_path_refuses_the_live_directory_even_through_a_symlink(tmp_path):
    # Broken variant checked: comparing unresolved strings lets a symlinked base through.
    live = tmp_path / "real_data" / "cef"
    live.mkdir(parents=True)
    link = tmp_path / "data"
    link.symlink_to(tmp_path / "real_data")
    with pytest.raises(C.FamiliesDataError, match="inside the live panel directory"):
        C.out_path("cef_prices.parquet", base=link / "cef", live=live)
    ok = C.out_path("cef_prices.parquet", base=link / "cef_families", live=live)
    assert ok.parent.name == "cef_families"          # a sibling whose name starts with "cef" is not inside it


def test_no_universe_name_reaches_a_panel(tmp_path):
    # Broken variant checked: a guard that only warns lets PDI through.
    p = tmp_path / "u.csv"
    pd.DataFrame({"ticker": ["PDI", "NAD"]}).to_csv(p, index=False)
    the44 = C.cef_universe_names(p)
    with pytest.raises(C.FamiliesDataError, match="PDI"):
        C.assert_no_universe_names(["GAB", "PDI"], the44)
    C.assert_no_universe_names(["GAB", "ADX"], the44)


def test_an_empty_universe_file_is_an_error_not_an_open_gate(tmp_path):
    p = tmp_path / "u.csv"
    pd.DataFrame({"ticker": []}).to_csv(p, index=False)
    with pytest.raises(C.FamiliesDataError):
        C.cef_universe_names(p)
    with pytest.raises(C.FamiliesDataError):
        C.cef_universe_names(tmp_path / "missing.csv")


def test_family_of_places_known_categories_and_raises_on_new_ones():
    assert C.family_of("Equity-Covered-Call Funds") == ("equity_covered_call", "covered_call")
    assert C.family_of("Fixed Income - Taxable-High Yield") is None
    with pytest.raises(C.FamiliesDataError, match="place it by hand"):
        C.family_of("Equity-Something New")
    with pytest.raises(C.FamiliesDataError):
        C.family_of(None)


def _cc_row(t, strategy, nav="X%sX"):
    return {"Ticker": t, "Name": t, "Strategy": strategy, "CategoryName": "c", "SponsorName": "s",
            "InceptionDate": "2000-01-03T00:00:00", "NavTicker": nav % t, "NAVPublished": "2026-10-09T00:00:00",
            "Cusip": "000", "IsLeveraged": False, "IsManagedDistribution": False, "Term": False,
            "MarketCapUSDm": 1.0, "TotalAssetsUSDm": 1.0}


def test_universe_excludes_a_holdout_name_even_in_an_in_scope_category():
    # Broken variant checked: filtering on family alone includes PDI here.
    cc = [_cc_row("GAB", "Equity-U.S. Equity"), _cc_row("PDI", "Hybrid-Global Allocation"),
          _cc_row("HYT", "Fixed Income - Taxable-High Yield"), _cc_row("XYZ", "Equity-Sector Equity")]
    assets = [{"symbol": s, "exchange": "NYSE", "status": "active", "tradable": tr, "shortable": True,
               "easy_to_borrow": True, "borrow_status": "easy_to_borrow"}
              for s, tr in (("GAB", True), ("PDI", True), ("HYT", True), ("XYZ", False))]
    umap = pd.DataFrame({"symbol": ["OLD"], "family": ["cef_equity_multi"]})
    u = U.build(cc, {"received_utc": "t"}, assets, {"received_utc": "t"}, {"PDI", "HYT"}, umap)
    inc = set(u.loc[u.included, "ticker"])
    assert inc == {"GAB"}
    why = dict(zip(u.ticker, u.exclusion_reason))
    assert "cef_universe.csv" in why["PDI"]
    assert "tradable is false" in why["XYZ"]
    assert "not listed by CEFConnect" in why["OLD"]
    assert "HYT" not in why                              # out-of-scope category: not a candidate at all


# ---------------------------------------------------------------- yfinance rules

def test_nav_candidates_prefer_cefconnect_and_skip_the_price_ticker():
    assert YF.nav_candidates("ADX", "XADEX") == ["XADEX", "XADXX"]
    assert YF.nav_candidates("GAB", "XGABX") == ["XGABX"]
    assert YF.nav_candidates("HERZ", "HERZ") == ["XHERZX"]
    assert YF.nav_candidates("EVT", None) == ["XEVTX"]


def _nav(dates, vals):
    return pd.DataFrame({"date": pd.to_datetime(dates), "nav": vals, "ticker": "T"})


def test_resolve_nav_never_picks_between_disagreeing_symbols():
    # Broken variant checked: "first with rows wins" returns A for the conflict.
    d = ["2020-01-02", "2020-01-03"]
    empty = pd.DataFrame(columns=["date", "nav", "ticker"])
    assert YF.resolve_nav({"A": empty, "B": empty})[0] is None
    assert YF.resolve_nav({"A": _nav(d, [1, 2]), "B": empty})[0] == "A"
    assert YF.resolve_nav({"A": empty, "B": _nav(d, [1, 2])})[0] == "B"
    assert YF.resolve_nav({"A": _nav(d, [1, 2]), "B": _nav(d, [1.001, 2])})[0] == "A"
    sym, status = YF.resolve_nav({"A": _nav(d, [1, 2]), "B": _nav(d, [1, 2.5])})
    assert sym is None and status.startswith("CONFLICT")


def test_price_rows_count_what_they_drop_and_keep_the_last_duplicate():
    raw = pd.DataFrame({"date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-03", "2020-01-06"]),
                        "Open": 1.0, "High": 1.0, "Low": 1.0, "Close": [1.0, 2.0, 2.5, np.nan],
                        "Volume": [10, 20, 30, 40], "fetched_at_utc": "2020-01-07T23:00:00+00:00"})
    p, log = YF.price_rows(raw, "T", "fam")
    assert list(p["close"]) == [1.0, 2.5]
    assert log["px_duplicate_dates"] == 1 and log["px_dropped_no_close_or_volume"] == 1
    assert p["volume"].dtype == "int64"
    assert list(p.columns) == ["date", "open", "high", "low", "close", "volume", "ticker", "grp"]


def test_a_bar_dated_the_fetch_day_is_dropped_when_fetched_before_the_close():
    raw = pd.DataFrame({"date": pd.to_datetime(["2026-10-09", "2026-10-12"]), "Open": 1.0, "High": 1.0,
                        "Low": 1.0, "Close": 1.0, "Volume": 1,
                        "fetched_at_utc": "2026-10-12T18:00:00+00:00"})          # 14:00 ET
    p, log = YF.price_rows(raw, "T", "f")
    assert list(p["date"].dt.date.astype(str)) == ["2026-10-09"] and log["px_dropped_partial_today"] == 1


# ---------------------------------------------------------------- CEFConnect parse

def test_cefconnect_parse_drops_rows_without_nav_and_refuses_duplicate_dates():
    rows = [{"DataDate": "2026-10-08T00:00:00", "NAVData": 5.0, "Data": 4.9, "DiscountData": -2.0},
            {"DataDate": "2026-10-09T00:00:00", "NAVData": None, "Data": 4.9, "DiscountData": None}]
    d, log = CC.parse({"rows": rows}, "T", "1Y")
    assert len(d) == 1 and log["1Y_rows_without_nav"] == 1
    with pytest.raises(C.FamiliesDataError):
        CC.parse({"rows": rows[:1] * 2}, "T", "1Y")


# ---------------------------------------------------------------- CRSP panel

def test_crsp_panel_takes_the_current_permno_and_refuses_an_unrelated_earlier_issuer():
    # Broken variant checked: the plain date-range join keeps permno 3's 1985 rows,
    # a share-code-11 company that once used the ticker (the STEW / Stewart Sandwiches case).
    dsf = pd.DataFrame({"permno": [1, 1, 1, 2, 2, 3], "date": pd.to_datetime(
        ["2010-01-04", "2010-01-05", "2010-01-06", "2008-01-02", "2010-01-04", "1985-01-02"]),
        "prc": [10.0, -10.1, 10.2, 5.0, 5.5, 7.0], "vol": [100, 0, 200, 50, 60, 70], "openprc": np.nan,
        "askhi": 11.0, "bidlo": 9.0, "cfacpr": 1.0, "cfacshr": 1.0, "shrout": 1.0})
    names = pd.DataFrame({"permno": [1, 2, 3], "ticker": ["T", "T", "T"], "shrcd": [44, 14, 11],
                          "namedt": pd.to_datetime(["2009-06-01", "2007-01-01", "1980-01-01"]),
                          "nameenddt": pd.to_datetime(["2024-12-31", "2009-05-29", "1990-12-31"])})
    dsf["date"] = dsf["date"].astype("datetime64[us]")                  # as DuckDB returns it
    pmap = pd.DataFrame({"ticker": ["T"], "current_permno": [1], "other_permnos": ["2 3"]})
    P, R, counts = CR.build_panel(dsf, pmap, names, {"T": "fam"})
    assert P["date"].dtype == "datetime64[ns]"                           # the live schema's precision
    # permno 2's 2010 row is after permno 1 starts: not added; its 2008 row is a CEF predecessor: added
    assert list(P["date"].dt.strftime("%Y-%m-%d")) == ["2008-01-02", "2010-01-04", "2010-01-06"]
    c = counts.iloc[0]
    assert c["crsp_no_trade_rows"] == 1 and c["predecessor_rows"] == 1 and c["permnos_refused"] == "3"
    assert list(P.columns) == ["date", "open", "high", "low", "close", "volume", "ticker", "grp"]


# ---------------------------------------------------------------- quality methods

def test_compare_levels_names_a_one_day_shift_and_never_averages():
    a = pd.DataFrame({"ticker": "T", "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
                      "nav": [10.0, 10.5, 11.0]})
    b = pd.DataFrame({"ticker": "T", "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
                      "nav_cc": [10.0, 10.0, 12.0]})
    m = Q.compare_levels(a, b, "nav", "nav_cc", shift_ref=a, shift_col="nav")
    assert list(m["category"]) == ["AGREE", "SHIFT_PREV", "UNEXPLAINED"]
    assert "nav" in m and "nav_cc" in m and not any("mean" in c for c in m.columns)


def test_split_basis_flags_a_price_adjusted_against_a_raw_nav():
    d = pd.bdate_range("2020-01-01", periods=60)
    px = pd.DataFrame({"ticker": "T", "date": d, "close": 10.0})          # back-adjusted: flat through the split
    nav = pd.DataFrame({"ticker": "T", "date": d, "nav": np.where(d < d[30], 2.5, 10.0)})   # raw: jumps 4x
    act = pd.DataFrame({"ticker": ["T"], "date": [d[30]], "stock_splits": [0.25], "dividends": [0.0]})
    v = Q.split_basis(px, nav, act)
    assert v["verdict"].iloc[0].startswith("BASIS MISMATCH")
    nav2 = nav.assign(nav=10.0)
    assert Q.split_basis(px, nav2, act)["verdict"].iloc[0] == "same basis"


def test_staleness_refuses_a_window_inside_the_time_holdout():
    ch = pd.DataFrame({"ticker": "T", "date": pd.bdate_range("2022-01-03", periods=10), "r": 0.0})
    with pytest.raises(C.FamiliesDataError, match="holdout"):
        Q.lag1(ch, "r", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-06-30"), 1)


def test_lag1_recovers_a_smoothed_series_and_adds_distributions_back():
    rng = np.random.default_rng(0)
    e = rng.normal(0, 0.01, 3000)
    r = np.empty_like(e); r[0] = e[0]
    for i in range(1, len(e)):
        r[i] = 0.5 * r[i - 1] + e[i]                                     # AR(1) phi 0.5: a stale NAV
    d = pd.bdate_range("2010-01-04", periods=len(r) + 1)
    nav = pd.DataFrame({"ticker": "T", "date": d, "nav": 10 * np.r_[1, np.cumprod(1 + r)]})
    ch = Q.nav_tr_changes(nav, pd.DataFrame(columns=["ticker", "date", "amount"]))
    s = Q.lag1(ch, "r", d[0], pd.Timestamp("2021-12-31"), 500)
    assert abs(s["ac1"].iloc[0] - 0.5) < 0.06
    # a distribution on day k: NAV drops by the amount, the TR change is flat
    nav2 = pd.DataFrame({"ticker": "T", "date": d[:3], "nav": [10.0, 9.9, 9.9]})
    dist = pd.DataFrame({"ticker": ["T"], "date": [d[1]], "amount": [0.1]})
    ch2 = Q.nav_tr_changes(nav2, dist)
    assert np.isclose(ch2["r"].iloc[1], 0.0) and np.isclose(ch2["r_raw"].iloc[1], -0.01)


def test_adv_is_the_sleeves_rule_shifted_one_session():
    # Broken variant checked: without .shift(1) the first value appears on day 21, not 22.
    d = pd.bdate_range("2020-01-01", periods=30)
    px = pd.DataFrame({"ticker": "T", "date": d, "close": 10.0, "volume": 1000})
    a = Q.adv_panel(px)["T"]
    assert a.iloc[:Q.ADV_MIN].isna().all() and a.iloc[Q.ADV_MIN] == 10_000.0


def test_a_stale_vendor_copy_is_named_as_such():
    # yfinance printed Thursday's NAV again on Friday while CEFConnect moved (ETY, 2023-05-05)
    a = pd.DataFrame({"ticker": "T", "date": pd.to_datetime(["2023-05-03", "2023-05-04", "2023-05-05"]),
                      "nav": [11.82, 11.74, 11.74]})
    b = pd.DataFrame({"ticker": "T", "date": pd.to_datetime(["2023-05-05"]), "nav_cc": [11.93]})
    m = Q.compare_levels(a, b, "nav", "nav_cc", shift_ref=a, shift_col="nav")
    assert list(m["category"]) == ["A_REPEATED"]


def test_a_nav_symbol_that_returns_the_price_is_measured():
    d = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])
    p = pd.DataFrame({"date": d, "close": [10.0, 10.1, 10.2, 10.3]})
    assert YF.price_as_nav_share(p, pd.DataFrame({"date": d, "nav": [10.0, 10.1, 10.2, 10.3]})) == 1.0
    assert YF.price_as_nav_share(p, pd.DataFrame({"date": d, "nav": [11.0, 11.1, 10.2, 11.3]})) == 0.25
    assert YF.PRICE_AS_NAV_SHARE == 0.5


def test_discount_compare_is_basis_free_and_its_tolerance_is_the_rounding_bound():
    # Broken variant checked: comparing NAV levels instead flags the re-based row.
    d = pd.to_datetime(["2020-01-03", "2020-01-10"])
    yf = pd.DataFrame({"ticker": "T", "date": d, "close": [40.0, 9.5], "nav": [44.0, 10.0]})   # first row re-based x4 on both legs
    cc = pd.DataFrame({"ticker": "T", "date": d, "close_cc": [10.0, 9.5], "nav": [11.0, 10.0], "window": "All"})
    m = Q.discount_compare(yf, cc)
    assert m["agree"].all()
    yf2 = yf.assign(close=[40.0 / 1.023, 9.5])                         # price re-based for a rights 'split', NAV not
    assert list(Q.discount_compare(yf2, cc)["agree"]) == [False, True]


def test_leg_attribution_names_a_rebased_yfinance_close():
    r = {"med_yfclose_over_crsp": 0.95, "med_ccclose_over_crsp": 1.0, "med_yfnav_over_ccnav": 1.0}
    assert Q._attribute(r).startswith("yfinance CLOSE re-based")
    r2 = {"med_yfclose_over_crsp": 20.0, "med_ccclose_over_crsp": 20.0, "med_yfnav_over_ccnav": 0.377}
    assert Q._attribute(r2).startswith("NAV legs differ")
    r3 = {"med_yfclose_over_crsp": 4.0, "med_ccclose_over_crsp": 4.0, "med_yfnav_over_ccnav": 1.0}
    assert Q._attribute(r3) == "consistent (medians)"


def test_split_factor_applies_only_to_dates_before_each_split():
    rows = pd.DataFrame({"ticker": ["T", "T", "T", "U"],
                         "date": pd.to_datetime(["2010-01-04", "2015-01-05", "2021-01-04", "2010-01-04"])})
    act = pd.DataFrame({"ticker": ["T", "T"], "date": pd.to_datetime(["2014-12-29", "2020-06-15"]),
                        "stock_splits": [0.25, 1.02], "dividends": [0.0, 0.0]})
    assert list(Q.split_factor(rows, act)) == [0.25 * 1.02, 1.02, 1.0, 1.0]
