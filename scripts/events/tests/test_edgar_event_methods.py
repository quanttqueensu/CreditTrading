"""Parsers behind the EDGAR-dated merger pair and gate G6 (plan 0.7), on literal strings.

WHY THESE TESTS
---------------
* `name_score` decides which EDGAR fund a CRSP merger target IS. A wrong
  match dates a deal by another fund's filing and nothing errors. The cases
  below are the ones that went wrong in the first pass on 2026-10-12: a state
  code read as an abbreviation (MA matched Maryland as well as Massachusetts),
  a fund number ignored (FUND 2 vs FUND 3), spaced initials (R M R, F S K K R)
  and CRSP's own typo (NUVEEEN).
* `mentions_target` is the read-before-use check on the filing that dates a
  deal; a bare short ticker must not count.
* `classify_tender` separates a NAV tender for common shares from a tender for
  auction-rate preferreds; G6 counts only the first.
* `event_mask` / `event_short_pnl` must apply the house execution convention
  (shift(2) inside `evaluate`) to exactly the shorts inside a window.
* `clustered_t` and `grid_table` are the merger pair's reporting arithmetic.
* `filing_txt_url` refuses a float CIK: EDGAR answers a malformed archive path
  with 403, its throttling code, which cost twelve minutes of back-off once.
Synthetic inputs test the code, not the market. No network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.data.edgar_client import filing_txt_url
from scripts.events import edgar_merger_dates as emd
from scripts.events import g6_corporate_action_shorts as g6
from scripts.events import merger_pairs as mp


def S(a, b):
    return emd.name_score(emd.name_tokens(a), emd.name_tokens(b))


def test_abbreviations_and_typos_match():
    assert S("NUVEEN NY QLTY INCOME MUN FD INC", "NUVEEN NEW YORK QUALITY INCOME MUNICIPAL FUND INC") == 1.0
    assert S("NUVEEEN CONN DIV ADV MUN FD", "NUVEEN CONNECTICUT DIVIDEND ADVANTAGE MUNICIPAL FUND") == 1.0
    assert S("INVESCO VAN KAMPN CA VL MN IN TR",
             "INVESCO VAN KAMPEN CALIFORNIA VALUE MUNICIPAL INCOME TRUST") > 0.9
    assert S("NUVEEN NC DIV ADV MUNI FD 3", "NUVEEN NORTH CAROLINA DIVIDEND ADVANTAGE MUNICIPAL FUND 3") == 1.0


def test_numbers_must_agree():
    right = S("NUVEEN NC DIV ADV MUNI FD 3", "NUVEEN NORTH CAROLINA DIVIDEND ADVANTAGE MUNICIPAL FUND 3")
    wrong = S("NUVEEN NC DIV ADV MUNI FD 3", "NUVEEN NORTH CAROLINA DIVIDEND ADVANTAGE MUNICIPAL FUND 2")
    none_ = S("NUVEEN NC DIV ADV MUN FD", "NUVEEN NORTH CAROLINA DIVIDEND ADVANTAGE MUNICIPAL FUND 2")
    assert right - wrong > 0.4 and none_ < 0.85
    assert S("BLACKROCK CREDIT ALL INC TR II", "BLACKROCK CREDIT ALLOCATION INCOME TRUST IV") < 0.5


def test_state_codes_are_states():
    ma = "NUVEEN MA PREM INC MUN FD"
    assert S(ma, "NUVEEN MASSACHUSETTS PREMIUM INCOME MUNICIPAL FUND") - \
        S(ma, "NUVEEN MARYLAND PREMIUM INCOME MUNICIPAL FUND") >= emd.MIN_MARGIN
    mi = "NUVEEN MI QLTY INC MUNI FD INC"
    assert S(mi, "NUVEEN MICHIGAN QUALITY INCOME MUNICIPAL FUND INC") > \
        S(mi, "NUVEEN MISSOURI QUALITY MUNICIPAL INCOME FUND")


def test_spaced_initials():
    assert S("R M R REAL ESTATE INCOME FUND", "RMR REAL ESTATE INCOME FUND") == 1.0
    assert S("F S K K R CAPITAL CORP II", "FS KKR Capital Corp. II") >= 0.95
    assert S("F S K K R CAPITAL CORP", "FS KKR Capital Corp. II") < 0.85


def test_tokens():
    assert emd.name_tokens("Nuveen Dow 30sm Dynamic Overwrite Fund") == \
        ("NUVEEN", "DOW", "30", "SM", "DYNAMIC", "OVERWRITE", "FUND")
    assert emd.name_tokens("BLACKROCK MUNIYIELD FUND INC /MD/")[-1] == "INC"
    with pytest.raises(ValueError):
        emd.name_tokens(float("nan"))


def test_match_cik_reports_ambiguity_rather_than_choosing():
    # two CIKs carrying the same name at the same time (a fund and the one that later took its name)
    names = pd.DataFrame({"cik": [1, 2], "company": ["X MUNI FUND", "X Muni Fund"],
                          "first": pd.to_datetime(["2010-01-01"] * 2), "last": pd.to_datetime(["2012-01-01"] * 2)})
    names["tok"] = names["company"].map(emd.name_tokens)
    m = emd.match_cik("X MUNI FD", names, pd.Timestamp("2011-01-01"), pd.Timestamp("2011-06-01"))
    assert m["status"].startswith("ambiguous")
    m = emd.match_cik("X MUNI FD", names, pd.Timestamp("2013-01-01"), pd.Timestamp("2013-06-01"))
    assert m["status"] == "no EDGAR names in use in the window"


def test_mentions_target():
    txt = "<p>Nuveen New York Quality Income Municipal Fund, Inc. (NYSE: NUN) will merge</p>"
    assert emd.mentions_target(txt, ["NUVEEN NEW YORK QUALITY INCOME MUNICIPAL FUND INC"], None) == "name"
    assert emd.mentions_target(txt, [], "NUN") == "ticker"
    assert emd.mentions_target("IF the merger is approved", [], "IF") is None
    assert emd.mentions_target("Aberdeen Indonesia Fund (NYSE American: IF)", [], "IF") == "ticker"
    assert emd.mentions_target("another fund entirely", ["NUVEEN NEW YORK FUND"], "NNY") is None


COVER = """SCHEDULE TO ... PIMCO Corporate &amp; Income Opportunity Fund (Name of Subject Company (Issuer))
 ... (Name of Filing Person (Offeror)) <b>Auction Rate Preferred Shares</b> (Title of Class of Securities)
 72201B200 (CUSIP Number of Class of Securities)"""


def test_classify_tender():
    assert g6.classify_tender(COVER) == "preferred"
    common = COVER.replace("Auction Rate Preferred Shares", "Common Shares of Beneficial Interest")
    assert g6.classify_tender(common) == "common"
    assert g6.classify_tender("no cover page here") == "unknown"
    # A common-share offer that MENTIONS the preferreds elsewhere is still common.
    assert g6.classify_tender(common + " the Fund's preferred shares are not affected") == "common"
    assert g6.classify_tender(COVER + common) == "unknown"   # two cover lines that disagree


def test_scan_proxy():
    h = g6.scan_proxy("<p>Proposal 2: to approve a Plan of Liquidation of the Fund</p>")
    assert "liquidation" in h and "open_end" not in h
    assert "open_end" in g6.scan_proxy("a proposal to convert the Fund to an open-end investment company")


def _frame(vals, cols=("A", "B")):
    idx = pd.bdate_range("2020-01-06", periods=len(vals))
    return pd.DataFrame(vals, index=idx, columns=list(cols))


def test_event_short_pnl_uses_shift2_and_only_window_shorts():
    H = _frame([[-0.1, 0.1]] * 6)
    R = _frame([[0.01, 0.02]] * 6)
    w = pd.DataFrame({"ticker": ["A"], "start": [H.index[1]], "end": [H.index[2]]})
    M = g6.event_mask(H.index, H.columns, w)
    pnl, Spos = g6.event_short_pnl(H, R, M)
    # decided on days 1 and 2 -> earned on days 3 and 4; B (a long) never counts
    assert list(np.round(pnl.values, 6)) == [0, 0, 0, -0.001, -0.001, 0]
    assert (Spos["B"] == 0).all()


def test_event_mask_validates():
    idx = pd.bdate_range("2020-01-06", periods=3)
    with pytest.raises(KeyError):
        g6.event_mask(idx, ["A"], pd.DataFrame({"ticker": ["Z"], "start": [idx[0]], "end": [idx[1]]}))
    with pytest.raises(ValueError):
        g6.event_mask(idx, ["A"], pd.DataFrame({"ticker": ["A"], "start": [idx[2]], "end": [idx[0]]}))


def test_assert_causal():
    w = pd.DataFrame({"ticker": ["A"], "start": ["2020-01-02"], "first_filing": ["2020-01-03"]})
    with pytest.raises(AssertionError):
        g6.assert_causal(w)


def test_clustered_t_matches_iid_when_singletons():
    v = pd.Series([1.0, 2.0, 3.0, 6.0])
    t = mp.clustered_t(v, pd.Series(["a", "b", "c", "d"]))
    n = len(v)
    iid = v.mean() / np.sqrt((n / (n - 1)) * ((v - v.mean()) ** 2).sum() / n ** 2)
    assert t == pytest.approx(iid)
    # one group per pair of identical values halves the information
    t2 = mp.clustered_t(pd.Series([1.0, 1.0, 3.0, 3.0]), pd.Series(["a", "a", "b", "b"]))
    assert np.isfinite(t2)


def test_grid_table_nets():
    g = mp.grid_table(pd.Series([0.01, 0.02, 0.03]), pd.Series(["a", "b", "c"]))
    assert g["median_bp"] == 200.0
    assert g["net_median_bp"]["15bp_x2"] == 170.0 and g["net_median_bp"]["30bp_x4"] == 80.0


def test_filing_txt_url_validates():
    assert filing_txt_url(1195739.0, "0001193125-12-280520") == \
        "https://www.sec.gov/Archives/edgar/data/1195739/000119312512280520/0001193125-12-280520.txt"
    with pytest.raises(ValueError):
        filing_txt_url(1195739.5, "0001193125-12-280520")
    with pytest.raises(ValueError):
        filing_txt_url(1195739, "1193125-12-280520")


def test_merger_agreement_language():
    assert emd.merger_agreement_language("Item 1.01 ... entered into an Agreement and Plan of Merger (the "
                                         "&ldquo;Merger Agreement&rdquo;)")
    assert not emd.merger_agreement_language("Item 1.01 Entry into a Material Definitive Agreement: "
                                             "the Company amended its senior secured revolving credit facility")


def test_name_core_and_entities():
    assert emd._name_core("BLACKROCK MUNIYIELD FUND INC /MD/") == "BLACKROCK MUNIYIELD FUND"
    assert emd.mentions_target("Lazard World Dividend &amp; Income Fund (LOR) will", 
                               ["LAZARD WORLD DIVIDEND & INCOME FUND INC"], None) == "name"


def test_plural_and_parentheticals():
    assert S("NUVEEN PFD INCOME OPPTY FUND", "Nuveen Preferred Income Opportunities Fund") == 1.0
    assert S("GUGGENHEIM ENHANCED EQTY INC FD",
             "Guggenheim Enhanced Equity Income Fund (f/k/a Old Mutual/Claymore Long-Short Fund)") == 1.0


def test_last_episode_start():
    d = pd.to_datetime(["2019-07-01", "2019-08-15", "2019-12-10", "2020-11-24", "2021-02-01", "2021-07-01"])
    assert emd.last_episode_start(pd.Series(d), pd.Timestamp("2021-06-16")) == pd.Timestamp("2020-11-24")
    # one continuous run keeps its first date
    assert emd.last_episode_start(pd.Series(d[:3]), pd.Timestamp("2020-01-01")) == pd.Timestamp("2019-07-01")
    assert emd.last_episode_start(pd.Series([], dtype="datetime64[ns]"), pd.Timestamp("2020-01-01")) is None


def test_main_document_drops_exhibits():
    txt = ("<SEC-HEADER>...</SEC-HEADER>\n<DOCUMENT>\n<TYPE>8-K\n<TEXT>Item 1.01 credit facility</TEXT>\n"
           "</DOCUMENT>\n<DOCUMENT>\n<TYPE>EX-10.1\n<TEXT>Merger Documents means the Agreement and Plan of "
           "Merger</TEXT>\n</DOCUMENT>\n")
    body = emd.main_document(txt, "8-K")
    assert "credit facility" in body and not emd.merger_agreement_language(body)
    assert emd.merger_agreement_language(txt)          # the whole submission would have passed
    with pytest.raises(ValueError):
        emd.main_document(txt, "425")
