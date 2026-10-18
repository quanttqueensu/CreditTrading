"""The merger-arbitrage feasibility rules (`scripts/events/merger_arb_feasibility.py`), on synthetic inputs.

WHY THESE TESTS
---------------
Every count in `results/events/MERGER_ARB_AND_IBKR_2026-10-15.md` part A
comes from a handful of rules applied to EDGAR's index. Each way they could go
wrong silently has a test:

  * `split_episodes` / `chain_start`: a company that was an ACQUIRER in an
    unrelated deal ten months earlier must not have that 425 pulled into its
    own deal date; a second takeover two years later is a second deal.
  * `link_deals` / `assemble_deals`: a joint proxy (both parties file
    DEFM14A) is ONE deal, and the target is the party that did not register
    shares. Two deals of one company far apart in time are not linked.
  * `classify_consideration`: "cash in lieu of fractional shares" appears in
    every stock deal and must NOT make it mixed (checked to fail against the
    reader without the strike-out); a cash/stock election is mixed; a tender
    offer's "net to the seller in cash" is cash; no phrase is `unclassified`,
    never a guess.
  * `final_class`: structure and text that disagree are reported as a
    conflict, never forced into one class.
  * `parse_header` raises on a page without an SGML header (a throttled or
    moved page must not read as "no parties").
  * `announcement_doc` prefers the 8-K item 1.01 in the window, then the wide
    window, then the target's 425.
  * `merger_arb_readings.verify` raises on a quote that is not in the filing
    and on a reading with no quotes.
  Added 2026-10-18, when the job resumed:
  * `resolve_components` gives roles by REGISTRATION (the S-4 filer is the
    acquirer), never by the 425 header's subject company; checked to fail
    against the replaced header rule. Blank checks, split-offs (SC TO-I) and
    ambiguous components are skipped or left unresolved, never guessed.
  * `match_acquirer` pairs a lone target with a lone acquirer only when the
    dates agree AND exactly one candidate is named in the target's document.
  * `score_sample` scores only documents that are a target's deal, treats a
    relative outside date as unmatchable by a calendar date, and compares
    numbers as numbers; `capacity_table` counts a missing borrow flag as not
    borrowable; the frozen sample is 20 unique accessions with roles and quotes.
Synthetic inputs test the code, not the market. No network: the root conftest
blocks it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.events import merger_arb_feasibility as M
from scripts.events import merger_arb_readings as R

T = pd.Timestamp


def test_split_episodes_on_a_gap_of_more_than_a_year():
    runs = M.split_episodes(["2015-01-10", "2015-03-01", "2017-06-01"], gap_days=365)
    assert [len(r) for r in runs] == [2, 1]
    assert M.split_episodes([]) == []


def test_chain_start_stops_at_a_long_gap_and_at_the_lookback():
    a0 = T("2020-06-01")
    # 425s at -30d and -100d chain (gaps 30, 70); the one at -300d is 200 days before -100d: a different deal.
    dates = [a0 - pd.Timedelta(days=k) for k in (30, 100, 300)]
    assert M.chain_start(a0, dates) == a0 - pd.Timedelta(days=100)
    # nothing before the anchor: the anchor itself
    assert M.chain_start(a0, [a0 + pd.Timedelta(days=5)]) == a0
    # beyond the look-back window, even if each gap is short
    far = [a0 - pd.Timedelta(days=k) for k in range(0, 500, 60)]
    assert M.chain_start(a0, far, lookback_days=365) >= a0 - pd.Timedelta(days=365)


def IDX(rows):
    df = pd.DataFrame(rows, columns=["cik", "company", "form", "date_filed", "accession"])
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    return df


def TICK(rows=()):
    return pd.DataFrame(list(rows), columns=["cik", "name", "ticker", "exchange"])


def test_joint_proxy_is_one_deal_and_the_non_registrant_is_the_target():
    idx = IDX([
        (1, "TARGET INC", "425", "2021-01-05", "0000000001-21-000001"),
        (2, "ACQUIRER INC", "425", "2021-01-05", "0000000001-21-000001"),
        (2, "ACQUIRER INC", "S-4", "2021-02-01", "0000000002-21-000002"),
        (1, "TARGET INC", "DEFM14A", "2021-03-01", "0000000001-21-000003"),
        (2, "ACQUIRER INC", "DEFM14A", "2021-03-01", "0000000002-21-000004"),
        (1, "TARGET INC", "25-NSE", "2021-06-01", "0000000009-21-000005"),
    ])
    d = M.assemble_deals(idx, funds=set(), tickers=TICK([(2, "ACQUIRER INC", "ACQ", "NYSE")]))
    assert len(d) == 1
    r = d.iloc[0]
    assert r["target_cik"] == 1 and r["target_rule"] == "non_registrant"
    assert r["acquirer_cik"] == 2 and r["acquirer_ticker_today"] == "ACQ"
    assert r["stock_structural"] and r["completed"] and r["listed"]
    assert r["d0"] == T("2021-01-05")


def test_cash_merger_without_425_is_cash_and_unlisted_target_is_flagged():
    idx = IDX([(5, "CASHCO", "PREM14A", "2019-01-10", "0000000005-19-000001"),
               (5, "CASHCO", "DEFM14A", "2019-02-10", "0000000005-19-000002")])
    d = M.assemble_deals(idx, funds=set(), tickers=TICK())
    r = d.iloc[0]
    assert not r["stock_structural"] and not r["completed"] and not r["listed"]


def test_two_deals_of_one_company_years_apart_are_two_deals_and_funds_are_excluded():
    idx = IDX([(7, "SERIAL CO", "DEFM14A", "2012-01-10", "0000000007-12-000001"),
               (7, "SERIAL CO", "DEFM14A", "2016-01-10", "0000000007-16-000001"),
               (8, "A FUND", "DEFM14A", "2016-01-10", "0000000008-16-000001")])
    d = M.assemble_deals(idx, funds={8}, tickers=TICK())
    assert sorted(d["target_cik"].tolist()) == [7, 7]


def test_consideration_reader_cases():
    c = M.classify_consideration
    assert c("each Share will be converted into the right to receive $36.00 in cash, without interest")["class"] == "cash"
    lieu = ("each share will be converted into the right to receive 0.4500 shares of Parent common stock, "
            "with cash in lieu of fractional shares")
    assert c(lieu)["class"] == "stock"
    assert c("holders will receive $12.50 in cash and 0.25 shares of Parent common stock for each share")["class"] == "mixed"
    elect = ("each share will be converted into the right to receive, at the election of the holder, either $40.00 "
             "in cash or 1.2 shares of Parent common stock, subject to proration")
    assert c(elect)["class"] == "mixed"
    assert c("an offer price of $22.00 per share, net to the seller in cash, without interest")["class"] == "cash"
    assert c("the parties entered into a credit agreement")["class"] == "unclassified"


def test_lieu_strikeout_is_what_keeps_a_stock_deal_stock():
    """A priced cash-in-lieu clause ("$3.25 in cash in lieu of fractional shares") is not a cash leg.

    Checked 2026-10-15 to FAIL with the strike-out removed (the reader then
    calls this stock deal mixed). Most filings price the fractional share
    without a dollar figure, which the cash pattern never matches anyway.
    """
    lieu = ("each share will be converted into the right to receive 0.4500 shares of Parent common stock, and a "
            "holder entitled to a fraction of a share will receive $3.25 in cash in lieu of fractional shares")
    joined = " ".join(M.consideration_windows(lieu))
    assert M.CASH_RE.search(joined) and M.STOCK_RE.search(joined)          # the naive reader: mixed
    assert M.classify_consideration(lieu)["class"] == "stock"


def test_final_class_reports_conflicts():
    f = M.final_class
    assert f({"stock_structural": False, "text_class": "cash"}) == "cash"
    assert f({"stock_structural": False, "text_class": "unclassified"}) == "cash"
    assert f({"stock_structural": False, "text_class": "stock"}) == "conflict_cash_stock"
    assert f({"stock_structural": True, "text_class": "mixed"}) == "mixed"
    assert f({"stock_structural": True, "text_class": "cash"}) == "conflict_stock_cash"
    assert f({"stock_structural": True, "text_class": "unclassified"}) == "stock_involved_unsplit"


HDR = """<HTML><!--
<SEC-HEADER>0000000001-26-000001.hdr.sgml : 20260917
<TYPE>425
<SUBJECT-COMPANY>
<COMPANY-DATA>
<CONFORMED-NAME>Target Co
<CIK>0000000111
<ASSIGNED-SIC>7389
</COMPANY-DATA>
<FILING-VALUES>
<FORM-TYPE>425
<FILE-NUMBER>001-12345
</FILING-VALUES>
</SUBJECT-COMPANY>
<FILED-BY>
<COMPANY-DATA>
<CONFORMED-NAME>Buyer Co
<CIK>0000000222
<ASSIGNED-SIC>5500
</COMPANY-DATA>
</FILED-BY>
</SEC-HEADER>
--></HTML>"""


def test_parse_header_roles_and_refusal():
    h = M.parse_header(HDR)
    assert h["type"] == "425"
    assert h["subject"][0]["cik"] == 111 and h["subject"][0]["assigned_sic"] == 7389
    assert h["subject"][0]["file_number"] == "001-12345"
    assert h["filed_by"][0]["cik"] == 222
    with pytest.raises(ValueError):
        M.parse_header("<html>Access Denied</html>")


def test_announcement_doc_preference():
    f = pd.DataFrame({"accessionNumber": ["a-425", "a-wide", "a-near"],
                      "filingDate": pd.to_datetime(["2024-01-02", "2023-11-01", "2024-01-03"]),
                      "form": ["425", "8-K", "8-K"], "items": ["", "1.01,9.01", "1.01,7.01,9.01"],
                      "primaryDocument": ["p425.htm", "wide.htm", "near.htm"]})
    prof = {"cik": 1, "filings": f}
    assert M.announcement_doc(prof, T("2024-01-02"), T("2024-03-01"), False)[1] == "a-near"
    prof2 = {"cik": 1, "filings": f[f["accessionNumber"] != "a-near"]}
    assert M.announcement_doc(prof2, T("2024-01-02"), T("2024-03-01"), False)[0] == "8-K 1.01 (wide)"
    prof3 = {"cik": 1, "filings": f[f["form"] == "425"]}
    assert M.announcement_doc(prof3, T("2024-01-02"), T("2024-03-01"), False)[0] == "425"
    prof4 = {"cik": 1, "filings": f.iloc[0:0]}
    assert M.announcement_doc(prof4, T("2024-01-02"), T("2024-03-01"), False) is None


def test_machine_terms_pull_ratio_outside_date_and_fee():
    text = ("each share will be converted into the right to receive 0.7850 shares of Parent common stock. "
            "The Merger Agreement may be terminated if the Merger has not been completed by the Outside Date, "
            "which is March 31, 2027, subject to extension. Company would pay a termination fee of $125 million. "
            "The obligations are not subject to any financing condition. Hart-Scott-Rodino Act waiting period.")
    m = M.machine_terms(text)
    assert m["m_ratio"] == "0.7850" and m["m_outside_date"] == "March 31, 2027"
    assert m["m_termination_fee"] == "125 million" and m["m_hsr"] and m["m_no_financing_condition"]
    assert m["m_class"] == "stock" and m["m_cash_per_share"] is None


def test_reading_verify_raises_on_a_missing_quote():
    doc = "Each share will be converted into the right to receive $36.00 in cash."
    R.verify({"quotes": {"cash_per_share": "right to receive $36.00 in cash"}}, doc, "acc")
    with pytest.raises(AssertionError):
        R.verify({"quotes": {"cash_per_share": "right to receive $37.00 in cash"}}, doc, "acc")
    with pytest.raises(ValueError):
        R.verify({"quotes": {}}, doc, "acc")
    assert R.flatten(None) == {"read": False}


def test_recent_425_components_skip_anchored_ciks():
    idx = IDX([(1, "T", "425", "2026-08-01", "0000000001-26-000001"),
               (2, "A", "425", "2026-08-01", "0000000001-26-000001"),
               (3, "T2", "425", "2026-09-01", "0000000003-26-000001"),
               (4, "A2", "425", "2026-09-01", "0000000003-26-000001")])
    deals = pd.DataFrame({"members": ["1"], "acquirer_cik": [None], "a1": [T("2026-09-15")]})
    comps = M.recent_425_components(idx, deals, T("2025-04-01"), funds=set())
    assert [c["ciks"] for c in comps] == [[3, 4]]


# ------------------------------------------------------------------ added 2026-10-18 (job 5 resumed)

def _hdr(subject: list[tuple], filed_by: list[tuple], typ: str = "425") -> str:
    """A minimal SEC header page: each party is (cik, name, sic, file_number)."""
    def block(tag, p):
        cik, name, sic, fn = p
        return (f"<{tag}>\n<COMPANY-DATA>\n<CONFORMED-NAME>{name}\n<CIK>{cik:010d}\n<ASSIGNED-SIC>{sic}\n"
                f"</COMPANY-DATA>\n<FILING-VALUES>\n<FILE-NUMBER>{fn}\n</FILING-VALUES>\n</{tag}>\n")
    body = "".join(block("SUBJECT-COMPANY", p) for p in subject) + "".join(block("FILED-BY", p) for p in filed_by)
    return f"<HTML><!--\n<SEC-HEADER>x.hdr.sgml : 20260101\n<TYPE>{typ}\n{body}</SEC-HEADER>\n--></HTML>"


class FakeEdgar:
    """Serves header pages by accession; anything else is a test bug and raises."""
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get_text(self, url, max_age_s=None, encoding="latin-1"):
        for acc, page in self.pages.items():
            if acc in url:
                return page
        raise AssertionError(f"unexpected fetch {url}")


def _comp(ciks, acc, first="2026-08-01"):
    return {"ciks": ciks, "first_acc": acc, "first_cik": ciks[0], "first": T(first), "last": T(first), "n425": 1}


def test_resolve_components_assigns_roles_by_registration_not_by_header_subject():
    """The 425 header's SUBJECT is often the issuer itself; the registrant (S-4) is the acquirer.

    Checked 2026-10-18 to FAIL against the replaced rule (target = header subject): there the
    pair below comes out with the REGISTRANT (CIK 2) as the target, which is how PNC, Amazon and
    Palo Alto Networks were listed as pending targets.
    """
    pages = {
        "0000000002-26-000001": _hdr([(2, "BUYER CORP", 6022, "001-1")], [(2, "BUYER CORP", 6022, "001-1")]),
        "0000000003-26-000001": _hdr([(3, "LONE TARGET INC", 2834, "001-3")], [(3, "LONE TARGET INC", 2834, "001-3")]),
        "0000000004-26-000001": _hdr([(4, "ISSUER INC", 3711, "001-4")], [(4, "ISSUER INC", 3711, "001-4")]),
        "0000000006-26-000001": _hdr([(6, "SPAC ACQUISITION CORP", 6770, "001-6")], [(7, "OPCO", 3711, "")]),
        "0000000008-26-000001": _hdr([(8, "PARENT CO", 3841, "001-8")], [(9, "SPINCO", 3841, "001-9")]),
    }
    reg = {2: np.array([np.datetime64("2026-08-20")]), 4: np.array([np.datetime64("2026-07-01")]),
           9: np.array([np.datetime64("2026-08-05")])}
    comps = [_comp([2, 1], "0000000002-26-000001"), _comp([3], "0000000003-26-000001"),
             _comp([4], "0000000004-26-000001"), _comp([6, 7], "0000000006-26-000001"),
             _comp([8, 9], "0000000008-26-000001")]
    splitoff = {8: np.array([np.datetime64("2026-08-10")])}
    res = M.resolve_components(FakeEdgar(pages), comps, funds=set(), live={1: "TGT", 2: "BUY"}, reg=reg,
                               today=T("2026-10-16"), splitoff=splitoff)
    by = {tuple(r["ciks"]): r for r in res}
    assert by[(2, 1)]["kind"] == "pair" and by[(2, 1)]["target_cik"] == 1 and by[(2, 1)]["acquirer_cik"] == 2
    assert by[(2, 1)]["target_ticker_today"] == "TGT" and by[(2, 1)]["acquirer_ticker_today"] == "BUY"
    assert by[(3,)]["kind"] == "target_only" and by[(3,)]["target_cik"] == 3
    assert by[(4,)]["kind"] == "acquirer_only" and by[(4,)]["acquirer_cik"] == 4
    assert by[(6, 7)]["kind"] == "skip"                       # a blank check is not a merger arbitrage
    assert by[(8, 9)]["kind"] == "skip" and "SC TO-I" in by[(8, 9)]["why"]   # split-off exchange offer


def test_resolve_components_leaves_ambiguity_unresolved():
    pages = {"0000000010-26-000001": _hdr([(10, "A CO", 1000, "001-10")], [(11, "B CO", 1000, "001-11")])}
    none_yet = M.resolve_components(FakeEdgar(pages), [_comp([10, 11], "0000000010-26-000001")], funds=set(),
                                    live={}, reg={}, today=T("2026-10-16"))
    assert none_yet[0]["kind"] == "unresolved" and none_yet[0]["why"] == "no registrant yet"
    both = {10: np.array([np.datetime64("2026-08-02")]), 11: np.array([np.datetime64("2026-08-03")])}
    two = M.resolve_components(FakeEdgar(pages), [_comp([10, 11], "0000000010-26-000001")], funds=set(),
                               live={}, reg=both, today=T("2026-10-16"))
    assert two[0]["kind"] == "unresolved" and two[0]["why"] == "2 registrants"


def test_match_acquirer_needs_the_date_window_and_exactly_one_name_in_the_document():
    acq = [{"acquirer_cik": 1, "acquirer_name": "PATRICK INDUSTRIES INC", "acquirer_ticker_today": "PATK",
            "first": T("2026-06-30")},
           {"acquirer_cik": 2, "acquirer_name": "OTHER BANCORP INC", "acquirer_ticker_today": "OTH",
            "first": T("2026-06-29")},
           {"acquirer_cik": 3, "acquirer_name": "FAR AWAY CORP", "acquirer_ticker_today": "FAR",
            "first": T("2026-03-01")}]
    doc = "entered into an Agreement and Plan of Merger with Patrick Industries, Inc. (Patrick)"
    a, why = M.match_acquirer(T("2026-07-01"), doc, acq)
    assert a["acquirer_cik"] == 1 and why.startswith("matched")
    assert M.match_acquirer(T("2026-07-01"), "a merger with a private company", acq)[0] is None
    assert M.match_acquirer(T("2026-07-01"), None, acq)[1] == "no announcement document to confirm the name"
    assert M.match_acquirer(T("2026-01-01"), doc, acq)[1] == "no acquirer_only 425 within the window"
    both = doc + " and with Other Bancorp"
    assert M.match_acquirer(T("2026-07-01"), both, acq)[0] is None          # two named: never pick one


def test_name_phrase_and_names_in_ignore_generic_words_and_punctuation():
    assert M.name_phrase("PNC FINANCIAL SERVICES GROUP, INC.") == "pnc financial"
    assert M.name_phrase("AMAZON COM INC") == "amazon"                    # 'COM' is generic
    assert M.names_in("acquired by Amazon.com, Inc.", "AMAZON COM INC")
    assert not M.names_in("acquired by Amazonia Ltd", "AMAZON COM INC")
    assert M.name_phrase("THE CORP INC") is None


def test_spac_name_rule():
    for n in ("Opes Acquisition Corp.", "CF Acquisition Corp. VIII", "FG Merger II Corp.", "Live Oak Acquisition Corp. V"):
        assert M.SPAC_NAME_RE.search(n), n
    for n in ("PNC FINANCIAL SERVICES GROUP, INC.", "Acquisition Logistics LLC", "Merger Technologies Inc"):
        assert not M.SPAC_NAME_RE.search(n), n


def test_alpaca_symbol_maps_class_shares_and_refuses_what_it_cannot_hold():
    assert M.alpaca_symbol("BRK-B") == "BRK.B"
    assert M.alpaca_symbol("PDI") == "PDI"
    assert M.alpaca_symbol("ABC-WS-A") is None or M.alpaca_symbol("ABC-WS-A") == "ABC.WS.A"
    assert M.alpaca_symbol("abc") is None                                # never guessed into another symbol


def test_freeze_out_flags_the_target_inside_the_window_only():
    idx = IDX([(1, "T", "SC 13E3", "2020-02-01", "0000000001-20-000001"),
               (9, "AFFILIATE", "SC 13E3", "2020-02-01", "0000000001-20-000001"),
               (2, "U", "SC 13E3", "2015-01-01", "0000000002-15-000001")])
    scope = pd.DataFrame({"target_cik": [1, 2], "d0": [T("2020-01-10"), T("2020-01-10")],
                          "a1": [T("2020-03-01"), T("2020-03-01")]})
    acc, flag = M.freeze_out(idx, scope)
    assert flag.tolist() == [True, False]
    assert dict(zip(acc["year"], acc["sc13e3_accessions"])) == {2015: 1, 2020: 1}   # one accession, two CIKs


def test_fee_and_number_parsers():
    assert M._fee_musd("125 million") == 125 and M._fee_musd("1.2 billion") == 1200
    assert M._fee_musd("$170,334,000") == pytest.approx(170.334) and M._fee_musd("22,540,785.00") == pytest.approx(22.540785)
    assert M._fee_musd(None) is None
    with pytest.raises(ValueError):
        M._fee_musd("approximately one hundred million")
    assert M._num("$36.00") == M._num("36.00") == 36.0 and M._num(None) is None
    assert M._date("June 14, 2027").isoformat() == "2027-06-14"
    assert M._date("six months after the date of the Merger Agreement") == "six months after the date of the Merger Agreement"


def _row(**kw):
    base = {"target": "X", "accession": "a", "read": True, "r_role": "target", "m_class": "cash",
            "m_cash_per_share": "36.00", "m_ratio": None, "m_collar": False, "m_cvr": False, "m_outside_date": None,
            "m_hsr": True, "m_other_reg": [], "m_no_financing_condition": False, "m_vote": True,
            "m_termination_fee": "62.0 million", "r_consideration": "cash", "r_cash_per_share": "$36.00",
            "r_ratio": None, "r_collar": False, "r_cvr": False, "r_outside_date": None, "r_approvals": "HSR",
            "r_vote": "target", "r_financing_cond": None, "r_term_fee": "$62.0 million"}
    base.update(kw)
    return base


def test_score_sample_outcomes_roles_and_relative_dates():
    rows = [_row(),
            _row(accession="b", m_outside_date="September 14, 2027", r_outside_date="June 14, 2027"),
            _row(accession="c", r_outside_date="one year from the date of the Merger Agreement"),
            _row(accession="d", m_termination_fee=None),
            _row(accession="e", r_role="acquirer")]
    t, by = M.score_sample(pd.DataFrame(rows))
    assert t.loc["outside date", "agree"] == 2 and t.loc["outside date", "wrong"] == 1
    assert t.loc["outside date", "missed"] == 1                         # a relative date the machine cannot match
    assert t.loc["termination fee", "missed"] == 1 and t.loc["cash per share", "agree"] == 4
    assert t.loc["(document is not a target's deal: excluded below)", "wrong"] == 1
    assert by.set_index("accession").loc["a", "fields_not_agreeing"] == 0
    assert by.set_index("accession").loc["e", "fields_scored"] == 0


def test_capacity_table_counts_none_flags_as_not_borrowable():
    pend = pd.DataFrame({"final_class": ["cash", "stock", "stock", "mixed"],
                         "tgt_adv_usd": [1e6, 5e6, 5e6, 5e6], "acq_adv_usd": [None, 5e6, 5e6, 1e5],
                         "acq_alp_shortable": [None, True, None, True], "acq_alp_etb": [None, True, None, True]})
    c = M.capacity_table(pend).set_index("position_usd")
    assert c.loc[50_000, "cash_fit"] == 1 and c.loc[50_000, "stock_deals"] == 3
    assert c.loc[50_000, "stock_borrow_ok"] == 2                          # None is not True
    assert c.loc[50_000, "stock_fit_both_legs"] == 1                      # the thin acquirer fails


def test_frozen_sample_and_readings_are_well_formed():
    """The 20 were frozen before reading (commit f024f2a); every reading names a role and carries quotes."""
    accs = R.SAMPLE_ACCESSIONS
    assert R.SAMPLE_DRAWN == "2026-10-18" and len(accs) == 20 and len(set(accs)) == 20
    assert set(R.READINGS) <= set(accs)
    for acc, rd in R.READINGS.items():
        assert rd.get("role") in ("target", "acquirer", "reorganisation", "wrong_document"), acc
        assert rd.get("quotes"), acc
        if rd["role"] == "target":
            assert rd.get("consideration") in ("cash", "stock", "mixed"), acc
