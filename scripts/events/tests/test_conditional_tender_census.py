"""The parsers and checks behind the conditional-tender census (idea N1), on literal strings and synthetic frames.

WHY THESE TESTS
---------------
The census turns ~45 filings into ~200 coded windows. Every way it could go
wrong silently has a test here:

  * `parse_pct` / `parse_dmp_table`: BlackRock prints a discount three ways
    ("-8.81%", "-8.81 %", "(8.17)%") and a premium as a bare "3.30%". A parser
    that reads "(8.17)%" as +8.17 turns a discount into a premium and a
    non-trigger into nothing at all; the 2026 table (MHD, MQY) uses exactly
    that format.
  * `normalise` / `quote_in`: the evidence check must survive curly quotes,
    en-dash minus signs ("–9.06%"), "-10.51 %" and "- 10.17%", and must NOT
    match a different number.
  * `is_triggered`: "more than 10%" and "10% or greater" differ exactly at the
    threshold; EEA's 2014 average of -9.9996888% must not trigger.
  * `check_inferred` counts only SC TO-I (a tender actually commenced): NRO
    filed the NEXT window's announcement as an SC TO-C inside 180 days.
  * `known_before_start`: the Delaware funds' windows end on a date the board
    never publishes in advance, so they are never "known before start".
  * `account_for_hits` raises on a flagged fund that is neither coded nor
    excluded, so a discovery hit cannot vanish.
  * `running_average` is causal: the value at t uses sessions <= t only.
  * `dedupe_agreeing` drops equal duplicate rows and raises on unequal ones.
  * The curated table's own integrity (no network).

Each test of a parser was checked to FAIL against the naive version it guards
(a float() of the stripped string; a plain substring match; counting SC TO-C;
a strict ">" for ">="). Synthetic inputs test the code, not the market. No
network: the root conftest blocks it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import conditional_tender_census as C
from scripts.events import conditional_tender_programmes as P


# ------------------------------------------------------------------ parse_pct

@pytest.mark.parametrize("s,v", [("-8.81%", -8.81), ("-8.81 %", -8.81), ("(8.17)%", -8.17), ("(2.74)%", -2.74),
                                 ("3.30%", 3.30), ("0.25%", 0.25), ("-10.00%", -10.0), ("(11.05)%", -11.05)])
def test_parse_pct_formats(s, v):
    assert C.parse_pct(s) == pytest.approx(v)


@pytest.mark.parametrize("bad", ["(8.17%", "8.17)%", "abc%", "8.17", ""])
def test_parse_pct_rejects(bad):
    with pytest.raises(ValueError):
        C.parse_pct(bad)


# ------------------------------------------------------------ parse_dmp_table

TABLE_2024 = ("Quarterly Measurement Period Discount Results for the Funds in the Program Fund Name Ticker Average Daily "
              "Discount for the Measurement Period ended June 30, 2024 BlackRock Capital Allocation Term Trust BCAT -8.81% "
              "BlackRock Health Sciences Term Trust BMEZ -14.17 % BlackRock Science and Technology Trust BST -2.11% "
              "BlackRock MuniVest Fund, Inc. MVF -11.75% BlackRock Utilities, Infrastructure, & Power Opportunities Trust "
              "BUI 0.25% The Funds’ Boards of Directors/Trustees (the “Boards”) determined that if a Trigger Event "
              "occurred ... a tender offer for 2.5% of its outstanding common shares at a price equal to 98% of NAV")
TABLE_2026 = ("Measurement Period Results for the Funds in the Program Fund Name Ticker Average Daily Premium/(Discount) "
              "for the Measurement Period ended September 30, 2026 BlackRock Capital Allocation Term Trust BCAT 3.30% "
              "BlackRock ESG Capital Allocation Term Trust ECAT (2.74)% BlackRock Health Sciences Term Trust BMEZ (11.05)% "
              "BlackRock MuniHoldings Fund, Inc. MHD (8.17)% BlackRock MuniYield Quality Fund, Inc. MQY (7.41)% "
              "1 Based on BMEZ’s average daily discount during the Measurement Period, the Fund will conduct a tender "
              "offer for up to 5% of the Fund’s outstanding common shares")


def test_dmp_table_2024_format():
    t = C.parse_dmp_table(TABLE_2024)
    assert t == {"BCAT": -8.81, "BMEZ": -14.17, "BST": -2.11, "MVF": -11.75, "BUI": 0.25}


def test_dmp_table_2026_parentheses_are_discounts():
    t = C.parse_dmp_table(TABLE_2026)
    assert t == {"BCAT": 3.30, "ECAT": -2.74, "BMEZ": -11.05, "MHD": -8.17, "MQY": -7.41}
    # the footnote's "5%" after the table must not be read as a row
    assert all(k in ("BCAT", "ECAT", "BMEZ", "MHD", "MQY") for k in t)


def test_dmp_table_errors():
    with pytest.raises(ValueError, match="no DMP results table"):
        C.parse_dmp_table("nothing to see")
    with pytest.raises(ValueError, match="twice"):
        C.parse_dmp_table("Discount Results for the Funds X BCAT -8.81% Y BCAT -7.00% The Funds’ Boards")
    with pytest.raises(ValueError, match="no ticker rows"):
        C.parse_dmp_table("Discount Results for the Funds nothing here The Funds’ Boards")


# --------------------------------------------------------- normalise/quote_in

def test_quote_matching_survives_typography_but_not_numbers():
    doc = ("shares of common stock of GF had traded at an average discount to NAV of –9.06%, in each case; "
           "EEA had traded at an average discount to net asset value (“NAV”) of -10.17% and GF ... of -10.51 % "
           "and the Fund traded at an average discount to NAV of - 10.17%. The Fund’s shares")
    assert C.quote_in(doc, "GF had traded at an average discount to NAV of -9.06%")
    assert C.quote_in(doc, 'net asset value ("NAV") of -10.17%')
    assert C.quote_in(doc, "of -10.51%")
    assert C.quote_in(doc, "average discount to NAV of -10.17%")
    assert C.quote_in(doc, "THE FUND'S SHARES")
    assert not C.quote_in(doc, "GF had traded at an average discount to NAV of -9.07%")
    with pytest.raises(ValueError):
        C.quote_in(doc, "  ")


def test_plain_strips_tags_and_entities():
    # a non-breaking space is whitespace to the regex, so it collapses like any other
    assert C.plain("<p>The&nbsp;Fund&#8217;s <b>shares</b>\n traded</p>") == "The Fund’s shares traded"


# ---------------------------------------------------------------- is_triggered

def test_threshold_comparators():
    assert C.is_triggered(-10.01, 10.0, ">")
    assert not C.is_triggered(-10.0, 10.0, ">")
    assert C.is_triggered(-10.0, 10.0, ">=")
    assert not C.is_triggered(-9.9996888, 10.0, ">")     # EEA, 2014-06-27
    assert not C.is_triggered(3.30, 10.0, ">")           # a premium never triggers
    with pytest.raises(ValueError):
        C.is_triggered(-11, 10, "=>")


# ------------------------------------------------------------ discovery rules

def test_discovery_rules():
    dgf = ("the Board committed to conduct an annual tender offer if Shares have traded at an average discount "
           "from NAV of more than 3% as of the last trading day in each week during such twelve-week period")
    assert C.is_candidate(C.score(dgf))                   # the sentence rule; V1 has no window word here
    nb = ("if a Fund's common stock trades at an average daily discount to net asset value of greater than 10% "
          "during a 12-week measurement period")
    assert C.is_candidate(C.score(nb))
    routine = "The Fund will purchase up to 5% of its shares at 98% of NAV. The offer expires on May 1."
    assert not C.is_candidate(C.score(routine))


def test_every_flagged_fund_must_be_accounted_for():
    known = next(iter(P.EXCLUDED))
    ok = pd.DataFrame({"cik": [known, 1261166, 999999999], "company": ["x", "NRO", "zzz"],
                       "accession": ["a", "b", "c"], "candidate": [True, True, False]})
    out = C.account_for_hits(ok)
    assert out["disposition"].iloc[0].startswith("excluded") and out["disposition"].iloc[1] == "census"
    assert out["disposition"].iloc[2] == "not a candidate"
    bad = ok.assign(candidate=[True, True, True])
    with pytest.raises(RuntimeError, match="neither in the census nor excluded"):
        C.account_for_hits(bad)


# --------------------------------------------------------------- check_inferred

def _filings(rows):
    return pd.DataFrame(rows, columns=["cik", "form", "date_filed"]).assign(date_filed=lambda d: pd.to_datetime(d["date_filed"]))


def test_inferred_non_trigger_ignores_next_window_announcements():
    w = [P.W("NB-NRO-2016", "NRO", "2017-01-03", "2017-03-28", "not_triggered_inferred")]
    # an SC TO-C announcing the next window is not a tender
    assert len(C.check_inferred(_filings([(1261166, "SC TO-C", "2017-06-30")]), w)) == 1
    # an SC TO-I inside the horizon contradicts the inference
    with pytest.raises(AssertionError, match="not_triggered_inferred"):
        C.check_inferred(_filings([(1261166, "SC TO-I", "2017-05-01")]), w)
    # one after the horizon does not
    assert len(C.check_inferred(_filings([(1261166, "SC TO-I", "2017-12-01")]), w)) == 1


# ---------------------------------------------------------- known_before_start

def test_known_before_start_rules():
    prog = {p["pid"]: p for p in P.PROGRAMMES}
    filed = {(1261166, "0000898432-17-000688"): pd.Timestamp("2017-06-30")}
    nro_w = P.W("NB-NRO-2016", "NRO", "2017-07-10", "2017-10-02", "not_triggered",
                wev=(1261166, "0000898432-17-000688", "x"))
    assert C.known_before_start(prog["NB-NRO-2016"], nro_w, filed) is True
    # announced after the window began, nothing earlier
    w16 = P.W("NB-NRO-2016", "NRO", "2015-12-31", "2016-09-30", "triggered")
    assert C.known_before_start(prog["NB-NRO-2016"], w16, filed) is False
    # Delaware: the end date is never published in advance
    dex = P.W("DEL-DEX-2018", "DEX", "2020-01-01", "2020-06-30", "not_triggered_inferred")
    assert C.known_before_start(prog["DEL-DEX-2018"], dex, filed) is False
    # a fixed-date programme announced before the window
    ev = P.W("EV-2021", "EFT", "2022-01-01", "2022-08-31", "not_triggered_inferred")
    assert C.known_before_start(prog["EV-2021"], ev, filed) is True
    # no announcement date, no window evidence: not shown either way
    dws = P.W("DWS-2010", "EEA", "2010-09-01", "2010-11-24", "triggered")
    assert C.known_before_start(prog["DWS-2010"], dws, filed) is None
    # a cited filing missing from the index is an error, not a guess
    with pytest.raises(KeyError):
        C.known_before_start(prog["NB-NRO-2016"], nro_w, {})


# ------------------------------------------------------- the panel arithmetic

def test_window_discount_and_running_average_are_causal():
    days = pd.bdate_range("2024-01-02", periods=6)
    px = pd.Series([9.0, 9.0, 9.0, 9.5, 9.0, 8.0], index=days)
    nav = pd.Series([10.0, 10.0, np.nan, 10.0, 10.0, 10.0], index=days)
    r = C.window_discount(px, nav, days)
    assert r["sessions"] == 6 and r["days_both"] == 5 and r["coverage"] == pytest.approx(5 / 6)
    assert r["mean_disc_pct"] == pytest.approx(np.mean([-10, -10, -5, -10, -20]))
    ra = C.running_average(px, nav, days)
    disc = ra["discount_pct"].to_numpy()
    for k in range(len(ra)):
        assert ra["running_avg_pct"].iloc[k] == pytest.approx(disc[: k + 1].mean())   # uses sessions <= t only


def test_dedupe_agreeing():
    d = pd.DataFrame({"ticker": ["A", "A", "B"], "date": pd.to_datetime(["2025-01-03"] * 3),
                      "nav": [10.0, 10.0, 5.0], "close_cc": [9.0, 9.0, 4.0]})
    assert len(C.dedupe_agreeing(d, ["nav", "close_cc"])) == 2
    with pytest.raises(ValueError, match="different values"):
        C.dedupe_agreeing(d.assign(nav=[10.0, 10.5, 5.0]), ["nav", "close_cc"])


# ----------------------------------------------------- the curated table itself

def test_curated_table_integrity():
    pids = {p["pid"] for p in P.PROGRAMMES}
    assert len(pids) == len(P.PROGRAMMES), "duplicate programme id"
    for p in P.PROGRAMMES:
        assert p["basis"] in P.BASES and isinstance(p["fixed_dates"], bool)
        assert p["cmp"] in (">", ">=", None)
    for w in P.WINDOWS + P.EXTRA_BLK_WINDOWS:
        assert w["pid"] in pids and w["outcome"] in P.OUTCOMES
        if w["outcome"] in P.DOCUMENTED + ("triggered_inferred", "withdrawn", "waived", "suspended"):
            assert w["ev"] is not None, f"{w['pid']} {w['ticker']}: a stated outcome needs its quote"
        if w["avg"] is not None:
            assert w["ev"] is not None
        if w["start"] and w["end"]:
            assert w["start"] < w["end"]
    for pid, *_ in P.TABLES:
        assert pid in pids or pid == "BLK-2026"
    assert set(P.BLK_2026_ROUTE.values()) <= pids
    census = C.census_ciks()
    assert not (census & set(P.EXCLUDED)), "a fund is both in the census and excluded"
