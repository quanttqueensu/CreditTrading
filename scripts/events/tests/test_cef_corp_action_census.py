"""The parsers, guards and arithmetic behind the CEF corporate-action census, on literal strings and synthetic frames.

WHY THESE TESTS
---------------
The census reads ~1,000 filings with regular expressions and turns them into
counts, terms and terms-implied spreads. Each way it could go wrong quietly has
a test:

  * the zero-trial guards: a level statistic on a 2023+ event must raise
    (`assert_pre_holdout`), ADV must use sessions strictly BEFORE the
    announcement, and a close is taken on the stated date only;
  * the tender-offer parser: the price basis is the MODE of every "k% of NAV"
    statement (one stray history sentence must not set it); "5:00 P.M., NEW
    YORK CITY TIME, ON ..." must yield the expiry (a first draft's `[^.]` could
    not cross "P.M." and read 23 of 206 expiries); the three NAV-statement
    forms; Dutch-auction and interval-fund documents;
  * the result parser: accepted/tendered, a stated factor, a sponsor's
    multi-fund results table read by ticker, "all accepted", and a factor
    outside (0, 1] raising;
  * Form N-8F: exactly one checked box, or 'unknown';
  * `nav_beside_price`: the row layout, the pair layout, and a multi-fund
    report where only the exact CRSP close identifies the fund's column;
  * `classify_exit`: a missing N-8F arrives as NaN from a DataFrame, not None
    (the first draft classified 21 CRSP liquidations as "unresolved" for
    exactly that reason); a merger with no named survivor is not an
    open-ending;
  * the tracked CSV carries no CRSP-derived column (licensing);
  * the transport retry re-sends the same request and raises at the end.

Synthetic inputs test the code, not the market. No network: the root
conftest blocks it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import cef_corp_action_census as C


# ------------------------------------------------------------------ guards

def test_holdout_guard():
    C.assert_pre_holdout("2022-12-30", "x")
    for d in ("2023-01-01", "2024-06-30", None):
        with pytest.raises(C.HoldoutError):
            C.assert_pre_holdout(d, "x")


def _dsf(dates, vol, prc, permno=1):
    return pd.DataFrame({"permno": permno, "date": pd.to_datetime(dates), "vol": vol, "prc": prc})


def test_adv_uses_only_sessions_before_the_date():
    dates = pd.bdate_range("2020-01-01", periods=80)
    vol = np.full(80, 1000.0)
    vol[63:] = 1e9                       # the announcement day and after: must not enter
    d = _dsf(dates, vol, np.full(80, 10.0))
    assert C.adv_before(d, 1, dates[63]) == pytest.approx(10_000.0)
    with pytest.raises(C.HoldoutError):
        C.adv_before(d, 1, "2023-01-03")


def test_adv_needs_two_thirds_of_the_window():
    dates = pd.bdate_range("2020-01-01", periods=30)
    d = _dsf(dates, np.full(30, 1.0), np.full(30, 1.0))
    assert C.adv_before(d, 1, "2020-03-01") is None


def test_close_on_is_exact_date_only():
    d = _dsf(["2020-01-02", "2020-01-06"], [1, 1], [10.0, 11.0])
    assert C.close_on(d, 1, "2020-01-06") == 11.0
    assert C.close_on(d, 1, "2020-01-03") is None
    px, when = C.last_close_at_or_before(d, 1, "2020-01-05")
    assert px == 10.0 and when == pd.Timestamp("2020-01-02")
    assert C.last_close_at_or_before(d, 1, "2020-02-05") == (None, None)


# ------------------------------------------------------- names and classes

@pytest.mark.parametrize("name,sp", [("NUVEEN QUALITY MUNICIPAL INCOME FUND", "Nuveen"),
                                     ("MUNIYIELD QUALITY FUND II INC", "BlackRock"),
                                     ("D W S GLOBAL HIGH INCOME FUND", "DWS"),
                                     ("PACHOLDER HIGH YIELD FUND INC", "JPMorgan")])
def test_sponsor_recognised(name, sp):
    assert C.sponsor_of(name) == (sp, True)


def test_sponsor_unrecognised_is_its_own_group():
    s, ok = C.sponsor_of("Obscure Value Fund, Inc.")
    assert not ok and s == "OBSCURE VALUE FUND, INC."
    with pytest.raises(ValueError):
        C.sponsor_of("  ")


@pytest.mark.parametrize("name,a", [("NUVEEN MUNICIPAL HIGH INCOME OPPORTUNITY FUND", "muni"),
                                    ("EATON VANCE FLOATING-RATE INCOME TRUST", "loans"),
                                    ("PACHOLDER HIGH YIELD FUND INC", "high_yield"),
                                    ("EUROPEAN EQUITY FUND, INC / MD", "eq_europe"),
                                    ("ADAMS DIVERSIFIED EQUITY FUND", "eq_us")])
def test_asset_class(name, a):
    assert C.asset_class_of(name) == a
    assert a in C.HEDGE_ETF


def test_term_marker():
    assert C.is_term_fund("BLACKROCK MUN 2018 TERM TR")
    assert C.is_term_fund("Nuveen High Income 2020 Target Term Fund")
    assert not C.is_term_fund("NUVEEN QUALITY MUNICIPAL INCOME FUND")


# ------------------------------------------------------ tender offer parser

SWZ = ("the Transaction Value was calculated by multiplying 4,579,480 shares of common stock of the Fund "
       "(approximately 15% of the total number of shares outstanding on January 6, 2014) by $14.52 (95% of the net "
       "asset value per share of $15.28 as of the close of regular trading on the New York Stock Exchange on January 6, "
       "2014). OFFER TO PURCHASE Up to 4,579,480 Shares of Common Stock At a Cash Purchase Price of 95% of Net Asset "
       "Value Per Share THE OFFER, PRORATION PERIOD AND WITHDRAWAL RIGHTS WILL EXPIRE AT 5:00 P.M., NEW YORK CITY TIME, "
       "ON FEBRUARY 11, 2014 UNLESS THE FUND EXTENDS THE OFFER. The shares are traded on the New York Stock Exchange "
       "under the ticker symbol “SWZ.” purchase up to 4,579,480 (approximately 15%) of its issued and "
       "outstanding shares at a price equal to 95% of the NAV per share")


def test_tender_offer_fee_line():
    p = C.parse_tender_offer(SWZ)
    assert p["basis"] == "pct_nav" and p["k_pct"] == 95.0
    assert p["listed"] and p["ticker"] == "SWZ"
    assert p["size_pct"] == 15.0
    assert p["expire"] == pd.Timestamp("2014-02-11")
    assert p["nav_kind"] == "fee_nav" and p["nav"] == 15.28 and p["nav_date"] == pd.Timestamp("2014-01-06")


def test_expiry_crosses_pm():
    t = "WILL EXPIRE AT 5:00 P.M., NEW YORK CITY TIME, ON FEBRUARY 11, 2014"
    assert C._EXPIRE_RE.search(t).group("d") == "FEBRUARY 11, 2014"


def test_k_is_the_mode_not_the_first():
    t = ("In 2009 the Fund tendered at 95% of net asset value. " + "The price is 98% of NAV. " * 3
         + "Shares are listed on the NYSE.")
    assert C.parse_tender_offer(t)["k_pct"] == 98.0


def test_nav_statement_forms():
    a = C.parse_nav_statement("based upon a price per share of $18.44, which represents 99% of the net asset value "
                              "per share on April 23, 2010")
    assert a["nav_kind"] == "fee_price" and a["nav"] == pytest.approx(18.44 / 0.99, rel=1e-6)
    b = C.parse_nav_statement("Calculated as the aggregate maximum purchase price based upon the net asset value per "
                              "share as of July 31, 2022 of $16.40 and the offer")
    assert b["nav_kind"] == "nav_asof" and b["nav"] == 16.40
    c = C.parse_nav_statement("On June 19, 2012, the Fund's net asset value per share was $4.36 and the last sale $3.92")
    assert c["nav_kind"] == "on_date" and c["nav"] == 4.36 and c["nav_date"] == pd.Timestamp("2012-06-19")
    assert C.parse_nav_statement("no statement here")["nav_kind"] is None


def test_dutch_and_unlisted():
    d = C.parse_tender_offer("at a price not greater than $10.50 nor less than $9.50 per Share, net to the seller")
    assert d["basis"] == "dutch" and d["dutch_lo"] == 9.5 and d["dutch_hi"] == 10.5
    assert not d["listed"]
    u = C.parse_tender_offer("The Fund is an interval fund. There is no secondary market for the Shares. "
                             "at a price equal to 100% of net asset value")
    assert not u["listed"]


# ------------------------------------------------------------ result parser

def test_result_accepted_over_tendered():
    t = ("approximately 19,260,691 shares of common stock or approximately 63% of the Fund's outstanding shares as of "
         "the commencement of the Offer were properly tendered, and the Fund has accepted 4,579,480 shares for cash")
    r = C.parse_tender_result(t)
    assert r["proration"] == pytest.approx(4_579_480 / 19_260_691)
    assert r["proration_how"] == "accepted/tendered"


def test_result_stated_factor_and_table_row():
    r = C.parse_tender_result("Under final pro-ration, 29.9% of the Common Shares tendered will be accepted for payment")
    assert r["proration"] == pytest.approx(0.299)
    t = ("Fund Shares Properly Tendered Shares to be Purchased Pro-Ration Factor* TYG 5,215,915 596,395 0.1144 "
         "NTG 1,000,000 100,000 0.1000")
    r2 = C.parse_tender_result(t.replace("Pro-Ration Factor*", "Factor*"), ticker="TYG")
    assert r2["proration"] == pytest.approx(596_395 / 5_215_915)
    assert r2["proration_how"] == "results-table row (self-consistent), ticker TYG"


def test_result_all_accepted_and_bad_factor():
    assert C.parse_tender_result("All Shares validly tendered and not withdrawn were accepted for payment")["proration"] == 1.0
    with pytest.raises(ValueError):
        C.parse_tender_result("the proration factor was 120% of shares")
    assert C.parse_tender_result("the offer expired")["proration"] is None


# -------------------------------------------------------------------- N-8F

N8F = ("1. Reason fund is applying to deregister (check only one; for descriptions, see Instruction 1 above): "
       "[ ] Merger [x] Liquidation [ ] Abandonment of Registration (Note: ...) [ ] Election of status as a Business "
       "Development Company 2. Name of fund: ... If Yes, state the date on which the board vote took place: "
       "January 23, 2017 If No, explain: ... If Yes, state the date on which the shareholder vote took place: May 10, "
       "2017 ... (a) If Yes, list the date(s) on which the fund made those distributions: The fund made liquidating "
       "distributions to stockholders on July 11, 2017 and August 29, 2017. (b) Were the distributions made")


def test_n8f_liquidation():
    r = C.parse_n8f(N8F)
    assert r["reason"] == "liquidation"
    assert r["board_date"] == pd.Timestamp("2017-01-23") and r["holder_date"] == pd.Timestamp("2017-05-10")
    assert r["dist_first"] == pd.Timestamp("2017-07-11") and r["dist_last"] == pd.Timestamp("2017-08-29")


def test_n8f_two_boxes_is_unknown():
    assert C.parse_n8f(N8F.replace("[ ] Merger", "[x] Merger"))["reason"] == "unknown"


def test_n8f_merger_survivor():
    t = N8F.replace("[ ] Merger [x] Liquidation", "[x] Merger [ ] Liquidation") + (
        " 23. (a) State the name of the fund surviving the Merger: AB Income Fund, a series of AB Bond Fund (b) State the"
        " Investment Company Act file number")
    r = C.parse_n8f(t)
    assert r["reason"] == "merger" and r["survivor"] == "AB Income Fund, a series of AB Bond Fund"


# --------------------------------------------------------- nav_beside_price

ROW = ("Net asset value, end of period $ 7.86 $ 6.97 $ 8.18 $ 8.63 $ 8.57 "
       "Market value per share, end of period $ 7.20 $ 6.07 $ 7.35 $ 7.86 $ 8.87 TOTAL INVESTMENT RETURN")


def test_row_layout_takes_the_same_column():
    assert C.nav_beside_price(ROW, 7.20)["nav"] == 7.86
    assert C.nav_beside_price(ROW, 6.07)["nav"] == 6.97
    assert C.nav_beside_price(ROW, 7.35)["layout"] == "row"


def test_pair_layout():
    t = "Net Asset Value (NAV) ** Market Price 1 Year 22.62 % 29.16 % Price per share at December 31, 2016 $ 7.86 $ 7.20 *"
    h = C.nav_beside_price(t, 7.20)
    assert h["nav"] == 7.86 and h["layout"] == "pair"


def test_multi_fund_report_matched_by_exact_close():
    other = ROW.replace("7.86 $ 6.97", "12.40 $ 6.97").replace("7.20 $ 6.07", "11.10 $ 6.07")
    doc = other + " ... Fund B ... " + ROW
    assert C.nav_beside_price(doc, 7.20)["nav"] == 7.86
    assert C.nav_beside_price(doc, 11.10)["nav"] == 12.40
    assert C.nav_beside_price(doc, 5.55) is None


# ----------------------------------------------------------- classify_exit

def _exit(**k):
    base = {"dlstcd": 450, "reason": np.nan, "fund": "SOME HIGH YIELD FUND", "crsp_name": "SOME HI YLD FD",
            "survivor": np.nan, "files_open_end_forms_after": False}
    base.update(k)
    return base


def test_classify_exit_nan_reason_falls_to_crsp_code():
    assert C.classify_exit(_exit()) == "liquidation"
    assert C.classify_exit(_exit(fund="BLACKROCK MUNICIPAL 2018 TERM TRUST")) == "term_termination"
    assert C.classify_exit(_exit(dlstcd=232)) == "unresolved"


def test_classify_exit_mergers():
    assert C.classify_exit(_exit(dlstcd=232, reason="merger", survivor="AB Income Fund, a series of AB Bond Fund")) == "open_ending"
    assert C.classify_exit(_exit(dlstcd=232, reason="merger", survivor=np.nan)) == "merger_into_unlisted"
    assert C.classify_exit(_exit(dlstcd=232, reason="merger", survivor="XYZ Credit Interval Fund")) == "merger_into_unlisted"
    assert C.classify_exit(_exit(dlstcd=332, files_open_end_forms_after=True)) == "open_ending"


# ---------------------------------------------------------------- arithmetic

def test_spreads():
    assert C.accepted_slice_spread(98, -0.10) == pytest.approx(0.98 / 0.90 - 1)
    assert C.position_spread(98, -0.10, 0.25) == pytest.approx(0.25 * (0.98 / 0.90 - 1))
    assert C.nav_exit_spread(-0.05) == pytest.approx(1 / 0.95 - 1)
    for bad in [(0, -0.1), (98, -0.6)]:
        with pytest.raises(ValueError):
            C.accepted_slice_spread(*bad)
    with pytest.raises(ValueError):
        C.position_spread(98, -0.1, 0.0)


def test_cost_units():
    assert C.cost_units("liquidation", None) == 1.0
    assert C.cost_units("nav_tender", 0.3) == pytest.approx(1.7)
    assert C.cost_units("activist_13d", None) is None


# --------------------------------------------------------------- activists

def test_activist_filter_and_campaign_collapse():
    assert C.is_activist("Saba Capital Management, L.P.") and C.is_activist("GOLDSTEIN PHILLIP")
    assert not C.is_activist("BANK OF AMERICA CORP /DE/")
    idx = pd.DataFrame([
        (100, "FUND A", "SC 13D", "2015-01-05", "a1"), (900, "Saba Capital Management, L.P.", "SC 13D", "2015-01-05", "a1"),
        (100, "FUND A", "SC 13D", "2015-06-05", "a2"), (900, "Saba Capital Management, L.P.", "SC 13D", "2015-06-05", "a2"),
        (100, "FUND A", "SC 13D", "2017-06-05", "a3"), (900, "Saba Capital Management, L.P.", "SC 13D", "2017-06-05", "a3"),
        (200, "FUND B", "SC 13D", "2016-01-05", "b1"), (901, "BANK OF AMERICA CORP /DE/", "SC 13D", "2016-01-05", "b1"),
    ], columns=["cik", "company", "form", "date_filed", "accession"])
    idx["date_filed"] = pd.to_datetime(idx["date_filed"])
    f = pd.DataFrame({"cik": [100, 200], "ticker_now": ["AAA", None]})
    out = C.activist_events(idx, {100, 200}, f)
    assert list(out["accession"]) == ["a1", "a3"]          # a2 is the same campaign; the bank is not an activist
    assert set(out["ticker_now"]) == {"AAA"}


def test_groups_count_sponsor_date():
    df = pd.DataFrame({"sponsor": ["Nuveen", "Nuveen", "Nuveen", "X"], "sponsor_recognised": [True, True, True, False],
                       "ann_date": pd.to_datetime(["2015-01-05", "2015-01-05", "2015-01-20", "2015-01-05"])})
    g = C.groups(df)
    assert g["sponsor_x_date"] == 3 and g["sponsor_x_month"] == 2
    assert g["unrecognised_sponsor_share"] == 0.25


# ---------------------------------------------------------------- licensing

def test_tracked_view_has_no_crsp_column():
    ev = pd.DataFrame({c: [None] for c in set(C.TRACKED_COLS) | set(C.LICENSED_COLS)})
    ev["type"], ev["cik"], ev["ann_date"] = "nav_tender", 1, pd.Timestamp("2015-01-01")
    v = C.tracked_view(ev)
    assert not set(v.columns) & set(C.LICENSED_COLS)
    ev2 = ev.assign(type="liquidation", cik=np.nan)
    assert len(C.tracked_view(ev2)) == 0                    # a CRSP-only exit row is not published


# --------------------------------------------------------- transport retry

def test_fetch_raw_retries_then_raises():
    import requests

    class Flaky:
        def __init__(self, fails):
            self.fails, self.calls = fails, 0

        def get_text(self, url):
            self.calls += 1
            if self.calls <= self.fails:
                raise requests.exceptions.ReadTimeout("t")
            return "ok"

    slept = []
    c = Flaky(2)
    assert C.fetch_raw(c, 1, "0001193125-17-069072", sleep=slept.append) == "ok"
    assert c.calls == 3 and slept == list(C.TRANSPORT_RETRY_S[:2])
    with pytest.raises(requests.exceptions.ReadTimeout):
        C.fetch_raw(Flaky(99), 1, "0001193125-17-069072", sleep=lambda s: None)


# ------------------------------------------- holdout and universe in the levels

def test_period_end_discount_refuses_a_2023_event_before_any_fetch():
    class Boom:
        def get_text(self, url):
            raise AssertionError("must not fetch")
    with pytest.raises(C.HoldoutError):
        C.period_end_discount(Boom(), pd.DataFrame(columns=["cik", "date_filed", "accession"]), 1, 1, "2023-02-01", None)


def test_add_spreads_only_for_pre_2023_funds_outside_the_44():
    ev = pd.DataFrame({
        "type": ["nav_tender"] * 3 + ["liquidation"],
        "ann_date": pd.to_datetime(["2015-01-05", "2015-01-05", "2023-03-01", "2016-01-05"]),
        "in_universe": [False, True, False, False],
        "k_pct": [98.0, 98.0, 98.0, None], "disc_post": [-0.10, -0.10, -0.10, None],
        "disc_pre": [-0.12, -0.12, -0.12, -0.08], "expire": [pd.Timestamp("2015-02-20")] * 3 + [None],
        "end_date": pd.to_datetime(["2015-03-01"] * 3 + ["2016-06-30"])})
    ev["pre_holdout"] = ev["ann_date"] < C.TIME_HOLDOUT
    out = C.add_spreads(ev, a_expected=0.3)
    assert out.loc[0, "pos_post"] == pytest.approx(0.3 * (0.98 / 0.90 - 1))
    assert out.loc[1, "pos_post"] is None and out.loc[2, "pos_post"] is None   # the 44; the time holdout
    assert out.loc[3, "pos_pre"] == pytest.approx(1 / 0.92 - 1)
    assert out.loc[0, "hold"] == 47 and out.loc[3, "hold"] == 177


def test_not_all_accepted_is_not_all_accepted():
    t = "not all shares that were tendered were accepted for payment by the Fund. Under the final pro-ration"
    assert C.parse_tender_result(t)["proration"] is None


def test_gate_refuses_an_upper_bound_spread():
    rows = [{"type": "liquidation", "groups_2010_22_ex44": 40, "usable_groups": 35, "net_30bp": 0.05, "cost_units": 1.0,
             "spread_basis": "disc_pre (last period-end before announcement): an UPPER bound", "hedge_shortable_share": 0.2,
             "hedge_any_shortable_share": 0.9},
            {"type": "nav_tender", "groups_2010_22_ex44": 29, "usable_groups": 31, "net_30bp": 0.004, "cost_units": 1.7,
             "spread_basis": "disc_post (offer-stated NAV, CRSP close same date) x expected pro-ration",
             "hedge_shortable_share": 0.9, "hedge_any_shortable_share": 0.5, "proration_groups": 30}]
    g = {x["gate"].split(":")[0]: x["pass"] for x in C.gate_table(rows, ["liquidation", "nav_tender"])}
    assert g["liquidation-a"] and g["liquidation-b"] and not g["liquidation-c"] and g["liquidation-d"]
    assert not g["nav_tender-a"] and g["nav_tender-b"] and g["nav_tender-c"] and not g["nav_tender-d"] and g["nav_tender-e"]
    # gate d reads the any-candidate share (0.9 primary-alone does not rescue nav_tender's 0.5)


# ------------------------------------------- strict disc_post (2026-10-18 fix)

def test_post_discount_refuses_a_nav_dated_before_the_announcement():
    # 33 of 130 offer NAVs in the 2026-10-15 build were dated before the episode's first
    # filing; the old code called those levels "disc_post". This fails against it.
    d, why = C.post_discount(10.0, "2015-03-02", "2015-03-05", 9.0)
    assert d is None and why == "NAV date before the announcement"
    d, why = C.post_discount(10.0, "2015-03-05", "2015-03-05", 9.0)
    assert d == pytest.approx(-0.10) and why == "ok"
    assert C.post_discount(10.0, "2015-03-09", "2015-03-05", None) == (None, "no CRSP close on the NAV date")
    assert C.post_discount(10.0, "2015-03-09", "2015-03-05", 3.0)[0] is None      # price/NAV 0.3: a mis-parse


def test_giveback_spread():
    # entry at -8%, 30% accepted at 98% of NAV, residual back at the pre-announcement -12%
    g = C.giveback_spread(98, -0.08, -0.12, 0.3)
    assert g == pytest.approx(0.3 * (0.98 / 0.92 - 1) + 0.7 * (0.88 / 0.92 - 1))
    assert g < C.position_spread(98, -0.08, 0.3)
    assert C.giveback_spread(98, -0.08, -0.08, 0.3) == pytest.approx(C.position_spread(98, -0.08, 0.3))
    with pytest.raises(ValueError):
        C.giveback_spread(98, -0.08, -0.7, 0.3)


def test_add_spreads_uses_strict_post_and_reports_the_sensitivities():
    ev = pd.DataFrame({"type": ["nav_tender"], "ann_date": pd.to_datetime(["2015-01-05"]), "in_universe": [False],
                       "k_pct": [98.0], "disc_post": [None], "disc_navdate": [-0.10], "disc_pre": [-0.12],
                       "expire": [pd.Timestamp("2015-02-20")], "end_date": pd.to_datetime(["2015-03-01"])})
    ev["pre_holdout"] = True
    out = C.add_spreads(ev, a_expected=0.3)
    assert out.loc[0, "pos_post"] is None and out.loc[0, "pos_giveback"] is None
    assert out.loc[0, "pos_navdate"] == pytest.approx(0.3 * (0.98 / 0.90 - 1))


# ------------------------------------------------------------ hedge choice

def _flags(**ok):
    return pd.DataFrame([{"symbol": s, "found": v is not None, "shortable": bool(v)} for s, v in ok.items()]
                        ).set_index("symbol")


def test_hedge_choice_falls_to_a_declared_alternate():
    f = _flags(MUB=False, VTEB=False, TFI=True, HYD=True, SUB=True)
    assert C.hedge_choice("MUB", f) == ("TFI", False)
    assert C.hedge_choice("MUB", _flags(MUB=True, VTEB=True, TFI=True, HYD=True, SUB=True)) == ("MUB", True)
    assert C.hedge_choice("MUB", _flags(MUB=False, VTEB=False, TFI=False, HYD=None, SUB=False)) == (None, False)
    with pytest.raises(KeyError):
        C.hedge_choice("MUB", _flags(MUB=False))            # an alternate not read is a bug, not "no"
    with pytest.raises(KeyError):
        C.hedge_choice("ZZZ", f)


def test_hedge_summary_reports_primary_and_any():
    f = _flags(MUB=False, VTEB=True, TFI=True, HYD=True, SUB=True, HYG=True, JNK=True, USHY=True)
    h = C.hedge_summary(["MUB", "MUB", "HYG", "MUB"], f)
    assert h["hedge_shortable_share"] == 0.25 and h["hedge_any_shortable_share"] == 1.0
    assert h["hedge_used"] == {"MUB": "VTEB", "HYG": "HYG"} and h["hedge_etf_mode"] == "MUB"


def test_every_alternate_class_has_a_primary():
    assert set(C.HEDGE_ALTERNATES) <= set(C.HEDGE_ETF)


# ------------------------------------- conditional tenders outside the 44

def test_trigger_share_excludes_the_44():
    # One sponsor-window cluster: a universe fund untriggered, a non-universe fund triggered,
    # plus a second cluster holding ONLY a universe fund. Counting the universe-only cluster
    # (the old code) gives 1/2; outside the 44 the share is 1/1.
    c = pd.DataFrame({
        "ticker": ["EFT", "XYZ", "EFR"], "sponsor": ["EV", "EV", "EV"],
        "window_start": ["2022-06-01", "2022-06-01", "2021-06-01"],
        "window_end": ["2022-08-31", "2022-08-31", "2021-08-31"],
        "announced": ["2021-01-01"] * 3,
        "outcome": ["not_triggered_inferred", "triggered", "not_triggered"],
        "published_avg_pct": [None, -11.0, None], "tender_price_pct_nav": [98.0, 98.0, 98.0],
        "proration_pct": [None, 30.0, None], "threshold_pct": [10.0] * 3})
    s = C.cond_tender_summary(c, {"EFT", "EFR"})
    assert s["p_trigger_cluster_pre2023"] == 1.0
    assert s["clusters_known_pre2023"] == 2 and s["clusters_known_pre2023_ex44"] == 1
    assert s["window_days_median"] == 91.0


# ------------------------- result phrasings the 2026-10-15 parser missed (49 of 129)
# Each string is quoted from a real final SC TO-I/A (accession in the comment).

def test_decimal_percent_inside_the_tendered_sentence():
    # Chile Fund 2010, 0001104659-10-032524: "60.34%" stopped the old [^.;] pattern
    t = ("approximately 6,135,126 shares of common stock or 60.34% of the Fund’s outstanding stock were properly "
         "tendered, and the Fund has accepted, subject to adjustment for fractional shares and odd lots, 2,542,026 "
         "shares for cash payment at a price equal to $17.82")
    r = C.parse_tender_result(t)
    assert r["proration"] == pytest.approx(2_542_026 / 6_135_126) and r["proration_how"] == "accepted/tendered"
    assert r["pct_tendered"] == 60.34


def test_accepted_count_phrasings():
    # AGC 2017, 0001391461-17-000002; Voya PPR 2021, 0001193125-21-003312
    a = C.parse_tender_result("2. 14,817,666 Common Shares of the Fund were validly tendered and not withdrawn prior to "
                              "the expiration of the Offer, and 4,829,532 of those Common Shares were accepted for "
                              "repurchase by the Fund")
    assert a["proration"] == pytest.approx(4_829_532 / 14_817_666)
    b = C.parse_tender_result("2. 88,416,006.334 Shares of the Trust were validly tendered and not withdrawn prior to "
                              "the expiration of the Offer, and 21,576,552 Shares were accepted for repurchase")
    assert b["proration"] == pytest.approx(21_576_552 / 88_416_006)


@pytest.mark.parametrize("t", [
    # GIM 2021, 0001680359-21-000268
    "In accordance with the terms of the tender offer, the Fund has accepted for purchase all shares properly tendered",
    # GCH 2013, 0000891836-13-000051
    "The Fund accepted all properly tendered and not withdrawn shares for payment at $13.32 per share",
    # PCF 2019, 0000894189-19-001693
    "allowing the Fund to purchase additional shares not to exceed 2% of the outstanding shares, the Fund has elected "
    "to purchase all shares tendered at a price of $9.25 per Share",
])
def test_all_accepted_phrasings(t):
    r = C.parse_tender_result(t)
    assert r["proration"] == 1.0 and r["proration_how"] == "all accepted"


def test_all_accepted_is_not_believed_beside_oversubscription():
    t = ("The offer was oversubscribed. The Fund has accepted for purchase all shares properly tendered by odd-lot "
         "holders and a pro rata portion of the rest")
    assert C.parse_tender_result(t)["proration"] is None


def test_ticker_factor_in_a_two_fund_release():
    # DHG/LBF 2010, 0000088053-10-001620
    t = ("Under the final pro-ration calculation, 53.5926% of the DHG shares that were tendered and 75.1792% of the LBF "
         "shares that were tendered were accepted")
    assert C.parse_tender_result(t, ticker="LBF")["proration"] == pytest.approx(0.751792)
    assert C.parse_tender_result(t, ticker="DHG")["proration"] == pytest.approx(0.535926)


def test_sought_over_tendered_when_oversubscribed_and_no_accepted_count():
    # BrandywineGLOBAL 2020, 0001193125-20-254439 (the sought count here is synthetic)
    t = ("2. 14,111,137 Shares of the Fund were validly tendered and not withdrawn prior to the expiration of the Offer. "
         "Because the Offer was oversubscribed, the Fund purchased a pro rata portion of Shares tendered by each "
         "stockholder.")
    r = C.parse_tender_result(t, sought_shares=3_000_000)
    assert r["proration"] == pytest.approx(3_000_000 / 14_111_137)
    assert r["proration_how"] == "shares sought (offer) / shares tendered (oversubscribed)"
    assert C.parse_tender_result(t)["proration"] is None                     # no sought count: a stated gap


def test_table_row_must_check_itself():
    good = "Pro-Ration Factor Purchase Price 4,678,586 653,807 13.97 % $ 9.81"
    assert C.parse_tender_result(good)["proration"] == pytest.approx(653_807 / 4_678_586)
    bad = "Pro-Ration Factor Purchase Price 4,678,586 653,807 31.97 % $ 9.81"      # factor disagrees with the counts
    assert C.parse_tender_result(bad)["proration"] is None


def test_offer_states_shares_sought():
    p = C.parse_tender_offer(SWZ)
    assert p["sought_shares"] == 4_579_480


# ------------------------------------------------- multi-fund releases (2026-10-18)

VTA_VLT = ("Invesco Dynamic Credit Opportunities Fund (NYSE: VTA) and Invesco High Income Trust II (NYSE: VLT) "
           "(each, a “Fund” and collectively, the “Funds”). Invesco Dynamic Credit Opportunities Fund conducted a "
           "tender offer for cash of up to 11,114,143 of the Fund’s outstanding common shares. approximately "
           "37,165,804 Common Shares, or approximately 50.2% of the Fund’s Common Shares outstanding, were tendered. "
           "The Fund has accepted 11,114,143 shares (subject to adjustment for fractional shares) for cash payment.")
EEA_GF = ("The European Equity Fund, Inc. (NYSE: EEA) and The New Germany Fund, Inc. (NYSE: GF) each announced that EEA "
          "has accepted 529,026, and GF has accepted 863,598, properly tendered shares at 98% of NAV. 5,314,744.107 "
          "shares of EEA’s common stock, or 50.23% of its common stock outstanding, and 10,697,485.001 shares of GF’s "
          "common stock, or 61.94% of its common stock outstanding, were tendered through the stated expiration date. "
          "The tender offers were oversubscribed.")


def test_other_fund_tickers_ignores_the_sponsor():
    t = VTA_VLT + " Invesco Ltd. (NYSE: IVZ) is the adviser."
    assert C.other_fund_tickers(t, "VLT", {"VTA", "VLT", "VVR"}) == {"VTA"}
    assert C.other_fund_tickers("Swiss Helvetia Fund (NYSE: SWZ)", "SWZ", {"SWZ"}) == set()


def test_multi_fund_release_without_an_anchor_is_a_gap():
    # the old code gave VLT these VTA numbers (0.299)
    r = C.parse_tender_result(VTA_VLT, ticker="VLT", multi_fund=True)
    assert r["proration"] is None and r["proration_how"].startswith("multi-fund release")
    assert C.parse_tender_result(VTA_VLT, ticker="VTA")["proration"] == pytest.approx(11_114_143 / 37_165_804)


def test_multi_fund_ticker_anchored_counts():
    gf = C.parse_tender_result(EEA_GF, ticker="GF", multi_fund=True)
    assert gf["proration"] == pytest.approx(863_598 / 10_697_485)            # the old code: 863,598 / 5,314,744
    eea = C.parse_tender_result(EEA_GF, ticker="EEA", multi_fund=True)
    assert eea["proration"] == pytest.approx(529_026 / 5_314_744)


def test_multi_fund_item_block_is_the_funds_own():
    # AGC 2017, 0001391461-17-000002: the amendment body, then a joint AVK/AGC release
    t = ("The following information is furnished pursuant to Rule 13e-4(c)(4): 1. The Offer expired. 2. 14,817,666 "
         "Common Shares of the Fund were validly tendered and not withdrawn prior to the expiration of the Offer, and "
         "4,829,532 of those Common Shares were accepted for repurchase by the Fund. EXHIBIT (NYSE: AVK) (NYSE: AGC) "
         "approximately 8,775,224 Shares of AVK were tendered and 3,537,132 Shares were accepted")
    r = C.parse_tender_result(t, ticker="AGC", multi_fund=True)
    assert r["proration"] == pytest.approx(4_829_532 / 14_817_666)
    assert r["proration_how"] == "accepted/tendered (fund-anchored, multi-fund release)"


def test_conflicting_statements_are_a_gap():
    # IRL 2017, the New Ireland Fund's final amendment
    t = ("the Fund has accepted 1,601,285 shares for payment on or about May 12, 2017. A total of approximately "
         "1,601,285 shares or approximately 30% of the Fund’s issued and outstanding shares of common stock were "
         "properly tendered and not withdrawn. Consistent with the terms of the offer, on a pro rated basis, "
         "approximately 64.75% of the shares properly tendered by each stockholder have been accepted for payment.")
    r = C.parse_tender_result(t)
    assert r["proration"] is None and r["proration_how"].startswith("conflicting statements")


def test_strip_binary_and_a_bare_parenthetical_is_not_an_offer_size():
    raw = "Offer text.\nbegin 644 g1.jpg\nM(2%)XYZ\nend\nThe offer is for up to 25% of its outstanding shares."
    assert "(2%)" not in C.strip_binary(raw) and "up to 25%" in C.strip_binary(raw)
    jpt = ("dividends (37%) exceeds the maximum tax rate on net capital gains (20%). The Fund is offering to purchase "
           "up to 100% of its outstanding Common Shares at 100% of net asset value. Listed on the NYSE.")
    assert C.parse_tender_offer(jpt)["size_pct"] == 100.0
    assert C.parse_tender_offer(SWZ)["size_pct"] == 15.0


def test_mode_tie_goes_to_the_first_in_the_document():
    assert C._mode([15.0, 5.0]) == 15.0                 # IRL 2012: the old tie-break gave 5.0
    assert C._mode([5.0, 15.0, 15.0]) == 15.0
    assert C._mode([]) is None


def test_unknown_own_ticker_needs_two_fund_tickers_for_a_joint_release():
    assert C.other_fund_tickers("The Malaysia Fund, Inc. (NYSE: MAY) announced", None, {"MAY"}) == set()
    assert C.other_fund_tickers("(NYSE: VTA) and (NYSE: VLT)", None, {"VTA", "VLT"}) == {"VTA", "VLT"}


def test_stated_price_on_the_nav_date():
    t = ("On June 19, 2012, the Fund's net asset value per share was $4.36 and the last reported sale price of the "
         "shares on the NYSE was $3.92. On June 20, 2012 the market price was $9.99.")
    px, sp = C.stated_price_on(t, pd.Timestamp("2012-06-19"))
    assert px == 3.92 and "3.92" in sp
    assert C.stated_price_on(t, pd.Timestamp("2012-07-01")) == (None, None)
    assert C.stated_price_on(t, None) == (None, None)


def test_nuveen_share_table_reads_the_same_column():
    # JMLP 2018, 0001193125-19-030298: the old pair rule returned 9.19 (JMF's share price)
    t = ("the Funds’ share prices were trading at a premium/(discount) to their NAVs as shown in the accompanying "
         "table. JMF JMLP NAV $ 9.98 $ 6.92 Share price $ 9.19 $ 6.24 Premium/(Discount) (7.92)% (9.83)%")
    h = C.nav_beside_price(t, 6.24)
    assert h["nav"] == 6.92 and h["layout"] == "row2"
    assert C.nav_beside_price(t, 9.19)["nav"] == 9.98


def test_pair_rule_refuses_a_number_in_a_price_row():
    t = "Net Asset Value per share is shown above. Share price $ 9.19 $ 6.24"
    assert C.nav_beside_price(t, 6.24) is None
    ok = "Net Asset Value (NAV) ** Market Price 1 Year 22.62 % 29.16 % Price per share at December 31, 2016 $ 7.86 $ 7.20 *"
    assert C.nav_beside_price(ok, 7.20)["nav"] == 7.86


def test_tortoise_highlights_read_by_column():
    # NDP 2022 semi-annual: the old pair rule took 27.59 (the previous column of the PRICE row)
    t = ("Net asset value per common share (2) 20.67 23.06 22.00 25.13 31.77 38.68 Market value per common share (2) "
         "17.74 19.88 19.49 22.24 27.59 32.47 Shares outstanding")
    h = C.nav_beside_price(t, 32.47)
    assert h["nav"] == 38.68 and h["layout"] == "row2"


@pytest.mark.parametrize("t,close", [
    # SGF 2011 annual report: a price CHANGE, not NAV beside price
    ("Net asset value rose. Market price fell. The Fund's share price decreased 22.75% over the twelve months, from "
     "$16.31 on October 31, 2010 to $12.60 on October 31, 2011.", 12.60),
    # HIX 2020: a total return beside the NAV
    ("NAV and Market Price. Performance Snapshot as of April 30, 2020 Price Per Share 12-Month Total Return** $ 6.19 "
     "(NAV) -8.11 %† $ 5.51 (Mkt)", 5.51),
    # FAM 2016: a monthly high/low table
    ("NAV Market Price 4/16 11.09 12.50 10.97 12.29 11.08 12.33 11.02 12.22 5/16 11.08 12.24 11.08 12.38 11.31 12.48 "
     "11.10 12.42 11.16 12.43", 11.16),
])
def test_pair_rule_refuses_non_adjacent_and_table_reads(t, close):
    assert C.nav_beside_price(t, close) is None


def test_sentence_layouts():
    a = C.nav_beside_price("As of June 30, 2010, the Fund’s NAV was $14.26, and its market price was $13.40.", 13.40)
    assert a["nav"] == 14.26 and a["layout"] == "sentence"
    b = C.nav_beside_price("Price Per Share Total Return* $9.72 (NAV) 32.2 % 0.1 % $8.50 (Market Price)", 8.50)
    assert b["nav"] == 9.72 and b["layout"] == "sentence"
    c = C.nav_beside_price("Snapshot $ 6.19 (NAV) -8.11 %† $ 5.51 (Market Price)", 5.51)
    assert c["nav"] == 6.19
