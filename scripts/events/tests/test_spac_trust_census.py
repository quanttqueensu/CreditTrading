"""Tests for the SPAC trust-value census (scripts/events/spac_trust_census.py).

Synthetic filing lists and strings only: these test the METHOD (how a SPAC's
life is dated from its forms, how a trust figure is read, what the yield
arithmetic is), never a claim about the market. Nothing here opens a socket
(the root conftest blocks the network).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scripts.events import spac_trust_census as S

TODAY = date(2026, 10, 15)


def filings(rows):
    """rows: (date, form, items) -> the frame spac_events reads."""
    return pd.DataFrame({"filingDate": pd.to_datetime([r[0] for r in rows]), "form": [r[1] for r in rows],
                         "items": [r[2] if len(r) > 2 else "" for r in rows],
                         "accessionNumber": [f"0000000000-26-{i:06d}" for i in range(len(rows))]})


# ------------------------------------------------------------------ events

def test_completion_by_item_201_without_506_is_a_deal_not_a_liquidation():
    # M III Acquisition (CIK 1652362): the 2018 closing 8-K carries 2.01 but not
    # 5.06, and a 25-NSE (warrants/units) is filed around the closing. A
    # 5.06-only rule called this a liquidation.
    f = filings([("2016-07-08", "424B4"), ("2016-08-12", "10-Q"), ("2018-03-21", "8-K", "3.02,5.07,8.01,9.01"),
                 ("2018-03-27", "25-NSE"), ("2018-03-29", "8-K", "1.01,2.01,3.03,5.02,9.01"),
                 ("2018-04-03", "15-12B"), ("2018-05-10", "10-Q"), ("2026-08-10", "10-Q")])
    e = S.spac_events(f, TODAY)
    assert e["status"] == "completed"
    assert e["completion_date"] == date(2018, 3, 29)
    assert e["completion_rule"] == "8k_2.01_or_5.06"
    # the deal-vote 8-K (5.07) before completion is a vote candidate
    assert len(e["vote_8ks"]) == 1


def test_liquidation_is_termination_with_no_later_periodic_report():
    f = filings([("2021-03-01", "424B4"), ("2021-05-10", "10-Q"), ("2022-12-01", "8-K", "8.01,9.01"),
                 ("2022-12-12", "25-NSE"), ("2023-02-15", "10-K")])   # the 10-K inside the grace period
    e = S.spac_events(f, TODAY)
    assert e["status"] == "liquidated"
    assert e["termination_date"] == date(2022, 12, 12)
    assert e["completion_date"] is None


def test_delisted_but_still_reporting_is_not_liquidated():
    f = filings([("2021-03-01", "424B4"), ("2023-06-01", "25-NSE"), ("2024-08-01", "10-Q"), ("2026-08-12", "10-Q")])
    assert S.spac_events(f, TODAY)["status"] == "delisted_alive"


def test_holdco_completion_needs_a_425_and_a_change_in_control_at_delisting():
    base = [("2020-10-01", "424B4"), ("2020-11-10", "10-Q"), ("2021-05-01", "425"),
            ("2021-09-30", "8-K", "3.01,3.03,5.01,9.01"), ("2021-10-01", "25-NSE")]
    e = S.spac_events(filings(base), TODAY)
    assert e["status"] == "completed" and e["completion_rule"] == "holdco_5.01_at_delisting"
    # Without the 425 the same forms are a liquidation (a 5.01 alone can be a sponsor sale).
    no425 = [r for r in base if r[1] != "425"]
    assert S.spac_events(filings(no425), TODAY)["status"] == "liquidated"


def test_sponsor_change_of_control_without_delisting_stays_live():
    f = filings([("2025-01-10", "424B4"), ("2025-05-10", "10-Q"), ("2026-03-01", "8-K", "5.01,5.02"),
                 ("2026-08-10", "10-Q")])
    e = S.spac_events(f, TODAY)
    assert e["status"] == "live" and e["completion_date"] is None


def test_recent_ipo_without_a_10q_is_live_and_old_silent_one_is_dormant():
    assert S.spac_events(filings([("2026-09-01", "424B4")]), TODAY)["status"] == "live"
    assert S.spac_events(filings([("2024-01-10", "424B4"), ("2024-05-01", "10-Q")]), TODAY)["status"] == "dormant"


def test_pre_2010_prospectus_is_out_of_scope():
    assert S.spac_events(filings([("2007-05-01", "424B4")]), TODAY)["status"] == "no_ipo_in_scope"


def test_events_raise_on_missing_columns():
    with pytest.raises(S.CensusError):
        S.spac_events(pd.DataFrame({"form": ["424B4"]}), TODAY)


def test_year_counts_and_live_at():
    ev = pd.DataFrame({
        "cik": [1, 2, 3],
        "ipo_date": [date(2020, 1, 5), date(2021, 2, 1), date(2021, 3, 1)],
        "announce_date": [date(2020, 9, 1), None, None],
        "completion_date": [date(2021, 1, 10), None, None],
        "termination_date": [None, date(2023, 2, 1), None],
        "status": ["completed", "liquidated", "live"],
        "ext_dates": [[], [date(2022, 12, 1), date(2022, 6, 1)], [date(2023, 1, 5)]],
    })
    yc = S.year_counts(ev, years=range(2020, 2024)).set_index("year")
    assert yc.loc[2020, "ipos"] == 1 and yc.loc[2021, "ipos"] == 2
    assert yc.loc[2021, "deals_completed"] == 1 and yc.loc[2023, "liquidations"] == 1
    assert yc.loc[2022, "extension_votes"] == 2 and yc.loc[2022, "spacs_with_extension_vote"] == 1
    assert S.live_at(ev, pd.Timestamp("2022-01-01")) == 2      # 2 and 3; 1 had completed
    assert S.live_at(ev, pd.Timestamp("2024-01-01")) == 1      # only the live one


# ------------------------------------------------------------------ text rules

def test_extension_and_liquidation_texts():
    assert S.is_extension_text("Shareholders approved the Extension Amendment Proposal to extend the date by "
                               "which the Company must consummate a business combination.")
    assert not S.is_extension_text("Shareholders elected three directors and ratified the auditor.")
    # deal-vote boilerplate (Cerberus Telecom, CIK 1824577) is not an extension vote
    assert not S.is_extension_text("the risk that the transaction may not be completed by CTAC's business "
                                   "combination deadline and the potential failure to obtain an extension of "
                                   "the business combination deadline if sought by CTAC")
    assert S.is_extension_text("to extend the date by which the Company must consummate a business combination "
                               "up to twelve (12) times")
    assert S.is_liquidation_text("The Company will redeem all of the outstanding public shares because it "
                                 "will not consummate an initial business combination within the time period.")
    assert not S.is_liquidation_text("The Company entered into a business combination agreement.")


def test_per_share_prices_keep_only_trust_range():
    t = "approximately $10.52 per share ... of $0.10 per public share ... approximately $11.50 per share"
    assert S.per_share_prices(t) == [10.52, 11.5]


def test_base_deadline_months_is_the_modal_window():
    t = ("24 months from the closing of this offering ... 24 months from the closing of this offering ... "
         "(or 27 months from the closing of this offering if we have signed a definitive agreement) ... "
         "twenty-four months from the closing of this offering")
    assert S.months_from_ipo(t) == [24, 24, 27, 24]
    assert S.base_deadline_months(t) == 24
    assert S.base_deadline_months("no such phrase") is None


def test_deadline_candidates_need_business_combination_context():
    t = ("If we have not completed our initial business combination by March 1, 2027 (or September 1, 2027 if "
         "extended), we will redeem. Our lease ends on December 31, 2027.")
    assert S.deadline_candidates(t, date(2026, 10, 1)) == [date(2027, 3, 1), date(2027, 9, 1)]


def test_redemption_value_and_share_count_from_10q_text():
    t = ("Class A ordinary shares subject to possible redemption, $ 0.0001 par value; 46,000,000 shares at "
         "redemption value of approximately $ 10.29 and 10.10 per share at June 30, 2026 and December 31, 2025")
    assert S.text_redemption_value(t) == [10.29]
    assert S.text_redeemable_shares(t) == [46_000_000]
    t2 = "25,300,000 shares issued and outstanding subject to possible redemption, at redemption value"
    assert S.text_redeemable_shares(t2) == [25_300_000]


def test_redemption_value_first_10q_and_other_live_forms():
    # The first 10-Q after an IPO prints the prior period as "$ 0": missed before
    # 2026-10-18, which left two live SPACs on a wrong XBRL share count.
    t = ("Class A Ordinary Shares subject to possible redemption, $ 0.0001 par value; 20,125,000 and no shares "
         "at redemption value of $ 10.02 and $ 0 per share as of June 30, 2026 and December 31, 2025, respectively")
    assert S.text_redemption_value(t) == [10.02]
    assert S.text_redeemable_shares(t) == [20_125_000]
    t2 = "17,250,000 shares and no shares at a redemption value of $ 10.11 and $ 0 per share as of June 30, 2026"
    assert S.text_redemption_value(t2) == [10.11] and S.text_redeemable_shares(t2) == [17_250_000]
    t3 = "25,800,000 shares at $ 10.60 and $ 10.42 per share redemption value as of June 30, 2026"
    assert S.text_redemption_value(t3) == [10.60] and S.text_redeemable_shares(t3) == [25_800_000]
    t4 = "1,040,332 shares issued and outstanding at redemption value of $ 12.00 and $ 11.63 as of June 30, 2026"
    assert S.text_redemption_value(t4) == [12.00]
    # a dollar total is not a per-share value
    assert S.text_redemption_value("11,500,000 shares at redemption value $ 115,226,525") == []


def test_ipo_close_date_and_months_from_close():
    t = ("On October 1, 2025, the Company consummated the Initial Public Offering of 46,000,000 units. "
         "within 24 months from the closing of the Initial Public Offering (or 27 months from the closing of "
         "the Initial Public Offering if ...)")
    assert S.ipo_close_date(t) == date(2025, 10, 1)
    assert S.months_from_close(t) == [24, 27]


def test_trust_per_unit_at_ipo_reads_the_trust_sentence():
    t = ("An aggregate of $230,000,000, or $10.00 per unit, will be deposited into a trust account. "
         "The underwriters receive $0.20 per unit. Each warrant at $11.50 per share. "
         "$10.00 per unit held in the trust account.")
    assert S.trust_per_unit_at_ipo(t) == 10.0
    assert S.trust_per_unit_at_ipo("no trust language here, $10.00 per unit") is None


def test_spac_prospectus_rule():
    cover = "This is an initial public offering of units. Proceeds go into a trust account. "
    body = "trust account business combination " * 6
    assert S.is_spac_prospectus(cover + body)
    assert not S.is_spac_prospectus("This is an initial public offering of common stock. " + "business combination " * 9)
    # a de-SPAC's resale prospectus: trust account in the body, not on the cover
    assert not S.is_spac_prospectus("Resale prospectus. " + "x" * S.COVER_CHARS + body)


# ------------------------------------------------------------------ XBRL trust

def _facts(points):
    """points: concept -> list of (end, val, filed)."""
    return {"facts": {"us-gaap": {c: {"units": {"USD/shares" if "PerShare" in c else "USD": [
        {"end": e, "val": v, "filed": f, "form": "10-Q", "accn": f"a{i}"} for i, (e, v, f) in enumerate(pts)]}}
        for c, pts in points.items()}}}


def test_trust_series_merges_concepts_and_counts_conflicts():
    f = _facts({"AssetsHeldInTrustNoncurrent": [("2025-06-30", 100.0, "2025-08-10")],
                "AssetsHeldInTrustCurrent": [("2025-06-30", 101.0, "2025-08-10"), ("2025-09-30", 102.0, "2025-11-10")]})
    ts = S.trust_series(f)
    assert list(ts["trust"]) == [101.0, 102.0]
    assert list(ts["n_conflict"]) == [1, 0]


def test_trust_ps_at_uses_only_facts_filed_by_the_date():
    f = _facts({"AssetsHeldInTrustNoncurrent": [("2020-03-31", 100.0, "2020-05-10"),
                                                ("2020-06-30", 101.0, "2020-08-10"),
                                                ("2020-09-30", 130.0, "2020-11-10")]})
    # IPO 2020-01-15: t1 must be >= IPO + 45 days -> 2020-03-31.
    r = S.trust_ps_at(f, date(2020, 1, 15), 10.0, date(2020, 10, 1))
    # the 2020-09-30 balance sheet was filed 2020-11-10: not known on 2020-10-01
    assert r["ok"] and r["t"] == date(2020, 6, 30) and r["trust_ps"] == pytest.approx(10.10)
    # once it is known, the 30% jump is a changed share count, not interest: refused
    r2 = S.trust_ps_at(f, date(2020, 1, 15), 10.0, date(2020, 12, 1))
    assert not r2["ok"] and r2["why"] == "trust_changed" and r2["trust_ps"] is None


def test_price_at_takes_last_row_and_flags_quote_midpoints():
    px = pd.DataFrame({"date": pd.to_datetime(["2020-09-28", "2020-09-29", "2020-10-02"]),
                       "prc": [9.9, -9.95, 10.0]})
    r = S.price_at(px, date(2020, 10, 1))
    assert r["price"] == 9.95 and r["traded"] is False and r["stale_days"] == 2


def test_hist_levels_never_builds_a_holdout_row():
    sp = pd.DataFrame({"cik": [1], "ipo_date": [date(2021, 6, 1)], "base_months": [24], "t0": [10.0],
                       "permno": [5], "completion_date": [None], "termination_date": [None]})
    out = S.hist_levels(sp, lambda c: _facts({}), pd.DataFrame(columns=["permno", "date", "prc"]), 3)
    assert out.empty   # 2023-06-01 - 3 months = 2023-03-01 >= 2023-01-01


# ------------------------------------------------------------------ yield, Alpaca, sampling, links

def test_terms_yield_arithmetic():
    r = S.terms_yield(10.0, 10.2, date(2026, 10, 15), date(2027, 10, 15))
    assert r["discount"] == pytest.approx(10.0 / 10.2 - 1)
    assert r["gain"] == pytest.approx(0.02) and r["days"] == 365
    assert r["simple"] == pytest.approx(0.02) and r["compound"] == pytest.approx(0.02)
    with pytest.raises(ValueError):
        S.terms_yield(10.0, 10.2, date(2026, 10, 15), date(2026, 10, 15))
    with pytest.raises(ValueError):
        S.terms_yield(0.0, 10.2, date(2026, 10, 15), date(2027, 1, 1))


def test_alpaca_kind_and_common_symbol():
    assert S.alpaca_kind("XYZ Acquisition Corp. Units") == "unit"
    assert S.alpaca_kind("XYZ Acquisition Corp WT EXP 01/14/2026") == "warrant"
    assert S.alpaca_kind("AIB Acquisition Corporation Rights") == "right"
    assert S.alpaca_kind("XYZ Acquisition Corp Class A Ordinary Shares") == "share"
    assets = {"XYZ": {"name": "XYZ Acquisition Corp Class A Ordinary Shares", "tradable": True, "exchange": "NASDAQ"},
              "XYZU": {"name": "XYZ Acquisition Corp Units", "tradable": True, "exchange": "NASDAQ"},
              "XYZW": {"name": "XYZ Acquisition Corp Warrants", "tradable": True, "exchange": "NASDAQ"}}
    r = S.common_symbol(["XYZU", "XYZ", "XYZW"], assets)
    assert r["symbol"] == "XYZ" and r["n_share_tickers"] == 1
    assert S.common_symbol(["XYZU"], assets) is None


def test_liquidity_counts_untraded_sessions_as_zero():
    sess = list(pd.bdate_range("2026-07-01", periods=5))
    bars = pd.DataFrame({"symbol": ["A", "A"], "date": [sess[1], sess[4]], "c": [10.0, 10.1], "v": [1000.0, 0.0]})
    r = S.liquidity(bars, sess, n=5).iloc[0]
    assert r["adv_usd_mean"] == pytest.approx(10.0 * 1000 / 5)
    assert r["adv_usd_median"] == 0.0 and r["sessions_traded"] == 1 and r["last_close"] == 10.1
    with pytest.raises(S.CensusError):
        S.liquidity(bars.assign(date=[sess[1], pd.Timestamp("2026-07-04")]), sess, n=5)


def test_declared_order_is_deterministic_and_content_blind():
    a = S.declared_order([3, 1, 2])
    assert a == S.declared_order([2, 3, 1]) and sorted(a) == [1, 2, 3]


def test_name_link_joins_crsp_initials_and_refuses_ties():
    assert S.norm_name("C F FINANCE ACQUISITION CORP II") == S.norm_name("CF Finance Acquisition Corp II")
    assert S.name_score("Roth CH Acquisition I Co", "ROTH C H ACQUISITION I CO") == 1.0
    names = pd.DataFrame({"permno": [10, 11, 12], "namedt": pd.to_datetime(["2020-03-01", "2020-03-02", "2020-03-01"]),
                          "comnam": ["ALPHA ACQ CORP", "ALPHA ACQ CORP", "BETA ACQ CORP"], "shrcd": [11, 11, 11]})
    sp = pd.DataFrame({"cik": [1, 2], "ipo_date": [date(2020, 2, 1)] * 2,
                       "ipo_name": ["Alpha Acquisition Corp", "Beta Acquisition Corp"]})
    L = S.link_crsp(sp, names).set_index("cik")
    assert pd.isna(L.loc[1, "permno"])          # two equal candidates: no link
    assert L.loc[2, "permno"] == 12
    # a unit (share code 73) never links
    names_u = names.assign(shrcd=[73, 73, 73])
    assert S.link_crsp(sp, names_u)["permno"].isna().all()


def test_quote_in_normalises_but_keeps_numbers():
    doc = "<p>The cost is $100&nbsp;per client per voluntary corporate action</p>"
    assert S.quote_in(doc, "The cost is $100 per client per voluntary corporate action")
    assert not S.quote_in(doc, "The cost is $150 per client")
    with pytest.raises(ValueError):
        S.quote_in(doc, " ")


def test_filing_doc_url_validates():
    u = S.filing_doc_url(1652362, "0001104659-18-021312", "a18-9134_18k.htm")
    assert u == "https://www.sec.gov/Archives/edgar/data/1652362/000110465918021312/a18-9134_18k.htm"
    with pytest.raises(ValueError):
        S.filing_doc_url(1652362, "0001104659-18-021312", "../x.htm")
    with pytest.raises(ValueError):
        S.filing_doc_url(1652362.5, "0001104659-18-021312", "a.htm")


def test_parse_sic_browse():
    atom = "<feed><entry><cik>0001848507</cik></entry><entry><cik>0001558916</cik></entry></feed>"
    assert S.parse_sic_browse(atom) == [1848507, 1558916]
    with pytest.raises(S.CensusError):
        S.parse_sic_browse("<html>blocked</html>")


def test_frozen_client_never_refetches_a_cached_document(tmp_path):
    # The --frozen mode: a cached copy is used whatever its age, so a run days
    # after the as-of date cannot move the snapshot; a missing one is fetched.
    from scripts.data.edgar_client import EdgarClient, cache_path
    import os
    import time

    class Sess:
        def __init__(self):
            self.urls = []

        def get(self, url, headers=None, timeout=None):
            self.urls.append(url)
            return type("R", (), {"status_code": 200, "content": b"fresh"})()

    sess = Sess()
    c = EdgarClient(user_agent="Test Desk test@example.com", session=sess, cache=tmp_path, sleep=lambda s: None)
    old = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=6770"
    p = cache_path(old, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"snapshot")
    t = time.time() - 10 * 86400
    os.utime(p, (t, t))
    assert c.get(old, max_age_s=86400) == b"fresh"          # unfrozen: a stale copy is re-fetched
    p.write_bytes(b"snapshot")
    os.utime(p, (t, t))
    S.freeze(c)
    assert c.get(old, max_age_s=86400) == b"snapshot"       # frozen: the snapshot stands
    assert c.get_text(old, max_age_s=86400) == "snapshot"
    new = "https://www.sec.gov/Archives/edgar/data/1/000000000026000001/a.htm"
    assert c.get(new) == b"fresh" and sess.urls[-1] == new  # a missing document is still fetched


def test_deal_vote_text_is_the_deal_not_an_extension():
    # Calisa (CIK 2026767): names its Business Combination Proposal, never says "approved".
    assert S.is_deal_vote_text("the Company held an extraordinary general meeting to approve the following "
                               "proposals: a proposal to approve the BCA (the “Business Combination Proposal”)")
    # an extension-only meeting is not a deal vote, even if it names the deal in passing
    assert not S.is_deal_vote_text("Shareholders approved the Extension Amendment Proposal to extend the date by "
                                   "which the Company must consummate a business combination; the merger proposal "
                                   "will be voted on at a later meeting.")
    # one meeting, both proposals, the deal approved: the window was the deal's
    assert S.is_deal_vote_text("The Extension Amendment Proposal and the Business Combination Proposal were "
                               "approved. The stockholders approved the Business Combination Agreement.")


def test_accrued_terms_uses_only_rates_known_by_the_date():
    tb = pd.Series([4.0, 4.0, 5.0, 9.0], index=pd.to_datetime(["2026-07-01", "2026-09-01", "2026-10-14", "2026-10-20"]))
    a = S.accrued_terms(10.0, 10.0, date(2026, 6, 30), date(2026, 10, 15), date(2027, 10, 15), tb)
    assert a["tbill_now"] == pytest.approx(0.05)                      # 2026-10-20's 9% is not yet known
    assert a["tbill_past"] == pytest.approx((4 + 4 + 5) / 3 / 100)
    assert a["trust_ps_accrued"] == pytest.approx(10.0 * (1 + a["tbill_past"] * 107 / 365))
    assert a["spread"] == pytest.approx(a["yield_total"] - 0.05)
    # bought at the accrued trust, the total yield is the bill rate and the spread is zero
    b = S.accrued_terms(a["trust_ps_accrued"], 10.0, date(2026, 6, 30), date(2026, 10, 15), date(2027, 10, 15), tb)
    assert b["spread"] == pytest.approx(0.0, abs=1e-12) and b["discount_accrued"] == pytest.approx(0.0, abs=1e-12)
    with pytest.raises(S.CensusError):
        S.accrued_terms(10.0, 10.0, date(2026, 1, 1), date(2026, 3, 1), date(2027, 1, 1), tb)
    with pytest.raises(ValueError):
        S.accrued_terms(10.0, 10.0, date(2026, 11, 1), date(2026, 10, 15), date(2027, 1, 1), tb)


def test_pick_trust_ps_uses_the_balance_sheet_identity():
    # WLCO-like: a wrong count is read first (an accretion amount), the printed line is consistent
    c = {"pps_text": 10.01, "amount_text_ps": 230_178_997 / 19_746_129, "carry_ps": 11.6569, "trust_ps": 11.6569}
    assert S.pick_trust_ps(c, [19_746_129, 23_000_000, 19_746_129], 230_178_997) == (10.01, "pps_text_checked")
    # CRAC-like: "$10.00 per share" printed beside an amount that is $10.23 a share
    c = {"pps_text": 10.00, "amount_text_ps": 176_476_946 / 17_250_000, "carry_ps": 10.2305}
    v, src = S.pick_trust_ps(c, [17_250_000, 17_250_000], 176_476_946)
    assert src == "amount_over_text_shares" and v == pytest.approx(10.2305, abs=1e-4)
    # MMTX-like: the prior period printed first; the tagged per-share price passes the identity
    c = {"pps_text": 10.07, "pps_xbrl": 10.25, "amount_text_ps": 10.2469}
    assert S.pick_trust_ps(c, [6_900_000, 6_900_000], 70_703_610) == (10.25, "pps_xbrl_checked")
    # nothing to check against: the stated value, labelled unchecked
    assert S.pick_trust_ps({"pps_text": 10.3, "trust_ps": 10.4}, [None], None) == (10.3, "pps_text_unchecked")
    assert S.pick_trust_ps({}, [], None) == (None, None)


def test_share_count_ignores_a_table_row_label():
    t = ("Plus: Accretion for Class A ordinary shares to redemption amount 19,746,129 Class A ordinary shares "
         "subject to possible redemption, June 30, 2026 $ 230,178,997")
    assert S.text_redeemable_shares(t) == []
    t2 = ("23,000,000 and none shares at redemption value of $ 10.01 and $ 0.00 per share as of June 30, 2026")
    assert S.text_redeemable_shares(t2) == [23_000_000] and S.text_redemption_value(t2) == [10.01]
    t3 = "450,000,000 shares authorized, 3,563,133 shares subject to possible redemption as of June 30, 2026"
    assert S.text_redeemable_shares(t3) == [3_563_133]


def test_liquidation_text_with_a_defined_term_in_parentheses():
    # Social Capital Hedosophia IV (CIK 1818876), 2022-09: missed before 2026-10-18
    t = ("the Company will as promptly as possible, but not more than ten business days thereafter, redeem "
         "(the “Redemption”) 100% of the Company’s issued and outstanding Class A ordinary shares")
    assert S.is_liquidation_text(t)
    assert not S.is_liquidation_text("holders may redeem their shares in connection with the extension")


# ------------------------------------------------------------------ IBKR gate (added 2026-10-19)

def test_ibkr_fixed_commission_matches_ibkrs_own_examples():
    # IBKR's "Fixed Examples" on commissions-stocks.php (read 2026-10-19).
    assert S.ibkr_fixed_commission(100, 25.0) == pytest.approx(1.00)
    assert S.ibkr_fixed_commission(1_000, 25.0) == pytest.approx(5.00)
    assert S.ibkr_fixed_commission(1_000, 0.25) == pytest.approx(2.50)     # the 1% cap binds
    with pytest.raises(ValueError):
        S.ibkr_fixed_commission(0, 10.0)


def test_ibkr_net_terms_reduces_to_the_census_grid_without_ibkr_costs(monkeypatch):
    # With commission, CAT, fee and lag all zero, the IBKR arithmetic must be the
    # census grid exactly: gross - grid_bp * 365 / days (live_splits.grid).
    monkeypatch.setattr(S, "IBKR_FIXED_PER_SHARE", 0.0)
    monkeypatch.setattr(S, "IBKR_FIXED_MIN_USD", 0.0)
    monkeypatch.setattr(S, "FINRA_CAT_PER_SHARE", 0.0)
    t = S.ibkr_net_terms(10.30, 120, 0.065, 0.041, 25_000, 0.0, 0, 30)
    assert t["spread"] == pytest.approx(0.065 - 0.0030 * 365 / 120 - 0.041)
    assert t["shares"] == 2427


def test_ibkr_net_terms_fee_lag_and_whole_shares():
    t0 = S.ibkr_net_terms(10.0, 100, 0.06, 0.04, 10_000, 0.0)
    t1 = S.ibkr_net_terms(10.0, 100, 0.06, 0.04, 10_000, 100.0)
    # USD 100 on USD 10,000 held 100 days costs 1% * 365/100 a year
    assert t0["spread"] - t1["spread"] == pytest.approx(0.01 * 365 / 100)
    lagged = S.ibkr_net_terms(10.0, 100, 0.06, 0.04, 10_000, 0.0, lag_days=21)
    assert lagged["net"] == pytest.approx(t0["net"] * 100 / 121)
    with pytest.raises(ValueError):
        S.ibkr_net_terms(10.0, 100, 0.06, 0.04, 9.0, 0.0)          # buys no whole share
    with pytest.raises(ValueError):
        S.ibkr_net_terms(10.0, 0, 0.06, 0.04, 10_000, 0.0)          # deadline passed


def test_ibkr_breakeven_ticket_is_the_first_share_count_that_repays():
    px, days, y, r = 10.0, 100, 0.07, 0.04
    be = S.ibkr_breakeven_ticket(px, days, y, r, 100.0)
    assert S.ibkr_net_terms(px, days, y, r, be, 100.0)["spread"] >= 0
    assert S.ibkr_net_terms(px, days, y, r, be - px, 100.0)["spread"] < 0
    assert S.ibkr_breakeven_ticket(px, days, 0.03, r, 100.0) is None   # below the bill: never repays


def test_ibkr_candidate_symbols():
    assert S.ibkr_candidate_symbols("AACI", "AACI;AACIU;AACIW") == ["AACI"]
    assert S.ibkr_candidate_symbols(None, "PAXG;PAXGU") == ["PAXG"]
    assert S.ibkr_candidate_symbols(float("nan"), "KCAC-UN;KCAC-WT;KCA-UN") == ["KCAC", "KCA"]
    assert S.ibkr_candidate_symbols(None, float("nan")) == []


def test_ibkr_truncated_prefix_reads_ibkrs_cut_names_and_nothing_shorter():
    assert S.ibkr_truncated_prefix("OAKTREE ACQUISITION CORP I-A", "Oaktree Acquisition Corp. III Life Sciences")
    assert S.ibkr_truncated_prefix("A SPAC III ACQUISITION-CL A", "ASPAC III Acquisition Corp.")
    assert not S.ibkr_truncated_prefix("SPAC PARTNER", "SPAC Partners Corp")          # 11 letters: too short
    assert not S.ibkr_truncated_prefix("OAKTREE ACQUISITION CORP I-A", "Oak Ridge Acquisition Corp")
    assert S.ibkr_name("PALOMA ACQUISITION COR CL-A") == "PALOMA ACQUISITION COR"
    assert S.ibkr_name("THUNDER BRIDGE CAPITAL PAR-A") == "THUNDER BRIDGE CAPITAL PAR"


def test_ibkr_match_flags_each_check_separately():
    live = pd.DataFrame([
        {"cik": 1, "symbol": "AAAA", "tickers": "AAAA;AAAAU", "name": "Alpha Acquisition Corp", "domicile": "E9"},
        {"cik": 2, "symbol": "BBBB", "tickers": "BBBB;BBBBU", "name": "Bravo Capital Acquisition Corp. III Tech",
         "domicile": "DE"},
        {"cik": 3, "symbol": "CCCC", "tickers": "CCCC", "name": "Charlie Acquisition Corp", "domicile": None},
        {"cik": 4, "symbol": None, "tickers": "DDDD;DDDDU", "name": "Delta Acquisition Corp", "domicile": "E9"},
    ])
    row = dict(type="STK", primary=True, list="NASDAQ", exchange="NASDAQ", read_utc="x")
    listing = pd.DataFrame([
        row | {"symbol": "AAAA", "conid": 11, "description": "ALPHA ACQUISITION CORP-A", "isin": "KYG000000001"},
        row | {"symbol": "BBBB", "conid": 22, "description": "BRAVO CAPITAL ACQUISITION C-A", "isin": "KYG000000002"},
        row | {"symbol": "CCCC", "conid": 33, "description": "CHARLIE ACQUISITION CORP", "isin": "US0000000003"},
        row | {"symbol": "CCCC", "conid": 34, "description": "CHARLIE ACQUISITION CORP", "isin": "US0000000004",
               "primary": False, "list": "NYSE", "exchange": "NYSE"},
    ])
    ss = pd.DataFrame([{"symbol": "AAAA", "name": "", "conid": 11, "isin": ""},
                       {"symbol": "BBBB", "name": "", "conid": 99, "isin": ""}])
    M = S.ibkr_match(live, listing, ss).set_index("cik")
    assert M.loc[1, "tradable_ibkr"] and M.loc[1, "name_rule"] == "tokens"
    assert M.loc[1, "conid_in_shortstock_agrees"] is True and M.loc[1, "isin_matches_domicile"] is True
    # truncated name admitted by its own rule; shortstock disagrees and DE vs KY disagrees: reported, not dropped
    assert M.loc[2, "tradable_ibkr"] and M.loc[2, "name_rule"] == "truncated_prefix"
    assert M.loc[2, "conid_in_shortstock_agrees"] is False and M.loc[2, "isin_matches_domicile"] is False
    # two conids under one symbol: ambiguous, never chosen between
    assert M.loc[3, "ambiguous"] and not M.loc[3, "tradable_ibkr"] and pd.isna(M.loc[3, "ibkr_conid"])
    # not listed at all
    assert not M.loc[4, "listed_ibkr"] and not M.loc[4, "tradable_ibkr"] and M.loc[4, "ibkr_n_conids"] == 0


def test_parse_ibkr_shortstock_ids():
    text = ("#BOF|2026.10.19|10:59:08\n#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE|FIGI|\n"
            "AAAA|USD|ALPHA ACQ|11|KYG000000001|3.6|0.25|1000|BBG0|\n#EOF|1\n")
    df, stamp = S.parse_ibkr_shortstock_ids(text)
    assert stamp == "2026-10-19 10:59:08" and df.to_dict("records") == [
        {"symbol": "AAAA", "name": "ALPHA ACQ", "conid": 11, "isin": "KYG000000001"}]
    with pytest.raises(S.CensusError):
        S.parse_ibkr_shortstock_ids("#BOF|2026.10.19|10:59:08\n#SYM|CUR|NAME|ISIN|\n")
    with pytest.raises(S.CensusError):
        S.parse_ibkr_shortstock_ids(text.replace("|11|", "|x|"))


def test_ibkr_election_load_shares():
    years = pd.DataFrame({"year": [2024, 2025], "extension_votes": [8, 2], "deals_completed": [3, 1],
                          "liquidations": [1, 1]})
    L = S.ibkr_election_load(years)
    assert L["share_first_event_is_vote"] == pytest.approx(14 / 16)
    assert L["share_terminal_event_is_deal"] == pytest.approx(4 / 6)
    with pytest.raises(S.CensusError):
        S.ibkr_election_load(years[years["year"] == 2024])
